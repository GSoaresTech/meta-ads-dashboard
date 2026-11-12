import copy
import json
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from etl.extracao import NivelAlcance, TipoPeriodo, TipoQuebra
from etl.mapa_campos import ErroCampoNaoMapeado
from etl.transformacao import (
    CadastroConta,
    ErroAlcance,
    ErroCadastro,
    ErroInsights,
    ErroQuebra,
    InsightsDiarios,
    QuebrasCampanha,
    transformar_alcance_periodo,
    transformar_cadastro,
    transformar_conjuntos,
    transformar_entidades,
    transformar_insights_diarios,
    transformar_quebras_campanha,
)
from tests import alcance_exemplo, quebras_exemplo
from tests.cadastro_exemplo import ID_META_CONTA, Fixtures, ler_fixtures
from tests.insights_exemplo import (
    ID_META_ANUNCIO_AUSENTE,
    NOMES_PAGINAS,
    listar_linhas,
)
from tests.insights_exemplo import ler_fixtures as ler_fixtures_insights

PASTA_FIXTURES = Path(__file__).parent / "fixtures"
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


def ler_linhas_resultados() -> list[dict]:
    """Uma linha de cada resultado fora de actions (R-24), uma com o
    resultado em actions e uma sem entrega, que a API acrescenta quando a
    consulta pede results."""
    fixture = PASTA_FIXTURES / "insights_resultados_fora_de_actions.json"
    return json.loads(fixture.read_text(encoding="utf-8"))["corpo"]["data"]


def transformar_linhas(linhas: list[dict]) -> InsightsDiarios:
    return transformar_insights_diarios([{"data": linhas}])


def quantidades_por_tipo(insights: InsightsDiarios) -> dict[tuple, object]:
    return {
        (acao["id_meta_anuncio"], acao["tipo_acao"]): acao["quantidade"]
        for acao in insights.acoes
    }


def test_resultado_fora_de_actions_e_igual_ao_do_indicator_com_ele_como_tipo() -> None:
    # Critério da #119: o valor gravado é o que a Meta conta em results, e o
    # tipo é o indicator, com ponto no lugar dos dois-pontos (R-24).
    linhas = ler_linhas_resultados()

    obtidas = quantidades_por_tipo(transformar_linhas(linhas))

    esperadas = {
        (linha["ad_id"], item["indicator"].replace(":", ".")): int(
            item["values"][0]["value"]
        )
        for linha in linhas
        for item in linha["results"]
        if item.get("values") and not item["indicator"].startswith("actions:")
    }
    assert len(esperadas) == 3
    assert esperadas.items() <= obtidas.items()
    assert {tipo for _, tipo in esperadas} == {
        "profile_visit_view",
        "video_thruplay_watched_actions",
        "conversions.contact_website",
    }


def test_thruplay_e_contato_vem_do_campo_proprio_mesmo_sem_ser_o_resultado() -> None:
    # Num conjunto com outro resultado, os dois campos continuam valendo: o
    # results é só a origem da visita ao perfil, que não vem em outro campo.
    linhas = ler_linhas_resultados()
    for linha in linhas[1:3]:
        linha["results"] = [{"indicator": "actions:post_engagement"}]

    obtidas = quantidades_por_tipo(transformar_linhas(linhas))

    assert obtidas[("995000000000000031", "video_thruplay_watched_actions")] == 243
    assert obtidas[("995000000000000032", "conversions.contact_website")] == 6


def test_visita_ao_perfil_so_vem_de_results() -> None:
    linhas = ler_linhas_resultados()
    linhas[0]["results"] = [{"indicator": "actions:link_click"}]

    obtidas = quantidades_por_tipo(transformar_linhas(linhas))

    assert not any(tipo == "profile_visit_view" for _, tipo in obtidas)


def test_so_o_contato_no_site_sai_de_conversions() -> None:
    # Os demais tipos de conversions não são resultado de nenhuma regra, e os
    # eventos personalizados trazem o nome do evento, fora do formato do tipo
    # de ação (ADR-0009 §2).
    insights = transformar_linhas(ler_linhas_resultados())

    tipos = {
        tipo
        for anuncio, tipo in quantidades_por_tipo(insights)
        if anuncio == "995000000000000032"
    }
    assert tipos == {
        "landing_page_view",
        "link_click",
        "offsite_conversion.fb_pixel_custom",
        "conversions.contact_website",
    }


