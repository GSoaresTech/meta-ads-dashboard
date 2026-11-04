import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from etl.mapa_campos import (
    CAMPOS_COM_NOME_IGUAL_EM_PORTUGUES,
    MAPA_CAMPOS,
    ErroCampoNaoMapeado,
    ObjetoApi,
    TipoCampo,
    traduzir_registro,
)
from etl.padronizacao import ErroPadronizacao

PASTA_FIXTURES = Path(__file__).parent / "fixtures"
PADRAO_NOME_PORTUGUES = re.compile(r"[a-z][a-z0-9]*(_[a-z0-9]+)*")
TIPOS_COMPOSTOS = {TipoCampo.LISTA, TipoCampo.OBJETO}


def ler_linhas_insights_fixture() -> list[dict[str, object]]:
    conteudo = json.loads(
        (PASTA_FIXTURES / "insights_anuncio_dia_pagina_1.json").read_text()
    )
    return conteudo["corpo"]["data"]


def test_traduz_linha_de_insights_da_fixture() -> None:
    linha = ler_linhas_insights_fixture()[0]

    traduzida = traduzir_registro(ObjetoApi.INSIGHTS, linha)

    assert traduzida["id_meta_anuncio"] == "990000000000301"
    assert traduzida["investimento"] == Decimal("12.34")
    assert traduzida["impressoes"] == 1520
    assert traduzida["inicio_periodo"] == date(2026, 10, 1)
    assert traduzida["fim_periodo"] == date(2026, 10, 1)


def test_campo_ausente_vira_none_nunca_zero() -> None:
    # A fixture não traz reach nem actions: os dois ficam None.
    traduzida = traduzir_registro(ObjetoApi.INSIGHTS, ler_linhas_insights_fixture()[0])

    assert traduzida["alcance"] is None
    assert traduzida["acoes"] is None


def test_devolve_todos_os_nomes_do_objeto_e_nenhum_da_api() -> None:
    traduzida = traduzir_registro(ObjetoApi.INSIGHTS, ler_linhas_insights_fixture()[0])

    nomes_esperados = {campo.nome for campo in MAPA_CAMPOS[ObjetoApi.INSIGHTS].values()}
    assert set(traduzida) == nomes_esperados
    assert not set(traduzida) & set(MAPA_CAMPOS[ObjetoApi.INSIGHTS])


def test_texto_e_aparado_e_vazio_vira_none() -> None:
    traduzida = traduzir_registro(
        ObjetoApi.CAMPANHA,
        {
            "id": "990000000000101",
            "name": "  Nome ",
            "objective": "",
            "status": "ACTIVE",
        },
    )

    assert traduzida == {
        "id_meta": "990000000000101",
        "nome": "Nome",
        "objetivo": None,
        "status": "ACTIVE",
    }


def test_traduz_acoes_e_valores_em_listas_tipadas() -> None:
    linha = {
        "ad_id": "990000000000301",
        "date_start": "2026-10-01",
        "date_stop": "2026-10-01",
        "actions": [
            {"action_type": "link_click", "value": "41"},
            {"action_type": "omni_purchase", "value": "3"},
        ],
        "action_values": [{"action_type": "omni_purchase", "value": "459.70"}],
    }

    traduzida = traduzir_registro(ObjetoApi.INSIGHTS, linha)

    assert traduzida["acoes"] == [
        {"tipo_acao": "link_click", "quantidade": 41},
        {"tipo_acao": "omni_purchase", "quantidade": 3},
    ]
    assert traduzida["valores_acoes"] == [
        {"tipo_acao": "omni_purchase", "valor": Decimal("459.70")}
    ]


def test_traduz_quebras_de_insights() -> None:
    linha = {
        "campaign_id": "990000000000101",
        "date_start": "2026-10-01",
        "date_stop": "2026-10-01",
        "age": "25-34",
        "gender": "female",
        "publisher_platform": "instagram",
        "platform_position": "feed",
        "region": " Região Exemplo ",
    }

    traduzida = traduzir_registro(ObjetoApi.INSIGHTS, linha)

    assert traduzida["id_meta_campanha"] == "990000000000101"
    assert traduzida["idade"] == "25-34"
    assert traduzida["genero"] == "female"
    assert traduzida["plataforma"] == "instagram"
    assert traduzida["posicionamento"] == "feed"
    assert traduzida["regiao"] == "Região Exemplo"


def test_conta_guarda_o_id_sem_prefixo() -> None:
    traduzida = traduzir_registro(
        ObjetoApi.CONTA,
        {
            "id": "act_990000000000001",
            "name": "Conta Exemplo",
            "timezone_name": "America/Sao_Paulo",
            "currency": "BRL",
        },
    )

    assert traduzida == {
        "id_meta": "990000000000001",
        "nome": "Conta Exemplo",
        "fuso_horario": "America/Sao_Paulo",
        "moeda": "BRL",
    }


