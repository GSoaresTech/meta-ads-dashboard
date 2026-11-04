import copy
from collections import Counter
from datetime import date
from decimal import Decimal

import pytest

from etl.mapa_campos import ErroCampoNaoMapeado
from etl.transformacao import (
    CadastroConta,
    ErroCadastro,
    ErroInsights,
    InsightsDiarios,
    transformar_cadastro,
    transformar_conjuntos,
    transformar_entidades,
    transformar_insights_diarios,
)
from tests.cadastro_exemplo import ID_META_CONTA, Fixtures, ler_fixtures
from tests.insights_exemplo import (
    ID_META_ANUNCIO_AUSENTE,
    NOMES_PAGINAS,
    listar_linhas,
)
from tests.insights_exemplo import ler_fixtures as ler_fixtures_insights

ID_CRIATIVO_REUTILIZADO = "9950000000000011"
ID_PAGINA = "995000000000012"


def transformar(fixtures: Fixtures) -> CadastroConta:
    return transformar_cadastro(
        ID_META_CONTA,
        fixtures["cadastro_conta"]["corpo"],
        [fixtures["cadastro_campanhas"]["corpo"]],
        [fixtures["cadastro_conjuntos"]["corpo"]],
        [
            fixtures["cadastro_anuncios_pagina_1"]["corpo"],
            fixtures["cadastro_anuncios_pagina_2"]["corpo"],
        ],
    )


def anuncios(fixtures: Fixtures) -> list[dict]:
    return [
        *fixtures["cadastro_anuncios_pagina_1"]["corpo"]["data"],
        *fixtures["cadastro_anuncios_pagina_2"]["corpo"]["data"],
    ]


def test_conta_traz_nome_fuso_e_moeda() -> None:
    cadastro = transformar(ler_fixtures())

    assert cadastro.conta == {
        "nome": "Conta Exemplo Cadastro",
        "fuso_horario": "America/Sao_Paulo",
        "moeda": "BRL",
    }


def test_resposta_de_outra_conta_e_recusada() -> None:
    fixtures = ler_fixtures()

    with pytest.raises(ErroCadastro):
        transformar_cadastro(
            "995000000000999",
            fixtures["cadastro_conta"]["corpo"],
            [],
            [],
            [],
        )


def test_campanhas_com_nome_objetivo_e_status() -> None:
    cadastro = transformar(ler_fixtures())

    assert len(cadastro.campanhas) == 4
    assert cadastro.campanhas[0] == {
        "id_meta": "995000000000000002",
        "nome": "Campanha Exemplo 1",
        "objetivo": "OUTCOME_ENGAGEMENT",
        "status": "PAUSED",
    }
    assert cadastro.campanhas[-1]["status"] == "ARCHIVED"


def test_conjuntos_com_meta_de_otimizacao_e_campanha_pelo_id_da_meta() -> None:
    cadastro = transformar(ler_fixtures())

    assert len(cadastro.conjuntos) == 4
    assert cadastro.conjuntos[1] == {
        "id_meta": "995000000000000007",
        "nome": "Conjunto Exemplo 2",
        "meta_otimizacao": "OFFSITE_CONVERSIONS",
        "status": "ACTIVE",
        "id_meta_campanha": "995000000000000003",
    }


def test_janelas_de_atribuicao_viram_linhas_por_conjunto() -> None:
    cadastro = transformar(ler_fixtures())

    assert len(cadastro.janelas) == 1 + 3 + 1 + 2
    assert [j for j in cadastro.janelas if j["id_meta_conjunto"].endswith("07")] == [
        {"id_meta_conjunto": "995000000000000007", "tipo_evento": t, "janela_dias": d}
        for t, d in (
            ("CLICK_THROUGH", 7),
            ("VIEW_THROUGH", 1),
            ("ENGAGED_VIDEO_VIEW", 1),
        )
    ]


