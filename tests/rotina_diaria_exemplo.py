"""Duas revisões diárias seguidas de uma conta, a partir das fixtures
revisao_*.json, e a simulação das consultas da revisão com essas respostas.

As fixtures seguem a estrutura das respostas de insights, com IDs e valores
inventados (CLAUDE.md §9). São duas extrações dos mesmos dias, antes e depois
de uma revisão da Meta (R-17): a primeira na execução de 07/04/2026, com a
janela de 10/03 a 06/04, e a segunda na de 08/04, com a janela de 11/03 a
07/04. Em DIA_REVISADO e em PRIMEIRO_DIA_SEGUNDA_JANELA, as compras e os
cadastros mudam; em DIA_REVISADO, um tipo de ação some. DIA_SEM_REVISAO vem
igual nas duas, e DIA_FORA_DA_SEGUNDA_JANELA só na primeira. Os anúncios e as
campanhas são os das fixtures de cadastro, que a revisão não lê: a carga
inicial já os carregou (ADR-0017).

O alcance é o das fixtures de alcance, cuja janela é a da primeira execução.
Os períodos lidos são os que contêm os dias do início do alcance até ontem
(ADR-0017): na conta ainda sem alcance extraído, a janela inteira; no dia
normal, só ontem. De cada fixture, ficam os blocos que começam no período
pedido, cortados no until, como a API os devolve (R-20).

A simulação só responde à consulta com os parâmetros que a revisão deve
mandar, na ordem da extração: uma janela ou um período diferente sai sem
resposta, e o teste falha.
"""

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

import responses

from tests.alcance_exemplo import NIVEIS, montar_parametros_alcance, nomear_fixture
from tests.cadastro_exemplo import CONTA, simular
from tests.insights_exemplo import montar_parametros_insights
from tests.quebras_exemplo import QUEBRAS, montar_parametros_quebra

PASTA_FIXTURES = Path(__file__).parent / "fixtures"
# 06:43 UTC em cada dia de execução: 03:43 em Brasília e 23:43 da véspera em
# Los Angeles.
PRIMEIRA_EXECUCAO: Final = datetime(2026, 4, 7, 6, 43, tzinfo=UTC)
SEGUNDA_EXECUCAO: Final = datetime(2026, 4, 8, 6, 43, tzinfo=UTC)
PRIMEIRO_HOJE: Final = date(2026, 4, 7)
SEGUNDO_HOJE: Final = date(2026, 4, 8)
DIA_FORA_DA_SEGUNDA_JANELA: Final = date(2026, 3, 10)
PRIMEIRO_DIA_SEGUNDA_JANELA: Final = date(2026, 3, 11)
DIA_REVISADO: Final = date(2026, 3, 20)
DIA_SEM_REVISAO: Final = date(2026, 3, 21)
ANTES: Final = "antes"
DEPOIS: Final = "depois"
RESPOSTA_VAZIA: Final = {"status": 200, "cabecalhos": {}, "corpo": {"data": []}}
type Fixtures = Mapping[str, dict]


def ler_fixture(nome: str) -> dict:
    """Uma cópia nova a cada chamada, para o teste alterar à vontade."""
    return json.loads((PASTA_FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))


def ler_insights(momento: str) -> dict:
    return ler_fixture(f"revisao_insights_{momento}")


def ler_quebras(momento: str) -> dict[str, dict]:
    return {
        tipo: ler_fixture(f"revisao_quebra_{tipo}_{momento}") for tipo, _, _ in QUEBRAS
    }


def listar_linhas(fixture: dict, dia: date | None = None) -> list[dict]:
    """As linhas da resposta, só as do dia, quando dado."""
    return [
        linha
        for linha in fixture["corpo"]["data"]
        if dia is None or linha["date_start"] == dia.isoformat()
    ]


def calcular_janela(hoje: date) -> tuple[date, date]:
    return hoje - timedelta(days=28), hoje - timedelta(days=1)


def calcular_periodos(desde: date, fim: date) -> list[tuple[str, date, date]]:
    """Os períodos que contêm os dias de desde a fim, na ordem da extração:
    a semana e o mês de desde e cada ano até fim, todos cortados em fim ou no
    fim do ano (ADR-0006; ADR-0017)."""
    return [
        ("semana", desde - timedelta(days=desde.weekday()), fim),
        ("mes", desde.replace(day=1), fim),
        *(
            ("ano", date(ano, 1, 1), min(fim, date(ano, 12, 31)))
            for ano in range(desde.year, fim.year + 1)
        ),
    ]


def montar_alcance_periodos(
    alcance: Fixtures, desde: date, fim: date
) -> dict[tuple[str, str, date], dict]:
    """A resposta de cada nível e período, pelo nome da fixture, o tipo e o
    since: os blocos da fixture que começam do since ao until, cortados no
    until. Sem fixture, a resposta vem vazia."""
    respostas = {}
    for tipo, inicio, ate in calcular_periodos(desde, fim):
        for _, nivel, _ in NIVEIS:
            nome = nomear_fixture(nivel, tipo)
            fixture = alcance.get(nome, RESPOSTA_VAZIA)
            linhas = [
                {**linha, "date_stop": min(linha["date_stop"], ate.isoformat())}
                for linha in fixture["corpo"]["data"]
                if inicio.isoformat() <= linha["date_start"] <= ate.isoformat()
            ]
            respostas[(nome, tipo, inicio)] = {**fixture, "corpo": {"data": linhas}}
    return respostas


def simular_janela(
    api: responses.RequestsMock,
    conta: str,
    hoje: date,
    insights: dict,
    quebras: Fixtures,
    alcance: Fixtures,
    desde: date | None = None,
) -> None:
    """Registra, na ordem da extração, os insights e as três quebras da
    janela e o alcance dos períodos que contêm os dias de desde a ontem, nos
    três níveis. Sem desde, o início da janela, como na conta ainda sem
    alcance extraído. A quebra ou o alcance sem fixture vem vazio."""
    inicio, fim = calcular_janela(hoje)
    simular(api, f"{conta}/insights", insights, montar_parametros_insights(inicio, fim))
    for tipo, breakdowns, _ in QUEBRAS:
        simular(
            api,
            f"{conta}/insights",
            quebras.get(tipo, RESPOSTA_VAZIA),
            montar_parametros_quebra(breakdowns, inicio, fim),
        )
    desde = inicio if desde is None else desde
    respostas = montar_alcance_periodos(alcance, desde, fim)
    for tipo, inicio_periodo, fim_periodo in calcular_periodos(desde, fim):
        for nivel_api, nivel, _ in NIVEIS:
            simular(
                api,
                f"{conta}/insights",
                respostas[(nomear_fixture(nivel, tipo), tipo, inicio_periodo)],
                montar_parametros_alcance(nivel_api, tipo, inicio_periodo, fim_periodo),
            )


def simular_rotina(
    api: responses.RequestsMock,
    hoje: date,
    insights: dict,
    quebras: Fixtures,
    alcance: Fixtures,
    desde: date | None = None,
) -> None:
    """Registra as consultas da revisão para a conta das fixtures de
    cadastro, sem o cadastro."""
    simular_janela(api, CONTA, hoje, insights, quebras, alcance, desde)


def simular_conta_vazia(
    api: responses.RequestsMock,
    id_meta_conta: str,
    hoje: date,
    desde: date | None = None,
) -> None:
    """Registra as consultas da revisão para uma conta sem entrega."""
    simular_janela(api, f"act_{id_meta_conta}", hoje, RESPOSTA_VAZIA, {}, {}, desde)
