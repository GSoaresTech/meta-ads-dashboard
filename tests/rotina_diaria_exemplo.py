"""Duas execuções diárias seguidas de uma conta, a partir das fixtures
revisao_*.json, e a simulação das consultas da rotina com essas respostas.

As fixtures seguem a estrutura das respostas de insights, com IDs e valores
inventados (CLAUDE.md §9). São duas extrações dos mesmos dias, antes e depois
de uma revisão da Meta (R-17): a primeira na execução de 07/04/2026, com a
janela de 10/03 a 06/04, e a segunda na de 08/04, com a janela de 11/03 a
07/04. Em DIA_REVISADO e em PRIMEIRO_DIA_SEGUNDA_JANELA, as compras e os
cadastros mudam; em DIA_REVISADO, um tipo de ação some. DIA_SEM_REVISAO vem
igual nas duas, e DIA_FORA_DA_SEGUNDA_JANELA só na primeira. Os anúncios e as
campanhas são os das fixtures de cadastro, e o alcance é o das fixtures de
alcance, cuja janela é a da primeira execução.

A simulação só responde à consulta com os parâmetros que a rotina deve mandar,
na ordem da extração: uma janela diferente sai sem resposta, e o teste falha.
"""

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

import responses

from etl.extracao import montar_campos
from etl.mapa_campos import ObjetoApi
from tests import cadastro_exemplo
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


def calcular_periodos(inicio: date, fim: date) -> list[tuple[str, date, date]]:
    """Os períodos da janela, na ordem da extração: a semana e o mês do
    primeiro dia e cada ano que ela toca, todos cortados no último dia da
    janela ou do ano (ADR-0006)."""
    return [
        ("semana", inicio - timedelta(days=inicio.weekday()), fim),
        ("mes", inicio.replace(day=1), fim),
        *(
            ("ano", date(ano, 1, 1), min(fim, date(ano, 12, 31)))
            for ano in range(inicio.year, fim.year + 1)
        ),
    ]


def simular_janela(
    api: responses.RequestsMock,
    conta: str,
    hoje: date,
    insights: dict,
    quebras: Fixtures,
    alcance: Fixtures,
) -> None:
    """Registra, na ordem da extração, os insights, as três quebras e o
    alcance dos períodos da janela, nos três níveis. A quebra ou o alcance
    sem fixture vem vazio."""
    inicio, fim = calcular_janela(hoje)
    simular(api, f"{conta}/insights", insights, montar_parametros_insights(inicio, fim))
    for tipo, breakdowns, _ in QUEBRAS:
        simular(
            api,
            f"{conta}/insights",
            quebras.get(tipo, RESPOSTA_VAZIA),
            montar_parametros_quebra(breakdowns, inicio, fim),
        )
    for tipo, inicio_periodo, fim_periodo in calcular_periodos(inicio, fim):
        for nivel_api, nivel, _ in NIVEIS:
            simular(
                api,
                f"{conta}/insights",
                alcance.get(nomear_fixture(nivel, tipo), RESPOSTA_VAZIA),
                montar_parametros_alcance(nivel_api, tipo, inicio_periodo, fim_periodo),
            )


def simular_rotina(
    api: responses.RequestsMock,
    hoje: date,
    insights: dict,
    quebras: Fixtures,
    alcance: Fixtures,
    *,
    cadastro: Fixtures | None = None,
) -> None:
    """Registra as consultas da rotina para a conta das fixtures de cadastro:
    primeiro o cadastro, que dá o dia no fuso da conta; depois, a janela."""
    cadastro_exemplo.simular_cadastro(
        api, cadastro_exemplo.ler_fixtures() if cadastro is None else cadastro
    )
    simular_janela(api, CONTA, hoje, insights, quebras, alcance)


def simular_conta_vazia(
    api: responses.RequestsMock, id_meta_conta: str, fuso: str, hoje: date
) -> None:
    """Registra as consultas da rotina para uma conta sem entidades nem
    entrega, no fuso dado."""
    conta = f"act_{id_meta_conta}"
    fixture_conta = cadastro_exemplo.ler_fixtures()["cadastro_conta"]
    fixture_conta["corpo"] |= {"id": conta, "timezone_name": fuso}
    simular(api, conta, fixture_conta, {"fields": montar_campos(ObjetoApi.CONTA)})
    for aresta, objeto in (
        ("ads", ObjetoApi.ANUNCIO),
        ("adsets", ObjetoApi.CONJUNTO),
        ("campaigns", ObjetoApi.CAMPANHA),
    ):
        simular(
            api,
            f"{conta}/{aresta}",
            RESPOSTA_VAZIA,
            cadastro_exemplo.montar_parametros(objeto),
        )
    simular_janela(api, conta, hoje, RESPOSTA_VAZIA, {}, {})
