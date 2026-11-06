"""A carga histórica de uma conta como a API a devolve, fatia a fatia, a partir
das fixtures dos insights diários, das quebras e do alcance, e a simulação das
consultas de cada fatia com essas respostas.

A execução de referência é a de 06/11/2026, às 03:43 de Brasília, no fuso da
conta das fixtures de cadastro. Os insights aceitam o since a partir de hoje
menos 37 meses, 06/10/2023, e a carga começa um dia depois, no limite de
amanhã, porque o hoje da Meta pode estar à frente (R-19). Vão até ontem, 05/11/2026: 38 fatias, de
outubro de 2023 a novembro de 2026, a primeira e a última cortadas. Só duas têm
entrega: março de 2026, com as fixtures revisao_*_antes, e outubro de 2026,
com as dos insights diários e das quebras, cujo anúncio excluído só existe
pelo ID. As demais respondem vazias.

Os períodos do alcance de cada fatia são calculados aqui de forma
independente da ETL: as semanas ISO que começam na fatia, o mês quando a
fatia começa no dia 1 e o ano quando ela começa em 1º de janeiro, todos
cortados em ontem (ADR-0006; ADR-0009 §5). A simulação só responde à
consulta com os parâmetros que a carga deve mandar, na ordem: uma fatia
fora da ordem, repetida ou com outro intervalo sai sem resposta, e o teste
falha.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

import responses

from tests.alcance_exemplo import NIVEIS, montar_parametros_alcance, nomear_fixture
from tests.cadastro_exemplo import CONTA, simular
from tests.insights_exemplo import ler_fixtures as ler_fixtures_insights
from tests.insights_exemplo import montar_parametros_insights, simular_entidades
from tests.quebras_exemplo import (
    QUEBRAS,
    montar_parametros_quebra,
    simular_campanha_ausente,
)
from tests.quebras_exemplo import ler_fixtures as ler_fixtures_quebras

PASTA_FIXTURES = Path(__file__).parent / "fixtures"
EXECUCAO: Final = datetime(2026, 11, 6, 6, 43, tzinfo=UTC)
HOJE: Final = date(2026, 11, 6)
LIMITE: Final = date(2023, 10, 7)
ONTEM: Final = date(2026, 11, 5)
MARCO: Final = date(2026, 3, 1)
OUTUBRO: Final = date(2026, 10, 1)
NOVEMBRO: Final = date(2026, 11, 1)
RESPOSTA_VAZIA: Final = {"status": 200, "cabecalhos": {}, "corpo": {"data": []}}
DIAS_SEMANA: Final = 7


@dataclass(frozen=True)
class RespostasFatia:
    """As respostas de uma fatia; o que falta vem vazio. alcance vai do nível
    e do tipo de período, como nos nomes das fixtures, à resposta.
    entidades_por_id registra, depois das consultas, as leituras pelo ID do
    anúncio excluído e da campanha dele."""

    insights: Sequence[dict] = ()
    quebras: Mapping[str, dict] = field(default_factory=dict)
    alcance: Mapping[str, dict] = field(default_factory=dict)
    entidades_por_id: bool = False


def ler_fixture(nome: str) -> dict:
    """Uma cópia nova a cada chamada, para o teste alterar à vontade."""
    return json.loads((PASTA_FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))


def listar_meses(limite: date = LIMITE, ontem: date = ONTEM) -> list[date]:
    """O dia 1 de cada mês do limite a ontem, na ordem."""
    meses = []
    mes = limite.replace(day=1)
    while mes <= ontem:
        meses.append(mes)
        mes = (mes + timedelta(days=32)).replace(day=1)
    return meses


def calcular_intervalo(
    mes: date, limite: date = LIMITE, ontem: date = ONTEM
) -> tuple[date, date]:
    fim_mes = (mes + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return max(mes, limite), min(fim_mes, ontem)


def calcular_periodos(
    inicio: date, fim: date, ontem: date = ONTEM
) -> list[tuple[str, date, date]]:
    """Os períodos do alcance da fatia, na ordem da extração."""
    segundas = [
        inicio + timedelta(days=dias)
        for dias in range((fim - inicio).days + 1)
        if (inicio + timedelta(days=dias)).weekday() == 0
    ]
    periodos = []
    if segundas:
        ultima = segundas[-1] + timedelta(days=DIAS_SEMANA - 1)
        periodos.append(("semana", segundas[0], min(ultima, ontem)))
    if inicio.day == 1:
        periodos.append(("mes", inicio, fim))
    if (inicio.month, inicio.day) == (1, 1):
        periodos.append(("ano", inicio, min(date(inicio.year, 12, 31), ontem)))
    return periodos


def montar_respostas_marco() -> RespostasFatia:
    """A fatia de março de 2026: a página de insights, as três quebras e o
    alcance de março de cada campanha (RF-04)."""
    return RespostasFatia(
        insights=[ler_fixture("revisao_insights_antes")],
        quebras={
            tipo: ler_fixture(f"revisao_quebra_{tipo}_antes") for tipo, _, _ in QUEBRAS
        },
        alcance={
            nomear_fixture("campanha", "mes"): ler_fixture("alcance_campanha_marco")
        },
    )


def montar_respostas_outubro() -> RespostasFatia:
    """A fatia de outubro de 2026: as duas páginas de insights, as três
    quebras e, pelo ID, o anúncio excluído e a campanha dele."""
    insights = ler_fixtures_insights()
    quebras = ler_fixtures_quebras()
    return RespostasFatia(
        insights=[
            insights["insights_diarios_anuncio_pagina_1"],
            insights["insights_diarios_anuncio_pagina_2"],
        ],
        quebras={tipo: quebras[nome] for tipo, _, nome in QUEBRAS},
        entidades_por_id=True,
    )


def montar_respostas() -> dict[date, RespostasFatia]:
    """As respostas das fatias com entrega; as outras vêm vazias."""
    return {MARCO: montar_respostas_marco(), OUTUBRO: montar_respostas_outubro()}


def simular_insights_fatia(
    api: responses.RequestsMock,
    conta: str,
    inicio: date,
    fim: date,
    paginas: Sequence[dict],
) -> None:
    """As páginas na ordem, a seguinte pedida pelo cursor da anterior."""
    parametros = montar_parametros_insights(inicio, fim)
    cursor = None
    for pagina in paginas or [RESPOSTA_VAZIA]:
        simular(
            api,
            f"{conta}/insights",
            pagina,
            {**parametros, "after": cursor} if cursor else parametros,
        )
        cursor = pagina["corpo"].get("paging", {}).get("cursors", {}).get("after")


def simular_fatia(
    api: responses.RequestsMock,
    mes: date,
    respostas: RespostasFatia,
    *,
    conta: str = CONTA,
    hoje: date = HOJE,
) -> None:
    """Registra, na ordem da extração, os insights, as três quebras e o
    alcance de cada período nos três níveis e, por último, as leituras pelo
    ID."""
    limite, ontem = calcular_limite(hoje), hoje - timedelta(days=1)
    inicio, fim = calcular_intervalo(mes, limite, ontem)
    simular_insights_fatia(api, conta, inicio, fim, respostas.insights)
    for tipo, breakdowns, _ in QUEBRAS:
        simular(
            api,
            f"{conta}/insights",
            respostas.quebras.get(tipo, RESPOSTA_VAZIA),
            montar_parametros_quebra(breakdowns, inicio, fim),
        )
    for tipo, inicio_periodo, fim_periodo in calcular_periodos(inicio, fim, ontem):
        for nivel_api, nivel, _ in NIVEIS:
            simular(
                api,
                f"{conta}/insights",
                respostas.alcance.get(nomear_fixture(nivel, tipo), RESPOSTA_VAZIA),
                montar_parametros_alcance(nivel_api, tipo, inicio_periodo, fim_periodo),
            )
    if respostas.entidades_por_id:
        simular_entidades(api, ler_fixtures_insights())
        simular_campanha_ausente(api)


def calcular_limite(hoje: date) -> date:
    """O mais tardio entre hoje e amanhã menos 37 meses, com o dia contado a
    partir do dia 1 do mês do limite (R-19)."""

    def recuar(dia: date) -> date:
        meses = dia.year * 12 + dia.month - 1 - 37
        return date(meses // 12, meses % 12 + 1, 1) + timedelta(days=dia.day - 1)

    return max(recuar(hoje), recuar(hoje + timedelta(days=1)))


def simular_historico(
    api: responses.RequestsMock,
    meses: Sequence[date],
    respostas: Mapping[date, RespostasFatia],
    *,
    conta: str = CONTA,
    hoje: date = HOJE,
) -> None:
    """Registra as fatias dos meses dados, na ordem."""
    for mes in meses:
        simular_fatia(
            api, mes, respostas.get(mes, RespostasFatia()), conta=conta, hoje=hoje
        )