def test_resultado_em_actions_nao_vira_outra_linha() -> None:
    linhas = ler_linhas_resultados()

    insights = transformar_linhas(linhas)

    tipos = {
        tipo
        for anuncio, tipo in quantidades_por_tipo(insights)
        if anuncio == "995000000000000033"
    }
    assert tipos == {item["action_type"] for item in linhas[3]["actions"]}


def test_linha_sem_entrega_e_sem_resultado_nao_vira_metrica() -> None:
    # Com results na consulta, a API devolve também anúncio e dia sem
    # investimento, impressões nem resultado, que a consulta sem ele não
    # devolve (R-24).
    linhas = ler_linhas_resultados()

    insights = transformar_linhas(linhas)

    assert [m["id_meta_anuncio"] for m in insights.metricas] == [
        linha["ad_id"] for linha in linhas[:4]
    ]
    assert all(a["id_meta_anuncio"] != "995000000000000034" for a in insights.acoes)


@pytest.mark.parametrize(
    ("lista", "tipo"),
    [
        ("actions", "omni_purchase"),
        ("action_values", "omni_purchase"),
        ("video_thruplay_watched_actions", "video_view"),
        ("conversions", "contact_website"),
    ],
)
def test_linha_sem_entrega_com_acao_continua(lista: str, tipo: str) -> None:
    # Conversões atribuídas a um dia sem entrega vêm em actions (R-21).
    linhas = ler_linhas_resultados()
    linhas[4][lista] = [{"action_type": tipo, "value": "1"}]

    insights = transformar_linhas(linhas)

    assert insights.metricas[-1]["id_meta_anuncio"] == "995000000000000034"
    assert insights.metricas[-1]["investimento"] == Decimal(0)


def test_linha_sem_entrega_com_visita_ao_perfil_continua() -> None:
    linhas = ler_linhas_resultados()
    linhas[4]["results"] = [
        {"indicator": "profile_visit_view", "values": [{"value": "1"}]}
    ]

    insights = transformar_linhas(linhas)

    assert insights.metricas[-1]["id_meta_anuncio"] == "995000000000000034"


def test_resultado_fora_de_actions_repetido_em_actions_e_recusado() -> None:
    linhas = ler_linhas_resultados()
    linhas[0]["actions"].append({"action_type": "profile_visit_view", "value": "1"})

    with pytest.raises(ErroInsights):
        transformar_linhas(linhas)


@pytest.mark.parametrize(
    "resultados",
    [
        [
            {"indicator": "profile_visit_view", "values": [{"value": "60"}]},
            {"indicator": "profile_visit_view", "values": [{"value": "60"}]},
        ],
        [
            {
                "indicator": "profile_visit_view",
                "values": [
                    {"value": "60", "attribution_windows": ["7d_click"]},
                    {"value": "4", "attribution_windows": ["1d_view"]},
                ],
            }
        ],
    ],
)
def test_resultado_fora_do_formato_verificado_e_recusado(resultados: list) -> None:
    # Um item por linha, com no máximo um valor, na janela padrão (R-24):
    # somar janelas ou indicadores daria um número que a Meta não conta.
    linhas = ler_linhas_resultados()
    linhas[0]["results"] = resultados

    with pytest.raises(ErroInsights):
        transformar_linhas(linhas)


@pytest.mark.parametrize(
    "resultados",
    [
        [{"indicator": "reach", "values": [{"value": "9"}, {"value": "3"}]}],
        [
            {"indicator": "actions:link_click"},
            {"indicator": "actions:link_click"},
        ],
        [{"values": [{"value": "60"}]}],
    ],
)
def test_indicator_que_nao_e_lido_de_results_nao_e_conferido(
    resultados: list,
) -> None:
    # Só a visita ao perfil é lida de results; os demais resultados vêm por
    # outros campos, e uma variação neles não derruba a carga.
    linhas = ler_linhas_resultados()
    linhas[3]["results"] = resultados

    insights = transformar_linhas(linhas)

    assert len(insights.metricas) == 4


