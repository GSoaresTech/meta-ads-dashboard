"""Cliente da Marketing API: toda extração da Meta passa por aqui.

Chama só os endpoints de Endpoint, com a versão de VERSAO_API_META (RF-10),
pagina pelo cursor e tenta de novo os erros de limite e os transitórios
conforme etl.limites_api_meta (RF-08). Os erros definitivos sobem como
exceções tipadas que levam só o tipo e os códigos da Meta: a mensagem dela
pode trazer nome de campanha ou ID e nunca é guardada (RNF-17).

O token vai no cabeçalho de autorização, nunca na URL nem nos parâmetros
(ADR-0009). Relógio, espera e sorteio do jitter são injetáveis, para os
testes não dormirem.
"""

import random
import re
import time
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Final

import requests

from etl.configuracao import (
    INTERVALO_CONSULTA_RELATORIO_SEGUNDOS,
    TEMPO_LIMITE_REQUISICAO_SEGUNDOS,
    TEMPO_MAXIMO_RELATORIO_SEGUNDOS,
    URL_BASE_API_META,
    VERSAO_API_META,
)
from etl.limites_api_meta import (
    ErroGraph,
    TipoErro,
    UsoApi,
    calcular_pausa_preventiva,
    classificar_codigo,
    classificar_erro,
    decidir_espera,
    ler_erro_graph,
    ler_inteiro,
    ler_uso,
)


class Endpoint(StrEnum):
    """Lista explícita dos endpoints que a ETL chama (RNF-24).

    O valor é a aresta pedida sob o objeto; OBJETO lê o próprio objeto: a
    conta, o relatório assíncrono, a Página ou a publicação. Nenhum endpoint
    de leads entra aqui, e o cliente recusa o que estiver fora da lista.
    """

    OBJETO = ""
    CAMPANHAS = "campaigns"
    CONJUNTOS = "adsets"
    ANUNCIOS = "ads"
    CRIATIVOS = "adcreatives"
    INSIGHTS = "insights"


# IDs da Meta são numeric strings; a conta é act_ seguido do número, e o ID
# da publicação junta o da Página e o do post com _ (R-35). Recusar qualquer
# outro formato impede que um caminho no ID escape da lista de endpoints.
PADRAO_ID_OBJETO: Final = re.compile(r"(act_)?[0-9]+(_[0-9]+)?")
STATUS_HTTP_ERRO: Final = 400
GET: Final = "GET"
POST: Final = "POST"
PADRAO_ID_RELATORIO: Final = re.compile(r"[0-9]+")
# Estados do job assíncrono, conferidos em 04/11/2026 em
# https://developers.facebook.com/docs/marketing-api/insights/best-practices.
STATUS_JOB_CONCLUIDO: Final = "Job Completed"
STATUS_JOB_SEM_CONCLUSAO: Final = frozenset({"Job Failed", "Job Skipped"})
PERCENTUAL_JOB_CONCLUIDO: Final = 100
# Só os códigos do erro do job: a mensagem e o título podem trazer nome de
# campanha (RNF-17).
CAMPOS_ESTADO_RELATORIO: Final = (
    "async_status,async_percent_completion,error_code,error_subcode"
)
SEM_USO: Final = UsoApi(percentual=0, espera_recuperacao_segundos=0)


class ErroApiMeta(Exception):
    """Erro definitivo da Marketing API, sem nova tentativa."""

    TIPO: str = TipoErro.DEFINITIVO

    def __init__(
        self,
        codigo: int | None = None,
        subcodigo: int | None = None,
        tentativas: int = 1,
    ) -> None:
        self.codigo = codigo
        self.subcodigo = subcodigo
        self.tentativas = tentativas
        super().__init__(
            f"Marketing API: {self.TIPO}; código {codigo}, subcódigo {subcodigo}, "
            f"{tentativas} tentativa(s)"
        )


class ErroLimiteTaxa(ErroApiMeta):
    """Limite de taxa que persistiu até MAXIMO_TENTATIVAS ou cuja recuperação
    passa da espera máxima."""

    TIPO = TipoErro.LIMITE_TAXA