def test_conjunto_sem_attribution_spec_fica_sem_janelas() -> None:
    conjuntos, janelas = transformar_conjuntos(
        [{"id": "995000000000000006", "name": "Conjunto", "status": "ACTIVE"}]
    )

    assert len(conjuntos) == 1
    assert janelas == []


def test_anuncios_apontam_para_conjunto_e_criativo_pelo_id_da_meta() -> None:
    cadastro = transformar(ler_fixtures())

    assert len(cadastro.anuncios) == 4
    assert cadastro.anuncios[0] == {
        "id_meta": "995000000000000010",
        "nome": "Anúncio Exemplo 1",
        "status": "ACTIVE",
        "id_meta_conjunto": "995000000000000006",
        "id_meta_criativo": ID_CRIATIVO_REUTILIZADO,
    }
    assert cadastro.anuncios[3]["status"] == "ARCHIVED"


def test_criativo_reutilizado_vira_uma_linha_so() -> None:
    cadastro = transformar(ler_fixtures())

    assert [c["id_meta"] for c in cadastro.criativos] == [
        ID_CRIATIVO_REUTILIZADO,
        "9950000000000016",
        "9950000000000021",
    ]
    assert cadastro.anuncios[2]["id_meta_criativo"] == ID_CRIATIVO_REUTILIZADO


def test_criativo_traz_textos_chamada_e_identificadores_do_post() -> None:
    cadastro = transformar(ler_fixtures())

    assert cadastro.criativos[1] == {
        "id_meta": "9950000000000016",
        "id_meta_pagina": ID_PAGINA,
        "titulo": "Título Exemplo 2",
        "texto": "Texto de exemplo do criativo 2.",
        "chamada_acao": "LEARN_MORE",
        "id_publicacao_facebook": f"{ID_PAGINA}_9950000000000018",
        "id_midia_instagram": "99500000000000017",
        "link_publicacao_instagram": "https://www.instagram.com/p/Exemplo0002Ab/",
    }


def test_campo_ausente_no_criativo_vira_nulo() -> None:
    cadastro = transformar(ler_fixtures())

    # O criativo 1 não tem body, e o 3 não tem link do Instagram.
    assert cadastro.criativos[0]["texto"] is None
    assert cadastro.criativos[2]["link_publicacao_instagram"] is None


def test_paginas_vem_do_actor_id_sem_repeticao() -> None:
    cadastro = transformar(ler_fixtures())

    assert cadastro.paginas == [ID_PAGINA]


def test_criativo_sem_actor_id_fica_sem_pagina() -> None:
    fixtures = ler_fixtures()
    for anuncio in anuncios(fixtures):
        del anuncio["creative"]["actor_id"]

    cadastro = transformar(fixtures)

    assert cadastro.paginas == []
    assert all(c["id_meta_pagina"] is None for c in cadastro.criativos)


def test_texto_e_aparado_e_vazio_vira_nulo() -> None:
    fixtures = ler_fixtures()
    campanha = fixtures["cadastro_campanhas"]["corpo"]["data"][0]
    campanha["name"] = "  Campanha Exemplo 1 "
    anuncios(fixtures)[1]["creative"]["body"] = "   "

    cadastro = transformar(fixtures)

    assert cadastro.campanhas[0]["nome"] == "Campanha Exemplo 1"
    assert cadastro.criativos[1]["texto"] is None


def test_anuncio_repetido_entre_paginas_fica_com_a_ultima_leitura() -> None:
    fixtures = ler_fixtures()
    pagina_2 = fixtures["cadastro_anuncios_pagina_2"]["corpo"]["data"]
    repetido = copy.deepcopy(anuncios(fixtures)[0])
    repetido["name"] = "Anúncio Exemplo 1 renomeado"
    pagina_2.append(repetido)

    cadastro = transformar(fixtures)

    assert len(cadastro.anuncios) == 4
    assert cadastro.anuncios[0]["nome"] == "Anúncio Exemplo 1 renomeado"