def transformar_alcance(
    nivel: NivelAlcance, linhas: list[dict], tipo: TipoPeriodo = TipoPeriodo.SEMANA
) -> list[dict[str, object]]:
    return transformar_alcance_periodo([{"data": linhas}], nivel, tipo)


def ler_linhas_alcance(nivel: str, tipo: str) -> list[dict]:
    return alcance_exemplo.listar_linhas(alcance_exemplo.ler_fixtures(), nivel, tipo)


def test_cada_linha_de_alcance_vira_uma_linha_da_entidade_no_periodo() -> None:
    linhas = transformar_alcance(
        NivelAlcance.CAMPANHA, ler_linhas_alcance("campanha", "semana")
    )

    assert len(linhas) == 6
    assert linhas[0] == {
        "id_meta_campanha": "995000000000000002",
        "id_meta_anuncio": None,
        "tipo_periodo": "semana",
        "inicio_periodo": date(2026, 3, 9),
        "fim_periodo": date(2026, 3, 15),
        "alcance": 5120,
        "impressoes": 9010,
    }


def test_alcance_do_anuncio_aponta_para_o_anuncio_pelo_id_da_meta() -> None:
    linhas = transformar_alcance(
        NivelAlcance.ANUNCIO, ler_linhas_alcance("anuncio", "ano"), TipoPeriodo.ANO
    )

    assert [(l["id_meta_campanha"], l["id_meta_anuncio"]) for l in linhas] == [
        (None, "995000000000000010"),
        (None, "995000000000000015"),
        (None, ID_META_ANUNCIO_AUSENTE),
    ]
    assert {l["tipo_periodo"] for l in linhas} == {"ano"}


def test_alcance_da_conta_fica_sem_campanha_nem_anuncio() -> None:
    linhas = transformar_alcance(
        NivelAlcance.CONTA, ler_linhas_alcance("conta", "mes"), TipoPeriodo.MES
    )

    assert [
        (l["id_meta_campanha"], l["id_meta_anuncio"], l["inicio_periodo"], l["alcance"])
        for l in linhas
    ] == [
        (None, None, date(2026, 3, 1), 24310),
        (None, None, date(2026, 4, 1), 6820),
    ]


def test_alcance_ausente_fica_nulo_e_nao_zero() -> None:
    # Métrica-base ausente é NULL (CLAUDE.md §5).
    linhas = ler_linhas_alcance("conta", "semana")
    del linhas[0]["reach"]

    assert transformar_alcance(NivelAlcance.CONTA, linhas)[0]["alcance"] is None


@pytest.mark.parametrize(
    ("nivel", "linha"),
    [
        (NivelAlcance.CONTA, {"campaign_id": "995000000000000002"}),
        (NivelAlcance.CAMPANHA, {}),
        (NivelAlcance.CAMPANHA, {"ad_id": "995000000000000010"}),
        (NivelAlcance.ANUNCIO, {"campaign_id": "995000000000000002"}),
        (
            NivelAlcance.ANUNCIO,
            {"ad_id": "995000000000000010", "campaign_id": "995000000000000002"},
        ),
    ],
)
def test_linha_de_alcance_fora_do_nivel_consultado_e_recusada(
    nivel: NivelAlcance, linha: dict
) -> None:
    periodo = {"reach": "1", "date_start": "2026-03-09", "date_stop": "2026-03-15"}

    with pytest.raises(ErroAlcance, match="fora do nível"):
        transformar_alcance(nivel, [{**linha, **periodo}])


@pytest.mark.parametrize(
    "periodo",
    [
        {"date_start": "2026-03-09"},
        {"date_stop": "2026-03-15"},
        {"date_start": "2026-03-15", "date_stop": "2026-03-09"},
    ],
)
def test_linha_de_alcance_sem_periodo_valido_e_recusada(periodo: dict) -> None:
    with pytest.raises(ErroAlcance, match="período"):
        transformar_alcance(NivelAlcance.CONTA, [{"reach": "1", **periodo}])


def test_entidade_e_periodo_repetidos_sao_recusados_sem_citar_o_id() -> None:
    # A carga substitui o conjunto completo, e uma das duas linhas se
    # perderia.
    linhas = ler_linhas_alcance("anuncio", "semana")
    linhas.append(copy.deepcopy(linhas[0]))

    with pytest.raises(ErroAlcance, match="1 linha") as erro:
        transformar_alcance(NivelAlcance.ANUNCIO, linhas)

    assert "995000000000000010" not in str(erro.value)