class ErroTransitorio(ErroApiMeta):
    """Erro temporário que persistiu até MAXIMO_TENTATIVAS."""

    TIPO = TipoErro.TRANSITORIO


class ErroTempoEsgotado(ErroTransitorio):
    TIPO = TipoErro.TEMPO_ESGOTADO


class ErroExcessoLinhas(ErroApiMeta):
    """A consulta pede linhas demais (R-39): fatie o intervalo."""

    TIPO = TipoErro.EXCESSO_LINHAS


class ErroAutenticacao(ErroApiMeta):
    """Token inválido, expirado ou revogado: vale para todas as empresas."""

    TIPO = TipoErro.AUTENTICACAO


class ErroPermissao(ErroApiMeta):
    TIPO = TipoErro.PERMISSAO


class ErroJobAssincrono(ErroApiMeta):
    """Job falho, expirado ou sem conclusão até TEMPO_MAXIMO_RELATORIO_SEGUNDOS."""

    TIPO = "job assíncrono sem conclusão"


class ErroRespostaInvalida(ErroApiMeta):
    """Resposta de sucesso fora do formato da Graph API."""

    TIPO = "resposta fora do formato esperado"


EXCECOES_POR_TIPO: Final[Mapping[TipoErro, type[ErroApiMeta]]] = {
    TipoErro.LIMITE_TAXA: ErroLimiteTaxa,
    TipoErro.TRANSITORIO: ErroTransitorio,
    TipoErro.TEMPO_ESGOTADO: ErroTempoEsgotado,
    TipoErro.EXCESSO_LINHAS: ErroExcessoLinhas,
    TipoErro.AUTENTICACAO: ErroAutenticacao,
    TipoErro.PERMISSAO: ErroPermissao,
    TipoErro.DEFINITIVO: ErroApiMeta,
}


class FalhaChamada(Exception):
    """Falha de uma chamada, ainda sujeita a nova tentativa."""

    def __init__(
        self,
        tipo: TipoErro,
        erro: ErroGraph | None = None,
        uso: UsoApi = SEM_USO,
    ) -> None:
        super().__init__(tipo)
        self.tipo = tipo
        self.erro = erro
        self.uso = uso