def test_conjunto_de_campanha_fora_da_extracao_e_recusado_sem_citar_o_id() -> None:
    fixtures = ler_fixtures()
    del fixtures["cadastro_campanhas"]["corpo"]["data"][0]

    with pytest.raises(ErroCadastro) as erro:
        transformar(fixtures)

    assert "995000000000000002" not in str(erro.value)


def test_anuncio_de_conjunto_fora_da_extracao_e_recusado() -> None:
    fixtures = ler_fixtures()
    anuncios(fixtures)[0]["adset_id"] = "995000000000000999"

    with pytest.raises(ErroCadastro):
        transformar(fixtures)


def test_anuncio_sem_criativo_e_recusado() -> None:
    fixtures = ler_fixtures()
    del anuncios(fixtures)[0]["creative"]

    with pytest.raises(ErroCadastro):
        transformar(fixtures)


def test_campo_nao_pedido_e_recusado_pelo_mapa() -> None:
    fixtures = ler_fixtures()
    fixtures["cadastro_campanhas"]["corpo"]["data"][0]["effective_status"] = "PAUSED"

    with pytest.raises(ErroCampoNaoMapeado):
        transformar(fixtures)


def test_entidades_lidas_pelo_id_viram_linhas_com_o_pai_pelo_id_da_meta() -> None:
    fixtures = ler_fixtures_insights()

    entidades = transformar_entidades(
        [fixtures["entidade_campanha_por_id"]["corpo"]],
        [fixtures["entidade_conjunto_por_id"]["corpo"]],
        [fixtures["entidade_anuncio_por_id"]["corpo"]],
    )

    assert entidades.anuncios == [
        {
            "id_meta": ID_META_ANUNCIO_AUSENTE,
            "nome": "Anúncio Exemplo 5",
            "status": "DELETED",
            "id_meta_conjunto": "995000000000000025",
            "id_meta_criativo": "9950000000000027",
        }
    ]
    assert entidades.conjuntos[0]["id_meta_campanha"] == "995000000000000026"
    assert [c["id_meta"] for c in entidades.campanhas] == ["995000000000000026"]
    assert entidades.paginas == [ID_PAGINA]
    assert len(entidades.janelas) == 2


def transformar_insights(fixtures: Fixtures) -> InsightsDiarios:
    return transformar_insights_diarios(
        [fixtures[nome]["corpo"] for nome in NOMES_PAGINAS]
    )


def acoes_do_grao(insights: InsightsDiarios, id_meta: str, dia: date) -> list[dict]:
    return [
        acao
        for acao in insights.acoes
        if acao["id_meta_anuncio"] == id_meta and acao["data"] == dia
    ]


def test_cada_linha_de_insights_vira_uma_metrica_do_anuncio_no_dia() -> None:
    insights = transformar_insights(ler_fixtures_insights())

    assert len(insights.metricas) == 8
    assert insights.metricas[0] == {
        "id_meta_anuncio": "995000000000000010",
        "data": date(2026, 10, 1),
        "investimento": Decimal("21.47"),
        "impressoes": 3105,
        "alcance": 2688,
    }


def test_resposta_com_12_itens_em_actions_gera_12_linhas() -> None:
    # Critério do RF-12. O anúncio de vendas tem 12 tipos no primeiro dia.
    fixtures = ler_fixtures_insights()
    linha = listar_linhas(fixtures)[2]
    assert len(linha["actions"]) == 12

    insights = transformar_insights(fixtures)

    acoes = acoes_do_grao(insights, linha["ad_id"], date(2026, 10, 1))
    assert len(acoes) == 12
    assert {a["tipo_acao"] for a in acoes} == {
        a["action_type"] for a in linha["actions"]
    }