def test_campo_de_alcance_nao_pedido_e_recusado_pelo_mapa() -> None:
    linhas = ler_linhas_alcance("conta", "ano")
    linhas[0]["clicks"] = "98765"

    with pytest.raises(ErroCampoNaoMapeado):
        transformar_alcance(NivelAlcance.CONTA, linhas, TipoPeriodo.ANO)


def test_resultado_assincrono_com_account_id_vira_as_linhas_da_consulta_sincrona() -> (
    None
):
    # O resultado do job assíncrono traz o account_id em toda linha, sem ser
    # pedido (R-39), e o alcance do ano por campanha cai sempre nele.
    assincrono = json.loads(
        (
            alcance_exemplo.PASTA_FIXTURES / "alcance_campanha_ano_assincrono.json"
        ).read_text(encoding="utf-8")
    )["corpo"]["data"]
    assert {linha["account_id"] for linha in assincrono} == {ID_META_CONTA}

    assert transformar_alcance(
        NivelAlcance.CAMPANHA, assincrono, TipoPeriodo.ANO
    ) == transformar_alcance(
        NivelAlcance.CAMPANHA, ler_linhas_alcance("campanha", "ano"), TipoPeriodo.ANO
    )


def transformar_quebra(
    tipo: TipoQuebra,
    linhas: list[dict],
    tipos_acao: dict[str, str] = quebras_exemplo.TIPOS_ACAO_RESULTADO,
) -> QuebrasCampanha:
    return transformar_quebras_campanha([{"data": linhas}], tipo, tipos_acao)


def ler_linhas_quebra(tipo: TipoQuebra) -> list[dict]:
    return quebras_exemplo.listar_linhas(quebras_exemplo.ler_fixtures(), tipo)


@pytest.mark.parametrize(
    ("tipo", "categoria", "subcategoria", "investimento", "impressoes", "alcance"),
    [
        (TipoQuebra.IDADE_GENERO, "25-34", "female", "8.15", 1181, 1023),
        (TipoQuebra.PLATAFORMA_POSICIONAMENTO, "instagram", "feed", "8.8", 1274, 1103),
        (TipoQuebra.REGIAO, "São Paulo (state)", None, "9.87", 1430, 1238),
    ],
)
def test_cada_linha_de_quebra_vira_uma_linha_da_campanha_no_dia_e_categoria(
    tipo: TipoQuebra,
    categoria: str,
    subcategoria: str | None,
    investimento: str,
    impressoes: int,
    alcance: int,
) -> None:
    # Idade e plataforma são a categoria; gênero e posicionamento, a
    # subcategoria. A região tem uma dimensão só (ADR-0009 §2).
    linhas = ler_linhas_quebra(tipo)

    quebras = transformar_quebra(tipo, linhas).quebras

    assert len(quebras) == len(linhas)
    assert quebras[0] == {
        "id_meta_campanha": "995000000000000002",
        "data": date(2026, 10, 1),
        "tipo_quebra": str(tipo),
        "categoria": categoria,
        "subcategoria": subcategoria,
        "investimento": Decimal(investimento),
        "impressoes": impressoes,
        "alcance": alcance,
    }


@pytest.mark.parametrize("tipo", list(TipoQuebra))
def test_so_a_acao_do_resultado_principal_de_cada_campanha_vira_linha(
    tipo: TipoQuebra,
) -> None:
    # A resposta traz cliques, interações e eventos do pixel; só o tipo do
    # resultado principal da campanha fica (RF-03; ADR-0011).
    linhas = ler_linhas_quebra(tipo)

    acoes = transformar_quebra(tipo, linhas).acoes

    esperadas = Counter(
        linha["campaign_id"]
        for linha in linhas
        for item in linha.get("actions", [])
        if item["action_type"]
        == quebras_exemplo.TIPOS_ACAO_RESULTADO[linha["campaign_id"]]
    )
    assert Counter(acao["id_meta_campanha"] for acao in acoes) == esperadas
    assert all(
        acao["tipo_acao"]
        == quebras_exemplo.TIPOS_ACAO_RESULTADO[acao["id_meta_campanha"]]
        for acao in acoes
    )


