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
    TEMPO_LIMITE_REQUISICAO_SEGUNDOS,
    URL_BASE_API_META,
    VERSAO_API_META,
)
from etl.limites_api_meta import (
    ErroGraph,
    TipoErro,
    UsoApi,
    calcular_pausa_preventiva,
    classificar_erro,
    decidir_espera,
    ler_erro_graph,
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
        return self._requisitar(montar_url(objeto_id, endpoint), parametros)

    def paginar(
        self, objeto_id: str, endpoint: Endpoint, parametros: Mapping[str, str]
    ) -> list[dict[str, object]]:
        """Todas as páginas, na ordem, cada uma como a Meta a devolveu.

        Devolve a lista só no fim, para que uma falha no meio não deixe
        páginas soltas com quem chamou.
        """
        url = montar_url(objeto_id, endpoint)
        paginas = [self._requisitar(url, parametros)]
        while (cursor := ler_cursor_seguinte(paginas[-1])) is not None:
            paginas.append(self._requisitar(url, {**parametros, "after": cursor}))
        return paginas

    def _requisitar(self, url: str, parametros: Mapping[str, str]) -> dict[str, object]:
        validar_parametros(parametros)
        tentativa = 1
        while True:
            try:
                corpo = self._enviar(url, parametros)
            except FalhaChamada as falha:
                espera = decidir_espera(
                    falha.tipo, tentativa, falha.uso, self._sortear()
                )
                if espera is None:
                    raise montar_excecao(falha, tentativa) from None
            else:
                if isinstance(corpo, dict):
                    return corpo
                raise ErroRespostaInvalida(tentativas=tentativa)
            self._dormir(espera)
            tentativa += 1

    def _enviar(self, url: str, parametros: Mapping[str, str]) -> object:
        self._respeitar_pausa()
        # from None em toda falha: a exceção do requests traz a URL, com o ID
        # da conta, e não pode ir encadeada para o log.
        try:
            resposta = self._sessao.get(
                url,
                params=parametros,
                headers=self._cabecalhos,
                timeout=TEMPO_LIMITE_REQUISICAO_SEGUNDOS,
            )
        except (requests.ConnectionError, requests.exceptions.ChunkedEncodingError):
            raise FalhaChamada(TipoErro.TRANSITORIO) from None
        except requests.Timeout:
            raise FalhaChamada(TipoErro.TEMPO_ESGOTADO) from None
        uso = ler_uso(resposta.headers)
        corpo = ler_corpo(resposta)
        erro = ler_erro_graph(corpo)
        if resposta.status_code >= STATUS_HTTP_ERRO or erro is not None:
            raise FalhaChamada(classificar_erro(resposta.status_code, erro), erro, uso)
        self._pausa = calcular_pausa_preventiva(uso)
        return corpo

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
