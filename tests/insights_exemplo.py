"""Os insights diários por anúncio de uma conta como a API os devolve, a partir
das fixtures insights_diarios_*.json e entidade_*_por_id.json, e a simulação
das consultas da extração com essas respostas.

As fixtures seguem a estrutura de respostas reais, com IDs, cursores e
valores inventados (CLAUDE.md §9). Os anúncios são os das fixtures de
cadastro, mais um que só existe pelo ID, com conjunto e campanha próprios: o
anúncio excluído que as arestas não devolvem (R-38). insights_diarios_conta
é a resposta da mesma conta e dos mesmos dias no nível de conta, para a
conferência do RF-02.

A simulação só responde à consulta com os parâmetros que a extração deve
mandar: um campo, um nível ou um intervalo diferente sai sem resposta, e o
teste falha.
"""

import json
from datetime import date
from pathlib import Path

import responses
from responses import matchers

from etl.configuracao import URL_BASE_API_META, VERSAO_API_META
from etl.extracao import montar_campos
from etl.mapa_campos import ObjetoApi
from tests.cadastro_exemplo import CONTA

PASTA_FIXTURES = Path(__file__).parent / "fixtures"
INICIO = date(2026, 10, 1)
FIM = date(2026, 10, 2)
ID_META_ANUNCIO_AUSENTE = "995000000000000024"
NOMES_PAGINAS = (
    "insights_diarios_anuncio_pagina_1",
    "insights_diarios_anuncio_pagina_2",
)
NOMES_ENTIDADES = (
    ("entidade_anuncio_por_id", ObjetoApi.ANUNCIO),
    ("entidade_conjunto_por_id", ObjetoApi.CONJUNTO),
    ("entidade_campanha_por_id", ObjetoApi.CAMPANHA),
)
type Fixtures = dict[str, dict]


def ler_fixtures() -> Fixtures:
    """Uma cópia nova a cada chamada, para o teste alterar à vontade."""
    nomes = (
        *NOMES_PAGINAS,
        "insights_diarios_conta",
        *(nome for nome, _ in NOMES_ENTIDADES),
    )
    return {
        nome: json.loads((PASTA_FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))
        for nome in nomes
    }


def montar_parametros_insights(inicio: date = INICIO, fim: date = FIM) -> dict:
    return {
        "level": "ad",
        "time_increment": "1",
        "time_range": json.dumps(
            {"since": inicio.isoformat(), "until": fim.isoformat()}
        ),
        "fields": "ad_id,spend,impressions,reach,actions,action_values",
        "limit": "500",
    }


def listar_linhas(fixtures: Fixtures) -> list[dict]:
    """As linhas de insights das duas páginas, na ordem."""
    return [
        linha for nome in NOMES_PAGINAS for linha in fixtures[nome]["corpo"]["data"]
    ]


def simular_insights(
    api: responses.RequestsMock, fixtures: Fixtures, *, com_entidades: bool = True
) -> None:
    """Registra, na ordem da extração, as duas páginas de insights da conta e,
    com com_entidades, a leitura pelo ID do anúncio ausente do banco, do
    conjunto e da campanha dele."""
    parametros = montar_parametros_insights()
    pagina_1, pagina_2 = (fixtures[nome] for nome in NOMES_PAGINAS)
    cursor = pagina_1["corpo"]["paging"]["cursors"]["after"]
    simular(api, f"{CONTA}/insights", pagina_1, parametros)
    simular(api, f"{CONTA}/insights", pagina_2, {**parametros, "after": cursor})
    if com_entidades:
        simular_entidades(api, fixtures)


def simular_entidades(api: responses.RequestsMock, fixtures: Fixtures) -> None:
    for nome, objeto in NOMES_ENTIDADES:
        fixture = fixtures[nome]
        simular(api, fixture["corpo"]["id"], fixture, {"fields": montar_campos(objeto)})


def simular(
    api: responses.RequestsMock, caminho: str, fixture: dict, parametros: dict
) -> None:
    api.add(
        responses.GET,
        f"{URL_BASE_API_META}/{VERSAO_API_META}/{caminho}",
        json=fixture["corpo"],
        status=fixture["status"],
        headers=fixture["cabecalhos"],
        match=[matchers.query_param_matcher(parametros)],
    )