class ClienteApiMeta:
    def __init__(
        self,
        token: str,
        *,
        sessao: requests.Session | None = None,
        dormir: Callable[[float], None] = time.sleep,
        relogio: Callable[[], float] = time.monotonic,
        sortear: Callable[[], float] = random.random,
    ) -> None:
        self._cabecalhos = {"Authorization": f"Bearer {token}"}
        self._sessao = sessao if sessao is not None else requests.Session()
        self._dormir = dormir
        self._relogio = relogio
        self._sortear = sortear
        self._pausa = 0.0

    def obter(
        self, objeto_id: str, endpoint: Endpoint, parametros: Mapping[str, str]
    ) -> dict[str, object]:
        """Uma chamada GET, sem paginação."""
        return self._requisitar(GET, montar_url(objeto_id, endpoint), parametros)

    def paginar(
        self, objeto_id: str, endpoint: Endpoint, parametros: Mapping[str, str]
    ) -> list[dict[str, object]]:
        """Todas as páginas, na ordem, cada uma como a Meta a devolveu.

        Devolve a lista só no fim, para que uma falha no meio não deixe
        páginas soltas com quem chamou.
        """
        return self._paginar(montar_url(objeto_id, endpoint), parametros)

    def ler_insights(
        self, objeto_id: str, parametros: Mapping[str, str]
    ) -> list[dict[str, object]]:
        """Insights pela consulta síncrona; se ela falhar por excesso de linhas
        ou por tempo, a mesma consulta é refeita por job assíncrono (RF-08).

        O tempo esgotado na síncrona não é tentado de novo, porque a mesma
        consulta tende a esgotá-lo outra vez. Se o job também falhar por
        excesso de linhas, o ErroExcessoLinhas sobe para quem chamou fatiar o
        intervalo (R-39).
        """
        url = montar_url(objeto_id, Endpoint.INSIGHTS)
        try:
            return self._paginar(url, parametros, repetir_tempo_esgotado=False)
        except (ErroExcessoLinhas, ErroTempoEsgotado):
            return self.executar_relatorio_assincrono(objeto_id, parametros)

    def executar_relatorio_assincrono(
        self, objeto_id: str, parametros: Mapping[str, str]
    ) -> list[dict[str, object]]:
        """Cria o job de insights, consulta o report_run_id até Job Completed
        e devolve as páginas do resultado (R-18).

        Uma criação repetida por erro transitório pode deixar um job a mais
        na Meta, o que é inócuo: o job só lê. O resultado é lido com o mesmo
        limit da consulta, para não cair no tamanho de página padrão da Meta
        e gastar a cota com páginas pequenas.
        """
        url = montar_url(objeto_id, Endpoint.INSIGHTS)
        relatorio_id = ler_id_relatorio(self._requisitar(POST, url, parametros))
        self._aguardar_relatorio(relatorio_id)
        leitura = {"limit": parametros["limit"]} if "limit" in parametros else {}
        return self._paginar(montar_url(relatorio_id, Endpoint.INSIGHTS), leitura)

    def _aguardar_relatorio(self, relatorio_id: str) -> None:
        url = montar_url(relatorio_id, Endpoint.OBJETO)
        inicio = self._relogio()
        while True:
            estado = self._requisitar(GET, url, {"fields": CAMPOS_ESTADO_RELATORIO})
            if relatorio_concluido(estado):
                return
            if estado.get("async_status") in STATUS_JOB_SEM_CONCLUSAO:
                raise montar_excecao_job(estado)
            if self._relogio() - inicio >= TEMPO_MAXIMO_RELATORIO_SEGUNDOS:
                raise ErroJobAssincrono()
            self._dormir(INTERVALO_CONSULTA_RELATORIO_SEGUNDOS)

    def _paginar(
        self,
        url: str,
        parametros: Mapping[str, str],
        *,
        repetir_tempo_esgotado: bool = True,
    ) -> list[dict[str, object]]:
        paginas: list[dict[str, object]] = []
        cursor: str | None = None
        while not paginas or cursor is not None:
            pagina_parametros = (
                {**parametros, "after": cursor} if cursor else parametros
            )
            paginas.append(
                self._requisitar(
                    GET,
                    url,
                    pagina_parametros,
                    repetir_tempo_esgotado=repetir_tempo_esgotado,
                )
            )
            cursor = ler_cursor_seguinte(paginas[-1])
        return paginas

    def _requisitar(
        self,
        metodo: str,
        url: str,
        parametros: Mapping[str, str],
        *,
        repetir_tempo_esgotado: bool = True,
    ) -> dict[str, object]:
        validar_parametros(parametros)
        tentativa = 1
        while True:
            try:
                corpo = self._enviar(metodo, url, parametros)
            except FalhaChamada as falha:
                espera = decidir_espera(
                    falha.tipo, tentativa, falha.uso, self._sortear()
                )
                if falha.tipo is TipoErro.TEMPO_ESGOTADO and not repetir_tempo_esgotado:
                    espera = None
                if espera is None:
                    raise montar_excecao(falha, tentativa) from None
            else:
                if isinstance(corpo, dict):
                    return corpo
                raise ErroRespostaInvalida(tentativas=tentativa)
            self._dormir(espera)
            tentativa += 1

    def _enviar(self, metodo: str, url: str, parametros: Mapping[str, str]) -> object:
        self._respeitar_pausa()
        resposta = self._chamar(metodo, url, parametros)
        if isinstance(resposta, TipoErro):
            raise FalhaChamada(resposta)
        uso = ler_uso(resposta.headers)
        corpo = ler_corpo(resposta)
        erro = ler_erro_graph(corpo)
        if resposta.status_code >= STATUS_HTTP_ERRO or erro is not None:
            raise FalhaChamada(classificar_erro(resposta.status_code, erro), erro, uso)
        self._pausa = calcular_pausa_preventiva(uso)
        return corpo

    def _chamar(
        self, metodo: str, url: str, parametros: Mapping[str, str]
    ) -> requests.Response | TipoErro:
        """A falha de rede volta como tipo, e não como exceção relançada: a
        do requests traz a URL, com o ID da conta, e ficaria no __context__
        da exceção que chega a quem chamou (RNF-17)."""
        try:
            return self._sessao.request(
                metodo,
                url,
                params=parametros if metodo == GET else None,
                data=parametros if metodo == POST else None,
                headers=self._cabecalhos,
                timeout=TEMPO_LIMITE_REQUISICAO_SEGUNDOS,
            )
        except (requests.ConnectionError, requests.exceptions.ChunkedEncodingError):
            return TipoErro.TRANSITORIO
        except requests.Timeout:
            return TipoErro.TEMPO_ESGOTADO

    def _respeitar_pausa(self) -> None:
        if self._pausa > 0:
            self._dormir(self._pausa)
            self._pausa = 0.0


