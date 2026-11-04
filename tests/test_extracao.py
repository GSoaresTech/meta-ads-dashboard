import json
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
import responses
from responses.registries import OrderedRegistry

from etl.cliente_api_meta import ClienteApiMeta, Endpoint, ErroRespostaInvalida
from etl.extracao import (
    CAMPOS_INSIGHTS_DIARIOS,
    STATUS_EFETIVOS_CADASTRO,
    calcular_data_referencia,
    extrair_cadastro_conta,
    extrair_entidades_por_id,
    extrair_insights_diarios,
    listar_anuncios_insights,
    montar_campos,
    montar_parametros_insights_diarios,
)
from etl.mapa_campos import MAPA_CAMPOS, ObjetoApi, TipoCampo
from tests.cadastro_exemplo import ID_META_CONTA, ler_fixtures, simular_cadastro
from tests.insights_exemplo import (
    FIM,
    ID_META_ANUNCIO_AUSENTE,
    INICIO,
    NOMES_PAGINAS,
    montar_parametros_insights,
    simular,
    simular_entidades,
    simular_insights,
)
from tests.insights_exemplo import ler_fixtures as ler_fixtures_insights

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


def ler_campos(objeto: ObjetoApi) -> dict[str, str]:
    return {"fields": montar_campos(objeto)}


def test_insights_pedem_o_nivel_de_anuncio_dia_a_dia_no_intervalo() -> None:
    parametros = montar_parametros_insights_diarios(INICIO, FIM)

    assert parametros == montar_parametros_insights()
    assert json.loads(parametros["time_range"]) == {
        "since": "2026-10-01",
        "until": "2026-10-02",
    }


def test_insights_ficam_na_janela_de_atribuicao_padrao() -> None:
    # A #15 concluiu que o parâmetro unificado não muda nenhum valor e que as
    # janelas explícitas não têm fonte confiável (ADR-0007; R-22).
    parametros = montar_parametros_insights_diarios(INICIO, FIM)

    assert "use_unified_attribution_setting" not in parametros
    assert "action_attribution_windows" not in parametros


def test_todo_campo_de_insights_pedido_tem_entrada_no_mapa() -> None:
    assert set(CAMPOS_INSIGHTS_DIARIOS) <= set(MAPA_CAMPOS[ObjetoApi.INSIGHTS])


def test_insights_vem_de_uma_consulta_paginada_da_conta(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    fixtures = ler_fixtures_insights()
    simular_insights(api, fixtures, com_entidades=False)

    consulta = extrair_insights_diarios(cliente, ID_META_CONTA, INICIO, FIM)

    assert consulta.endpoint is Endpoint.INSIGHTS
    assert consulta.parametros == montar_parametros_insights()
    assert consulta.paginas == [
        fixtures["insights_diarios_anuncio_pagina_1"]["corpo"],
        fixtures["insights_diarios_anuncio_pagina_2"]["corpo"],
    ]
    # Uma chamada por página, e não uma por anúncio (ADR-0003).
    assert len(api.calls) == 2


def test_lista_os_anuncios_dos_insights_sem_repeticao() -> None:
    fixtures = ler_fixtures_insights()
    paginas = [fixtures[nome]["corpo"] for nome in NOMES_PAGINAS]

    assert listar_anuncios_insights(paginas) == [
        "995000000000000010",
        "995000000000000015",
        "995000000000000020",
        "995000000000000019",
        ID_META_ANUNCIO_AUSENTE,
    ]


def test_linha_de_insights_sem_anuncio_e_resposta_invalida() -> None:
    with pytest.raises(ErroRespostaInvalida):
        listar_anuncios_insights([{"data": [{"spend": "1.00"}]}])


def test_le_pelo_id_o_anuncio_o_conjunto_e_a_campanha(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    fixtures = ler_fixtures_insights()
    simular_entidades(api, fixtures)

    entidades = extrair_entidades_por_id(cliente, [ID_META_ANUNCIO_AUSENTE])

    assert [c.paginas for c in entidades.listar_consultas()] == [
        [fixtures["entidade_anuncio_por_id"]["corpo"]],
        [fixtures["entidade_conjunto_por_id"]["corpo"]],
        [fixtures["entidade_campanha_por_id"]["corpo"]],
    ]
    assert all(c.endpoint is Endpoint.OBJETO for c in entidades.listar_consultas())
    assert entidades.anuncios.parametros == {"fields": montar_campos(ObjetoApi.ANUNCIO)}


def test_pai_comum_a_varios_anuncios_e_lido_uma_vez(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    fixtures = ler_fixtures_insights()
    outro = {**fixtures["entidade_anuncio_por_id"]}
    outro["corpo"] = {**outro["corpo"], "id": "995000000000000029"}
    anuncio = ler_campos(ObjetoApi.ANUNCIO)
    simular(api, ID_META_ANUNCIO_AUSENTE, fixtures["entidade_anuncio_por_id"], anuncio)
    simular(api, "995000000000000029", outro, anuncio)
    simular(
        api,
        "995000000000000025",
        fixtures["entidade_conjunto_por_id"],
        ler_campos(ObjetoApi.CONJUNTO),
    )
    simular(
        api,
        "995000000000000026",
        fixtures["entidade_campanha_por_id"],
        ler_campos(ObjetoApi.CAMPANHA),
    )

    entidades = extrair_entidades_por_id(
        cliente, [ID_META_ANUNCIO_AUSENTE, "995000000000000029"]
    )

    assert len(entidades.anuncios.paginas) == 2
    assert len(entidades.conjuntos.paginas) == 1
    assert len(entidades.campanhas.paginas) == 1


def test_sem_anuncio_ausente_nao_chama_a_api(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    entidades = extrair_entidades_por_id(cliente, [])

    assert all(not c.paginas for c in entidades.listar_consultas())
    assert not api.calls


def test_anuncio_sem_conjunto_e_resposta_invalida(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    fixture = ler_fixtures_insights()["entidade_anuncio_por_id"]
    del fixture["corpo"]["adset_id"]
    simular(api, ID_META_ANUNCIO_AUSENTE, fixture, ler_campos(ObjetoApi.ANUNCIO))

    with pytest.raises(ErroRespostaInvalida):
        extrair_entidades_por_id(cliente, [ID_META_ANUNCIO_AUSENTE])


def test_pagina_de_insights_sem_lista_de_linhas_e_resposta_invalida() -> None:
    with pytest.raises(ErroRespostaInvalida):
        listar_anuncios_insights([{"paging": {}}])
