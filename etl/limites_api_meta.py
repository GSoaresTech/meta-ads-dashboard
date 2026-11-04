"""Regras dos limites da Marketing API, em funções puras.

Classifica os erros da Graph API, lê os cabeçalhos de uso e calcula as
esperas do backoff (RF-08; R-15; R-37). O I/O fica no cliente, que chama
estas funções. Códigos e cabeçalhos conferidos em 04/11/2026 em
https://developers.facebook.com/docs/marketing-api/overview/rate-limiting,
https://developers.facebook.com/docs/graph-api/overview/rate-limiting e
https://developers.facebook.com/docs/graph-api/guides/error-handling.
"""

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from etl.configuracao import (
    ESPERA_INICIAL_SEGUNDOS,
    ESPERA_MAXIMA_SEGUNDOS,
    LIMITE_USO_PERCENTUAL,
    MAXIMO_TENTATIVAS,
)

# Os códigos de limite do RF-08. O 613 e o 17 também cobrem limites de
# escrita, que a ETL não faz; tratá-los todos como limite não muda a leitura.
CODIGOS_LIMITE_TAXA: Final = frozenset({4, 17, 613, *range(80000, 80015)})
# Erros que a Meta descreve como temporários, a tentar de novo mais tarde:
# 1 (desconhecido), 2 (serviço) e 341 (limite do aplicativo por instabilidade).
CODIGOS_TRANSITORIOS: Final = frozenset({1, 2, 341})
CODIGOS_AUTENTICACAO: Final = frozenset({102, 190})
CODIGOS_PERMISSAO: Final = frozenset({10, *range(200, 300)})
CODIGO_EXCESSO_LINHAS: Final = 100
SUBCODIGO_EXCESSO_LINHAS: Final = 1487534
STATUS_HTTP_ERRO_SERVIDOR: Final = 500

CABECALHO_USO_NEGOCIO: Final = "X-Business-Use-Case-Usage"
CABECALHO_USO_CONTA: Final = "X-Ad-Account-Usage"
CABECALHO_USO_INSIGHTS: Final = "X-FB-Ads-Insights-Throttle"
CAMPOS_PERCENTUAL_NEGOCIO: Final = ("call_count", "total_cputime", "total_time")
CAMPOS_PERCENTUAL_INSIGHTS: Final = ("app_id_util_pct", "acc_id_util_pct")
CAMPOS_PERCENTUAL_CONTA: Final = ("acc_id_util_pct",)
# O estimated_time_to_regain_access vem em minutos; o reset_time_duration,
# em segundos.
SEGUNDOS_POR_MINUTO: Final = 60


class TipoErro(StrEnum):
    LIMITE_TAXA = "limite de taxa"
    TRANSITORIO = "erro transitório"
    TEMPO_ESGOTADO = "tempo esgotado"
    EXCESSO_LINHAS = "excesso de linhas"
    AUTENTICACAO = "token inválido ou expirado"
    PERMISSAO = "permissão negada"
    DEFINITIVO = "erro definitivo"


TIPOS_RETENTAVEIS: Final = frozenset(
    {TipoErro.LIMITE_TAXA, TipoErro.TRANSITORIO, TipoErro.TEMPO_ESGOTADO}
)


@dataclass(frozen=True)
class ErroGraph:
    """Só os códigos do erro: a mensagem e o título da Meta podem trazer nome
    de campanha ou ID e nunca são guardados (RNF-17)."""

    codigo: int | None
    subcodigo: int | None
    transitorio: bool


@dataclass(frozen=True)
class UsoApi:
    percentual: float
    espera_recuperacao_segundos: float


def ler_erro_graph(corpo: object) -> ErroGraph | None:
    if not isinstance(corpo, dict) or not isinstance(corpo.get("error"), dict):
        return None
    erro = corpo["error"]
    return ErroGraph(
        codigo=ler_inteiro(erro.get("code")),
        subcodigo=ler_inteiro(erro.get("error_subcode")),
        transitorio=erro.get("is_transient") is True,
    )


def ler_inteiro(valor: object) -> int | None:
    # type() em vez de isinstance para recusar bool, que é subclasse de int.
    return valor if type(valor) is int else None


def classificar_erro(status_http: int, erro: ErroGraph | None) -> TipoErro:
    """Sem código da Graph, o status HTTP decide: 5xx é falha do servidor ou
    de um intermediário, que passa; o resto não muda ao repetir."""
    if erro is None or erro.codigo is None:
        if status_http >= STATUS_HTTP_ERRO_SERVIDOR:
            return TipoErro.TRANSITORIO
        return TipoErro.DEFINITIVO
    return classificar_codigo(erro)