def montar_url(objeto_id: str, endpoint: Endpoint) -> str:
    """Os erros não citam o valor recebido, que pode ser um ID da Meta."""
    if not isinstance(objeto_id, str):
        raise TypeError("objeto_id: deve ser texto")
    if not PADRAO_ID_OBJETO.fullmatch(objeto_id):
        raise ValueError("objeto_id: fora do formato de ID da Meta")
    if not isinstance(endpoint, Endpoint):
        raise TypeError("endpoint: fora da lista de Endpoint")
    caminho = f"{objeto_id}/{endpoint.value}" if endpoint.value else objeto_id
    return f"{URL_BASE_API_META}/{VERSAO_API_META}/{caminho}"


def validar_parametros(parametros: Mapping[str, str]) -> None:
    if "access_token" in parametros:
        raise ValueError(
            "parametros: o access_token vai só no cabeçalho de autorização"
        )


def ler_corpo(resposta: requests.Response) -> object:
    try:
        return resposta.json()
    except requests.exceptions.JSONDecodeError:
        return None


def ler_cursor_seguinte(pagina: Mapping[str, object]) -> str | None:
    """O cursor da página seguinte, ou None na última.

    A Graph API indica a última página pela ausência de paging.next. Seguimos
    pelo cursor after, e não pelo link next, para que a URL chamada seja
    sempre montada aqui, dentro da lista de endpoints.
    """
    paginacao = pagina.get("paging")
    if not isinstance(paginacao, dict) or "next" not in paginacao:
        return None
    cursores = paginacao.get("cursors")
    cursor = cursores.get("after") if isinstance(cursores, dict) else None
    if isinstance(cursor, str) and cursor:
        return cursor
    raise ErroRespostaInvalida()


def montar_excecao(falha: FalhaChamada, tentativas: int) -> ErroApiMeta:
    erro = falha.erro
    return EXCECOES_POR_TIPO[falha.tipo](
        codigo=erro.codigo if erro else None,
        subcodigo=erro.subcodigo if erro else None,
        tentativas=tentativas,
    )


def ler_id_relatorio(criacao: Mapping[str, object]) -> str:
    """A documentação mostra o report_run_id como número JSON; o int do
    Python não perde dígitos, e o ID segue como texto (CLAUDE.md §5)."""
    valor = criacao.get("report_run_id")
    texto = str(valor) if type(valor) is int else valor
    if isinstance(texto, str) and PADRAO_ID_RELATORIO.fullmatch(texto):
        return texto
    raise ErroRespostaInvalida()


def relatorio_concluido(estado: Mapping[str, object]) -> bool:
    return (
        estado.get("async_status") == STATUS_JOB_CONCLUIDO
        and estado.get("async_percent_completion") == PERCENTUAL_JOB_CONCLUIDO
    )


def montar_excecao_job(estado: Mapping[str, object]) -> ErroApiMeta:
    """O job que falha por excesso de linhas vira ErroExcessoLinhas, para quem
    chamou fatiar o intervalo; os demais, ErroJobAssincrono."""
    erro = ErroGraph(
        codigo=ler_inteiro(estado.get("error_code")),
        subcodigo=ler_inteiro(estado.get("error_subcode")),
        transitorio=False,
    )
    tipo = TipoErro.DEFINITIVO if erro.codigo is None else classificar_codigo(erro)
    excecao = (
        ErroExcessoLinhas if tipo is TipoErro.EXCESSO_LINHAS else ErroJobAssincrono
    )
    return excecao(codigo=erro.codigo, subcodigo=erro.subcodigo)