def test_traduz_janelas_de_atribuicao_do_conjunto() -> None:
    conjunto = {
        "id": "990000000000201",
        "campaign_id": "990000000000101",
        "status": "PAUSED",
        "attribution_spec": [
            {"event_type": "CLICK_THROUGH", "window_days": 7},
            {"event_type": "VIEW_THROUGH", "window_days": 1},
        ],
    }

    traduzida = traduzir_registro(ObjetoApi.CONJUNTO, conjunto)

    assert traduzida["id_meta_campanha"] == "990000000000101"
    assert traduzida["meta_otimizacao"] is None
    assert traduzida["janelas_atribuicao"] == [
        {"tipo_evento": "CLICK_THROUGH", "janela_dias": 7},
        {"tipo_evento": "VIEW_THROUGH", "janela_dias": 1},
    ]


def test_traduz_criativo_aninhado_no_anuncio() -> None:
    anuncio = {
        "id": "990000000000301",
        "name": "Anúncio Exemplo",
        "status": "ACTIVE",
        "adset_id": "990000000000201",
        "creative": {"id": "990000000000401"},
    }

    traduzida = traduzir_registro(ObjetoApi.ANUNCIO, anuncio)

    criativo = traduzida["criativo"]
    assert isinstance(criativo, dict)
    assert criativo["id_meta"] == "990000000000401"
    assert criativo["titulo"] is None
    assert traduzida["id_meta_conjunto"] == "990000000000201"


@pytest.mark.parametrize(
    ("objeto", "registro"),
    [
        (ObjetoApi.INSIGHTS, {"date_start": "2026-10-01", "clicks": "9"}),
        (
            ObjetoApi.INSIGHTS,
            {"actions": [{"action_type": "link_click", "value": "1", "1d_view": "1"}]},
        ),
        (ObjetoApi.ANUNCIO, {"id": "990000000000301", "creative": {"name": "x"}}),
        (
            ObjetoApi.CONJUNTO,
            {"attribution_spec": [{"event_type": "CLICK_THROUGH", "weight": 100}]},
        ),
    ],
)
def test_recusa_campo_sem_entrada_no_mapa(
    objeto: ObjetoApi, registro: dict[str, object]
) -> None:
    # Todo campo que a transformação lê passa pelo mapa (RF-11): um campo
    # fora dele falha, em vez de ser lido com o nome da API ou descartado.
    with pytest.raises(ErroCampoNaoMapeado):
        traduzir_registro(objeto, registro)


def test_erro_de_campo_nao_mapeado_nao_expoe_valores() -> None:
    with pytest.raises(ErroCampoNaoMapeado) as erro:
        traduzir_registro(ObjetoApi.INSIGHTS, {"clicks": "98765"})

    assert "clicks" in str(erro.value)
    assert "98765" not in str(erro.value)


@pytest.mark.parametrize(
    ("objeto", "registro"),
    [
        (ObjetoApi.INSIGHTS, ["não é objeto"]),
        (ObjetoApi.INSIGHTS, {"actions": {"action_type": "link_click"}}),
        (ObjetoApi.INSIGHTS, {"actions": ["não é objeto"]}),
        (ObjetoApi.ANUNCIO, {"creative": "990000000000401"}),
    ],
)
def test_recusa_estrutura_fora_do_tipo(objeto: ObjetoApi, registro: object) -> None:
    with pytest.raises(ErroPadronizacao):
        traduzir_registro(objeto, registro)


def test_cada_objeto_da_api_tem_mapa() -> None:
    assert set(MAPA_CAMPOS) == set(ObjetoApi)


@pytest.mark.parametrize("objeto", list(ObjetoApi))
def test_nomes_em_portugues_sao_unicos_e_em_snake_case(objeto: ObjetoApi) -> None:
    nomes = [campo.nome for campo in MAPA_CAMPOS[objeto].values()]

    assert len(nomes) == len(set(nomes))
    assert all(PADRAO_NOME_PORTUGUES.fullmatch(nome) for nome in nomes)


def test_nenhum_nome_traduzido_repete_o_da_api_salvo_as_excecoes() -> None:
    repetidos = {
        nome_api
        for campos in MAPA_CAMPOS.values()
        for nome_api, campo in campos.items()
        if campo.nome == nome_api
    }

    assert repetidos == CAMPOS_COM_NOME_IGUAL_EM_PORTUGUES


def test_so_campos_compostos_apontam_para_outro_objeto() -> None:
    for campos in MAPA_CAMPOS.values():
        for campo in campos.values():
            assert (campo.tipo in TIPOS_COMPOSTOS) == (campo.itens is not None)