def classificar_codigo(erro: ErroGraph) -> TipoErro:
    codigo = erro.codigo
    if codigo in CODIGOS_LIMITE_TAXA:
        return TipoErro.LIMITE_TAXA
    if codigo == CODIGO_EXCESSO_LINHAS and erro.subcodigo == SUBCODIGO_EXCESSO_LINHAS:
        return TipoErro.EXCESSO_LINHAS
    if codigo in CODIGOS_TRANSITORIOS or erro.transitorio:
        return TipoErro.TRANSITORIO
    if codigo in CODIGOS_AUTENTICACAO:
        return TipoErro.AUTENTICACAO
    if codigo in CODIGOS_PERMISSAO:
        return TipoErro.PERMISSAO
    return TipoErro.DEFINITIVO


def ler_uso(cabecalhos: Mapping[str, str]) -> UsoApi:
    """Junta os três cabeçalhos de uso no maior percentual informado e no
    maior tempo até a Meta devolver o acesso. Cabeçalho ausente ou malformado
    não informa nada, em vez de derrubar a extração."""
    percentuais = [0.0]
    esperas = [0.0]
    for item in ler_itens_uso_negocio(cabecalhos.get(CABECALHO_USO_NEGOCIO)):
        percentuais.extend(ler_numeros(item, CAMPOS_PERCENTUAL_NEGOCIO))
        minutos = ler_numeros(item, ("estimated_time_to_regain_access",))
        esperas.extend(m * SEGUNDOS_POR_MINUTO for m in minutos)
    insights = ler_objeto_json(cabecalhos.get(CABECALHO_USO_INSIGHTS))
    percentuais.extend(ler_numeros(insights, CAMPOS_PERCENTUAL_INSIGHTS))
    conta = ler_objeto_json(cabecalhos.get(CABECALHO_USO_CONTA))
    percentuais.extend(ler_numeros(conta, CAMPOS_PERCENTUAL_CONTA))
    esperas.extend(ler_numeros(conta, ("reset_time_duration",)))
    return UsoApi(percentual=max(percentuais), espera_recuperacao_segundos=max(esperas))


def ler_itens_uso_negocio(valor: str | None) -> Iterator[dict[str, object]]:
    """O cabeçalho traz, para cada BM, uma lista com um item por tipo de uso
    (ads_insights, ads_management)."""
    for itens in ler_objeto_json(valor).values():
        if isinstance(itens, list):
            yield from (item for item in itens if isinstance(item, dict))


def ler_objeto_json(valor: str | None) -> dict[str, object]:
    if not valor:
        return {}
    try:
        objeto = json.loads(valor)
    except json.JSONDecodeError:
        return {}
    return objeto if isinstance(objeto, dict) else {}


def ler_numeros(objeto: Mapping[str, object], campos: tuple[str, ...]) -> list[float]:
    return [
        float(valor)
        for campo in campos
        if type(valor := objeto.get(campo)) in (int, float)
    ]


def calcular_espera_backoff(tentativa: int, sorteio: float) -> float:
    """Espera depois da `tentativa`-ésima falha, com `sorteio` em [0, 1).

    O teto dobra a cada tentativa. O jitter sorteia entre a metade e o teto,
    para que chamadas que falharam juntas não voltem juntas e a espera nunca
    caia a zero.
    """
    teto = min(ESPERA_MAXIMA_SEGUNDOS, ESPERA_INICIAL_SEGUNDOS * 2 ** (tentativa - 1))
    return teto / 2 * (1 + sorteio)


def decidir_espera(
    tipo: TipoErro, tentativa: int, uso: UsoApi, sorteio: float
) -> float | None:
    """Quanto esperar antes de tentar de novo, ou None para desistir.

    No limite de taxa, espera pelo menos o que os cabeçalhos dizem faltar.
    Se isso passar da espera máxima, desiste já: a Meta orienta parar de
    chamar e voltar depois, e a falha fica com a empresa, sem atrasar as
    outras da execução.
    """
    if tipo not in TIPOS_RETENTAVEIS or tentativa >= MAXIMO_TENTATIVAS:
        return None
    espera = calcular_espera_backoff(tentativa, sorteio)
    if tipo is not TipoErro.LIMITE_TAXA:
        return espera
    if uso.espera_recuperacao_segundos > ESPERA_MAXIMA_SEGUNDOS:
        return None
    return max(espera, uso.espera_recuperacao_segundos)


def calcular_pausa_preventiva(uso: UsoApi) -> float:
    """Pausa antes da próxima chamada quando o uso chega a LIMITE_USO_PERCENTUAL.

    A pontuação da Meta decai ao longo de 300 s (R-15): a espera inicial
    devolve parte da cota. Quando os cabeçalhos informam o tempo de
    recuperação, ele prevalece, limitado à espera máxima.
    """
    if uso.percentual < LIMITE_USO_PERCENTUAL:
        return 0
    pausa = max(ESPERA_INICIAL_SEGUNDOS, uso.espera_recuperacao_segundos)
    return min(ESPERA_MAXIMA_SEGUNDOS, pausa)