def test_acao_do_resultado_traz_quantidade_e_valor_com_o_grao_da_quebra() -> None:
    linhas = ler_linhas_quebra(TipoQuebra.IDADE_GENERO)

    acoes = transformar_quebra(TipoQuebra.IDADE_GENERO, linhas).acoes

    compras = [a for a in acoes if a["id_meta_campanha"] == "995000000000000005"]
    assert compras[0] == {
        "id_meta_campanha": "995000000000000005",
        "data": date(2026, 10, 1),
        "tipo_quebra": "idade_genero",
        "categoria": "25-34",
        "subcategoria": "female",
        "tipo_acao": "omni_purchase",
        "quantidade": 2,
        "valor": Decimal("259.8"),
    }


def test_regiao_sem_acao_de_fora_da_meta_fica_sem_linha_e_nao_com_zero() -> None:
    # A região não devolve cadastros nem compras pelo pixel (R-23). A falta
    # não vira linha com zero: é "não disponível" na leitura (ADR-0011).
    linhas = ler_linhas_quebra(TipoQuebra.REGIAO)

    quebras = transformar_quebra(TipoQuebra.REGIAO, linhas)

    campanhas = {acao["id_meta_campanha"] for acao in quebras.acoes}
    assert campanhas == {"995000000000000002", "995000000000000004"}
    assert all(acao["quantidade"] > 0 for acao in quebras.acoes)
    assert {"995000000000000003", "995000000000000005"} <= {
        quebra["id_meta_campanha"] for quebra in quebras.quebras
    }


@pytest.mark.parametrize(
    ("campo", "valor", "tipo_acao"),
    [
        (
            "results",
            [{"indicator": "profile_visit_view", "values": [{"value": "12"}]}],
            "profile_visit_view",
        ),
        (
            "video_thruplay_watched_actions",
            [{"action_type": "video_view", "value": "12"}],
            "video_thruplay_watched_actions",
        ),
        (
            "conversions",
            [{"action_type": "contact_website", "value": "12"}],
            "conversions.contact_website",
        ),
    ],
)
def test_resultado_fora_de_actions_da_campanha_vira_acao_da_quebra(
    campo: str, valor: list, tipo_acao: str
) -> None:
    # A quebra grava o tipo do resultado principal (ADR-0011), também quando
    # ele vem fora de actions.
    linhas = ler_linhas_quebra(TipoQuebra.IDADE_GENERO)
    linha = linhas[0]
    linha[campo] = valor

    acoes = transformar_quebra(
        TipoQuebra.IDADE_GENERO, [linha], {linha["campaign_id"]: tipo_acao}
    ).acoes

    assert [(a["tipo_acao"], a["quantidade"]) for a in acoes] == [(tipo_acao, 12)]


def test_linha_de_quebra_sem_entrega_e_sem_resultado_nao_vira_linha() -> None:
    linhas = ler_linhas_quebra(TipoQuebra.IDADE_GENERO)
    vazia = {
        **{chave: linhas[0][chave] for chave in ("campaign_id", "age", "date_start")},
        "date_stop": linhas[0]["date_stop"],
        "gender": "unknown",
        "spend": "0",
        "impressions": "0",
        "results": [{"indicator": "profile_visit_view"}],
    }

    quebras = transformar_quebra(TipoQuebra.IDADE_GENERO, [*linhas, vazia]).quebras

    assert len(quebras) == len(linhas)


def test_campanha_sem_resultado_de_acao_fica_so_com_as_metricas_base() -> None:
    # Alcance, "Não classificado" e as regras sem resultado principal não são
    # tipos de ação: a campanha não entra no mapa (ADR-0011).
    linhas = ler_linhas_quebra(TipoQuebra.IDADE_GENERO)

    quebras = transformar_quebra(TipoQuebra.IDADE_GENERO, linhas, {})

    assert len(quebras.quebras) == len(linhas)
    assert quebras.acoes == []


