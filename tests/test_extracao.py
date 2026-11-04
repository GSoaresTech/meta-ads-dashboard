import json
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
import responses
from responses.registries import OrderedRegistry

from etl.cliente_api_meta import ClienteApiMeta, Endpoint, ErroRespostaInvalida
from etl.extracao import (
    STATUS_EFETIVOS_CADASTRO,
    calcular_data_referencia,
    extrair_cadastro_conta,
    montar_campos,
)
from etl.mapa_campos import MAPA_CAMPOS, ObjetoApi, TipoCampo
from tests.cadastro_exemplo import ID_META_CONTA, ler_fixtures, simular_cadastro

TOKEN = "EAAFicticio0000000000000000000000000000000000ZZ"
# 02:30 em UTC ainda é o dia anterior em São Paulo, o fuso da fixture.
INSTANTE = datetime(2026, 11, 4, 2, 30, tzinfo=UTC)


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(registry=OrderedRegistry) as mock:
        yield mock


@pytest.fixture
def cliente() -> ClienteApiMeta:
    return ClienteApiMeta(TOKEN, dormir=lambda segundos: None)


def test_pede_so_os_campos_do_rf_01() -> None:
    assert montar_campos(ObjetoApi.CONTA) == "id,name,timezone_name,currency"
    assert montar_campos(ObjetoApi.CAMPANHA) == "id,name,objective,status"
    assert montar_campos(ObjetoApi.CONJUNTO) == (
        "id,name,optimization_goal,status,campaign_id,attribution_spec"
    )
    assert montar_campos(ObjetoApi.ANUNCIO) == (
        "id,name,status,adset_id,creative{id,title,body,call_to_action_type,"
        "effective_object_story_id,effective_instagram_media_id,"
        "instagram_permalink_url,actor_id}"
    )


def test_todo_campo_pedido_tem_entrada_no_mapa() -> None:
    for objeto in (ObjetoApi.CAMPANHA, ObjetoApi.CONJUNTO, ObjetoApi.ANUNCIO):
        campos = montar_campos(objeto).replace("{", ",").replace("}", "").split(",")
        mapeados = set(MAPA_CAMPOS[objeto]) | {
            nome_api
            for campo in MAPA_CAMPOS[objeto].values()
            if campo.tipo is TipoCampo.OBJETO
            for nome_api in MAPA_CAMPOS[campo.itens]
        }
        assert set(campos) <= mapeados


def test_filtro_de_status_inclui_arquivados_e_nao_pede_excluidos() -> None:
    # Sem ARCHIVED, as arestas omitem os arquivados, que têm insights; DELETED
    # a API recusa (R-38).
    assert "ARCHIVED" in STATUS_EFETIVOS_CADASTRO
    assert "DELETED" not in STATUS_EFETIVOS_CADASTRO


def test_extrai_a_conta_e_as_arestas_com_todas_as_paginas(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    fixtures = ler_fixtures()
    simular_cadastro(api, fixtures)

    extraido = extrair_cadastro_conta(cliente, ID_META_CONTA, lambda: INSTANTE)

    assert extraido.id_meta_conta == ID_META_CONTA
    assert extraido.conta.endpoint is Endpoint.OBJETO
    assert extraido.conta.paginas == [fixtures["cadastro_conta"]["corpo"]]
    # De baixo para cima, para que o pai criado durante a extração venha.
    assert list(extraido.arestas) == [
        Endpoint.ANUNCIOS,
        Endpoint.CONJUNTOS,
        Endpoint.CAMPANHAS,
    ]
    assert extraido.arestas[Endpoint.ANUNCIOS].paginas == [
        fixtures["cadastro_anuncios_pagina_1"]["corpo"],
        fixtures["cadastro_anuncios_pagina_2"]["corpo"],
    ]
    assert len(extraido.listar_consultas()) == 4


def test_guarda_os_parametros_de_cada_consulta_para_o_bruto(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    simular_cadastro(api, ler_fixtures())

    extraido = extrair_cadastro_conta(cliente, ID_META_CONTA, lambda: INSTANTE)

    parametros = extraido.arestas[Endpoint.CAMPANHAS].parametros
    assert parametros["fields"] == "id,name,objective,status"
    assert json.loads(parametros["effective_status"]) == list(STATUS_EFETIVOS_CADASTRO)
    assert parametros["limit"] == "100"
    assert "access_token" not in parametros


def test_data_de_referencia_e_o_dia_da_extracao_no_fuso_da_conta(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    simular_cadastro(api, ler_fixtures())

    extraido = extrair_cadastro_conta(cliente, ID_META_CONTA, lambda: INSTANTE)

    assert extraido.data_referencia == date(2026, 11, 3)


def test_conta_sem_fuso_e_resposta_invalida() -> None:
    with pytest.raises(ErroRespostaInvalida):
        calcular_data_referencia({"id": "act_995000000000001"}, INSTANTE)
