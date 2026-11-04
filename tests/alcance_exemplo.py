"""O alcance por período de uma conta como a API o devolve, a partir das
fixtures alcance_*.json, e a simulação das consultas da extração com essas
respostas.

As fixtures seguem a estrutura das respostas de insights, com IDs e valores
inventados (CLAUDE.md §9). A janela vai de uma terça-feira a uma
segunda-feira, como a execução diária de 07/04/2026: a semana começa na
segunda-feira anterior ao primeiro dia, o mês no dia 1 e o ano em 1º de
janeiro, todos cortados no último dia (ADR-0006). Os anúncios e as campanhas
são os das fixtures de cadastro, mais o anúncio excluído que só existe pelo
ID, com alcance só no ano. alcance_campanha_marco é a resposta do intervalo
de 01/03 a 31/03/2026 sem quebra diária, para o critério do RF-04.

A simulação só responde à consulta com os parâmetros que a extração deve
mandar: um nível, um incremento ou um intervalo diferente sai sem resposta,
e o teste falha.
"""

import json
from datetime import date
from pathlib import Path

import responses

from etl.extracao import STATUS_EFETIVOS_CADASTRO
from tests.cadastro_exemplo import CONTA
from tests.insights_exemplo import ler_fixtures as ler_fixtures_insights
from tests.insights_exemplo import simular, simular_entidades

PASTA_FIXTURES = Path(__file__).parent / "fixtures"
INICIO = date(2026, 3, 10)
FIM = date(2026, 4, 6)
# Os períodos da janela, na ordem da extração: tipo, since e until.
PERIODOS = (
    ("semana", date(2026, 3, 9), FIM),
    ("mes", date(2026, 3, 1), FIM),
    ("ano", date(2026, 1, 1), FIM),
)
INCREMENTOS = {"semana": "7", "mes": "monthly", "ano": "all_days"}
# Nível da API, nome do nível nas fixtures e campos pedidos, na ordem da
# extração.
NIVEIS = (
    ("account", "conta", "reach,impressions"),
    ("campaign", "campanha", "campaign_id,reach,impressions"),
    ("ad", "anuncio", "ad_id,reach,impressions"),
)
FILTRO_STATUS = json.dumps(
    [
        {
            "field": "ad.effective_status",
            "operator": "IN",
            "value": [*STATUS_EFETIVOS_CADASTRO, "DELETED"],
        }
    ]
)
type Fixtures = dict[str, dict]


def nomear_fixture(nivel: str, tipo: str) -> str:
    return f"alcance_{nivel}_{tipo}"


def ler_fixtures() -> Fixtures:
    """Uma cópia nova a cada chamada, para o teste alterar à vontade."""
    nomes = [
        nomear_fixture(nivel, tipo) for _, nivel, _ in NIVEIS for tipo, *_ in PERIODOS
    ]
    return {
        nome: json.loads((PASTA_FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))
        for nome in (*nomes, "alcance_campanha_marco")
    }


def montar_parametros_alcance(
    nivel_api: str, tipo: str, inicio: date, fim: date
) -> dict[str, str]:
    campos = next(c for n, _, c in NIVEIS if n == nivel_api)
    parametros = {
        "level": nivel_api,
        "time_increment": INCREMENTOS[tipo],
        "time_range": json.dumps(
            {"since": inicio.isoformat(), "until": fim.isoformat()}
        ),
        "fields": campos,
        "limit": "500",
    }
    if nivel_api != "account":
        parametros["filtering"] = FILTRO_STATUS
    return parametros


def listar_linhas(fixtures: Fixtures, nivel: str, tipo: str) -> list[dict]:
    return fixtures[nomear_fixture(nivel, tipo)]["corpo"]["data"]


def simular_alcance(
    api: responses.RequestsMock, fixtures: Fixtures, *, com_entidades: bool = True
) -> None:
    """Registra, na ordem da extração, as consultas de cada período nos três
    níveis e, com com_entidades, a leitura pelo ID do anúncio excluído, do
    conjunto e da campanha dele."""
    for tipo, inicio, fim in PERIODOS:
        for nivel_api, nivel, _ in NIVEIS:
            simular(
                api,
                f"{CONTA}/insights",
                fixtures[nomear_fixture(nivel, tipo)],
                montar_parametros_alcance(nivel_api, tipo, inicio, fim),
            )
    if com_entidades:
        simular_entidades(api, ler_fixtures_insights())