def test_investimento_zero_e_zero_e_alcance_ausente_e_nulo() -> None:
    # Com quebras, a API não devolve alcance de datas a mais de 13 meses
    # (R-18): ausente é nulo, e não zero.
    linhas = ler_linhas_quebra(TipoQuebra.REGIAO)
    sem_entrega = next(i for i, linha in enumerate(linhas) if linha["spend"] == "0")
    del linhas[0]["reach"]

    quebras = transformar_quebra(TipoQuebra.REGIAO, linhas).quebras

    assert quebras[sem_entrega]["investimento"] == Decimal(0)
    assert quebras[0]["alcance"] is None


def test_categoria_e_aparada_e_vazia_e_recusada() -> None:
    linhas = ler_linhas_quebra(TipoQuebra.REGIAO)
    linhas[0]["region"] = "  São Paulo (state) "

    assert transformar_quebra(TipoQuebra.REGIAO, linhas).quebras[0]["categoria"] == (
        "São Paulo (state)"
    )

    linhas[0]["region"] = " "
    with pytest.raises(ErroQuebra):
        transformar_quebra(TipoQuebra.REGIAO, linhas)


@pytest.mark.parametrize(
    ("tipo", "campo"),
    [
        (TipoQuebra.IDADE_GENERO, "gender"),
        (TipoQuebra.PLATAFORMA_POSICIONAMENTO, "platform_position"),
        (TipoQuebra.REGIAO, "region"),
    ],
)
def test_linha_sem_dimensao_da_combinacao_e_recusada(
    tipo: TipoQuebra, campo: str
) -> None:
    linhas = ler_linhas_quebra(tipo)
    del linhas[0][campo]

    with pytest.raises(ErroQuebra):
        transformar_quebra(tipo, linhas)


def test_linha_de_outra_combinacao_e_recusada() -> None:
    # Uma dimensão a mais mudaria o grão: as categorias se repetiriam.
    linhas = ler_linhas_quebra(TipoQuebra.REGIAO)
    linhas[0]["age"] = "25-34"

    with pytest.raises(ErroQuebra):
        transformar_quebra(TipoQuebra.REGIAO, linhas)


def test_linha_de_quebra_sem_campanha_e_recusada() -> None:
    linhas = ler_linhas_quebra(TipoQuebra.IDADE_GENERO)
    del linhas[0]["campaign_id"]

    with pytest.raises(ErroQuebra):
        transformar_quebra(TipoQuebra.IDADE_GENERO, linhas)


def test_linha_de_quebra_que_nao_e_de_um_dia_e_recusada() -> None:
    linhas = ler_linhas_quebra(TipoQuebra.IDADE_GENERO)
    linhas[0]["date_stop"] = "2026-10-02"

    with pytest.raises(ErroQuebra):
        transformar_quebra(TipoQuebra.IDADE_GENERO, linhas)


def test_categoria_repetida_na_campanha_e_dia_e_recusada_sem_citar_o_id() -> None:
    # A carga substitui o conjunto completo, e uma das duas linhas se
    # perderia.
    linhas = ler_linhas_quebra(TipoQuebra.PLATAFORMA_POSICIONAMENTO)
    linhas.append(copy.deepcopy(linhas[0]))

    with pytest.raises(ErroQuebra) as erro:
        transformar_quebra(TipoQuebra.PLATAFORMA_POSICIONAMENTO, linhas)
    assert "995000000000000002" not in str(erro.value)


def test_mesma_categoria_em_plataformas_diferentes_nao_e_repetida() -> None:
    # O feed do Instagram e o do Facebook têm o mesmo posicionamento.
    linhas = ler_linhas_quebra(TipoQuebra.PLATAFORMA_POSICIONAMENTO)

    quebras = transformar_quebra(TipoQuebra.PLATAFORMA_POSICIONAMENTO, linhas).quebras

    feeds = {
        q["categoria"]
        for q in quebras
        if q["subcategoria"] == "feed" and q["id_meta_campanha"] == "995000000000000002"
    }
    assert feeds == {"instagram", "facebook"}


def test_campo_de_quebra_nao_pedido_e_recusado_pelo_mapa() -> None:
    linhas = ler_linhas_quebra(TipoQuebra.REGIAO)
    linhas[0]["cpc"] = "0.37"

    with pytest.raises(ErroCampoNaoMapeado):
        transformar_quebra(TipoQuebra.REGIAO, linhas)