def test_soma_por_tipo_de_acao_e_igual_a_da_resposta() -> None:
    # Critério do RF-12, na quantidade e no valor.
    fixtures = ler_fixtures_insights()
    esperadas: Counter[tuple[str, str]] = Counter()
    for linha in listar_linhas(fixtures):
        for lista, medida, tipo in (
            ("actions", "quantidade", int),
            ("action_values", "valor", Decimal),
        ):
            for item in linha.get(lista, ()):
                esperadas[(medida, item["action_type"])] += tipo(item["value"])

    insights = transformar_insights(fixtures)

    obtidas: Counter[tuple[str, str]] = Counter()
    for acao in insights.acoes:
        for medida in ("quantidade", "valor"):
            if acao[medida] is not None:
                obtidas[(medida, acao["tipo_acao"])] += acao[medida]
    assert obtidas == esperadas


def test_quantidade_vem_de_actions_e_valor_de_action_values() -> None:
    insights = transformar_insights(ler_fixtures_insights())

    acoes = acoes_do_grao(insights, "995000000000000020", date(2026, 10, 1))
    compra = next(a for a in acoes if a["tipo_acao"] == "omni_purchase")
    assert compra == {
        "id_meta_anuncio": "995000000000000020",
        "data": date(2026, 10, 1),
        "tipo_acao": "omni_purchase",
        "quantidade": 2,
        "valor": Decimal("259.8"),
    }
    clique = next(a for a in acoes if a["tipo_acao"] == "link_click")
    assert clique["valor"] is None


def test_tipo_so_em_action_values_fica_sem_quantidade() -> None:
    fixtures = ler_fixtures_insights()
    linha = listar_linhas(fixtures)[0]
    linha["action_values"] = [{"action_type": "omni_purchase", "value": "99.9"}]

    insights = transformar_insights(fixtures)

    acoes = acoes_do_grao(insights, linha["ad_id"], date(2026, 10, 1))
    assert len(acoes) == len(linha["actions"]) + 1
    assert acoes[-1] == {
        "id_meta_anuncio": linha["ad_id"],
        "data": date(2026, 10, 1),
        "tipo_acao": "omni_purchase",
        "quantidade": None,
        "valor": Decimal("99.9"),
    }


def test_investimento_zero_e_zero_e_campo_ausente_e_nulo() -> None:
    fixtures = ler_fixtures_insights()
    linha = listar_linhas(fixtures)[3]
    del linha["reach"]
    del linha["actions"]

    insights = transformar_insights(fixtures)

    metrica = insights.metricas[3]
    assert metrica["investimento"] == Decimal(0)
    assert metrica["alcance"] is None
    assert acoes_do_grao(insights, linha["ad_id"], date(2026, 10, 1)) == []


def test_linha_que_nao_e_de_um_dia_e_recusada() -> None:
    fixtures = ler_fixtures_insights()
    listar_linhas(fixtures)[0]["date_stop"] = "2026-10-02"

    with pytest.raises(ErroInsights):
        transformar_insights(fixtures)


def test_linha_sem_anuncio_e_recusada() -> None:
    fixtures = ler_fixtures_insights()
    del listar_linhas(fixtures)[0]["ad_id"]

    with pytest.raises(ErroInsights):
        transformar_insights(fixtures)


def test_tipo_de_acao_repetido_na_linha_e_recusado() -> None:
    fixtures = ler_fixtures_insights()
    acoes = listar_linhas(fixtures)[0]["actions"]
    acoes.append(dict(acoes[0]))

    with pytest.raises(ErroInsights):
        transformar_insights(fixtures)


def test_anuncio_e_dia_repetidos_sao_recusados_sem_citar_o_id() -> None:
    fixtures = ler_fixtures_insights()
    pagina = fixtures["insights_diarios_anuncio_pagina_2"]["corpo"]["data"]
    pagina.append(copy.deepcopy(listar_linhas(fixtures)[0]))

    with pytest.raises(ErroInsights) as erro:
        transformar_insights(fixtures)
    assert "995000000000000010" not in str(erro.value)


def test_campo_de_insights_nao_pedido_e_recusado_pelo_mapa() -> None:
    fixtures = ler_fixtures_insights()
    listar_linhas(fixtures)[0]["cpc"] = "0.37"

    with pytest.raises(ErroCampoNaoMapeado):
        transformar_insights(fixtures)
