"""O cadastro de uma conta como a API o devolve, a partir das fixtures
cadastro_*.json, montadas de respostas reais e anonimizadas (CLAUDE.md §9), e
a simulação das consultas da extração com essas respostas.

A simulação só responde à consulta com os parâmetros que a extração deve
mandar: um filtro de status ou um campo diferente sai sem resposta, e o
teste falha.
"""

import json
from pathlib import Path

import responses
from responses import matchers

from etl.configuracao import URL_BASE_API_META, VERSAO_API_META
from etl.extracao import STATUS_EFETIVOS_CADASTRO, montar_campos
from etl.mapa_campos import ObjetoApi

PASTA_FIXTURES = Path(__file__).parent / "fixtures"
ID_META_CONTA = "995000000000001"
CONTA = f"act_{ID_META_CONTA}"
NOMES_FIXTURES = (
    "cadastro_conta",
    "cadastro_campanhas",
    "cadastro_conjuntos",
    "cadastro_anuncios_pagina_1",
    "cadastro_anuncios_pagina_2",
)
ARESTAS = (
    ("adsets", ObjetoApi.CONJUNTO, "cadastro_conjuntos"),
    ("campaigns", ObjetoApi.CAMPANHA, "cadastro_campanhas"),
)
type Fixtures = dict[str, dict]


def ler_fixtures() -> Fixtures:
    """Uma cópia nova a cada chamada, para o teste alterar à vontade."""
    return {
        nome: json.loads((PASTA_FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))
        for nome in NOMES_FIXTURES
    }


def montar_parametros(objeto: ObjetoApi) -> dict[str, str]:
    return {
        "fields": montar_campos(objeto),
        "effective_status": json.dumps(list(STATUS_EFETIVOS_CADASTRO)),
        "limit": "100",
    }


def simular_cadastro(api: responses.RequestsMock, fixtures: Fixtures) -> None:
    """Registra, na ordem da extração, a conta, as duas páginas de anúncios,
    os conjuntos e as campanhas."""
    simular(
        api,
        CONTA,
        fixtures["cadastro_conta"],
        {"fields": montar_campos(ObjetoApi.CONTA)},
    )
    parametros_anuncios = montar_parametros(ObjetoApi.ANUNCIO)
    pagina_1 = fixtures["cadastro_anuncios_pagina_1"]
    cursor = pagina_1["corpo"]["paging"]["cursors"]["after"]
    simular(api, f"{CONTA}/ads", pagina_1, parametros_anuncios)
    simular(
        api,
        f"{CONTA}/ads",
        fixtures["cadastro_anuncios_pagina_2"],
        {**parametros_anuncios, "after": cursor},
    )
    for aresta, objeto, nome in ARESTAS:
        simular(api, f"{CONTA}/{aresta}", fixtures[nome], montar_parametros(objeto))


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
