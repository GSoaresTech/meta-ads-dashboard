import itertools
import json

import pytest

from etl.configuracao import (
    ESPERA_INICIAL_SEGUNDOS,
    ESPERA_MAXIMA_SEGUNDOS,
    LIMITE_USO_PERCENTUAL,
    MAXIMO_TENTATIVAS,
)
from etl.limites_api_meta import (
    ErroGraph,
    TipoErro,
    UsoApi,
    calcular_espera_backoff,
    calcular_pausa_preventiva,
    classificar_erro,
    decidir_espera,
    ler_erro_graph,
    ler_uso,
)

SEM_USO = UsoApi(percentual=0, espera_recuperacao_segundos=0)

# O ID de BM é a chave do X-Business-Use-Case-Usage; inventado, no formato real.
ID_BM_FICTICIO = "990000000000009"


def montar_uso_negocio(**campos: object) -> str:
    item = {
        "type": "ads_insights",
        "call_count": 0,
        "total_cputime": 0,
        "total_time": 0,
        "estimated_time_to_regain_access": 0,
        "ads_api_access_tier": "development_access",
    }
    item.update(campos)
    return json.dumps({ID_BM_FICTICIO: [item]})


@pytest.mark.parametrize("codigo", [4, 17, 613, *range(80000, 80015)])
def test_codigos_de_limite_do_rf_08_sao_limite_de_taxa(codigo: int) -> None:
    assert classificar_erro(400, ErroGraph(codigo, None, False)) is TipoErro.LIMITE_TAXA


def test_excesso_de_linhas_tem_tipo_proprio() -> None:
    erro = ErroGraph(100, 1487534, False)

    assert classificar_erro(400, erro) is TipoErro.EXCESSO_LINHAS


@pytest.mark.parametrize(
    ("status_http", "erro", "tipo"),
    [
        (500, ErroGraph(1, None, False), TipoErro.TRANSITORIO),
        (503, ErroGraph(2, None, True), TipoErro.TRANSITORIO),
        (400, ErroGraph(341, None, False), TipoErro.TRANSITORIO),
        (400, ErroGraph(9999, None, True), TipoErro.TRANSITORIO),
        (502, None, TipoErro.TRANSITORIO),
        (401, ErroGraph(190, 463, False), TipoErro.AUTENTICACAO),
        (400, ErroGraph(102, None, False), TipoErro.AUTENTICACAO),
        (403, ErroGraph(10, None, False), TipoErro.PERMISSAO),
        (403, ErroGraph(200, None, False), TipoErro.PERMISSAO),
        (403, ErroGraph(299, None, False), TipoErro.PERMISSAO),
        (400, ErroGraph(100, 33, False), TipoErro.DEFINITIVO),
        (400, ErroGraph(3018, None, False), TipoErro.DEFINITIVO),
        (404, None, TipoErro.DEFINITIVO),
    ],
)
def test_classifica_erros_transitorios_e_definitivos(
    status_http: int, erro: ErroGraph | None, tipo: TipoErro
) -> None:
    assert classificar_erro(status_http, erro) is tipo


def test_le_codigos_do_erro_sem_a_mensagem() -> None:
    corpo = {
        "error": {
            "message": "Campanha Exemplo não encontrada",
            "type": "OAuthException",
            "code": 100,
            "error_subcode": 1487534,
            "is_transient": False,
            "error_user_title": "Número excessivo de linhas",
            "fbtrace_id": "AbCdEfGhIjKlMnOpQrStUv0",
        }
    }

    assert ler_erro_graph(corpo) == ErroGraph(100, 1487534, False)


@pytest.mark.parametrize(
    "corpo",
    [None, [], "texto", {"data": []}, {"error": "texto"}, {"error": []}],
)
def test_corpo_sem_erro_da_graph_nao_tem_erro(corpo: object) -> None:
    assert ler_erro_graph(corpo) is None


@pytest.mark.parametrize(
    ("campos", "esperado"),
    [
        ({"code": "4"}, ErroGraph(None, None, False)),
        ({"code": True, "error_subcode": 2.5}, ErroGraph(None, None, False)),
        ({"code": 17, "is_transient": "true"}, ErroGraph(17, None, False)),
    ],
)
def test_codigo_fora_do_tipo_inteiro_e_ignorado(
    campos: dict[str, object], esperado: ErroGraph
) -> None:
    assert ler_erro_graph({"error": campos}) == esperado


def test_le_o_maior_percentual_entre_os_tres_cabecalhos() -> None:
    cabecalhos = {
        "X-Business-Use-Case-Usage": montar_uso_negocio(call_count=12, total_time=31),
        "X-FB-Ads-Insights-Throttle": json.dumps(
            {"app_id_util_pct": 7.5, "acc_id_util_pct": 44, "ads_api_access_tier": "x"}
        ),
        "X-Ad-Account-Usage": json.dumps(
            {"acc_id_util_pct": 9, "reset_time_duration": 0}
        ),
    }

    assert ler_uso(cabecalhos) == UsoApi(percentual=44, espera_recuperacao_segundos=0)


def test_tempo_para_recuperar_o_acesso_vem_em_minutos_e_vira_segundos() -> None:
    cabecalhos = {
        "X-Business-Use-Case-Usage": montar_uso_negocio(
            call_count=100, estimated_time_to_regain_access=3
        ),
    }

    assert ler_uso(cabecalhos) == UsoApi(
        percentual=100, espera_recuperacao_segundos=180
    )


def test_reset_da_conta_vem_em_segundos() -> None:
    cabecalhos = {
        "X-Business-Use-Case-Usage": montar_uso_negocio(
            estimated_time_to_regain_access=1
        ),
        "X-Ad-Account-Usage": json.dumps(
            {"acc_id_util_pct": 100, "reset_time_duration": 240}
        ),
    }

    assert ler_uso(cabecalhos).espera_recuperacao_segundos == 240


def test_considera_todos_os_tipos_e_todas_as_bms_do_cabecalho() -> None:
    uso_negocio = {
        ID_BM_FICTICIO: [
            {"type": "ads_insights", "call_count": 5},
            {"type": "ads_management", "total_cputime": 61},
        ],
        "990000000000008": [{"type": "ads_insights", "total_time": 73}],
    }

    uso = ler_uso({"X-Business-Use-Case-Usage": json.dumps(uso_negocio)})

    assert uso.percentual == 73


@pytest.mark.parametrize(
    "valor",
    [
        "",
        "não é json",
        "[]",
        '{"x": 1}',
        '{"x": [1, "a"]}',
        '{"x": [{"call_count": "9"}]}',
    ],
)
def test_cabecalho_malformado_nao_derruba_a_leitura(valor: str) -> None:
    cabecalhos = {
        "X-Business-Use-Case-Usage": valor,
        "X-FB-Ads-Insights-Throttle": valor,
        "X-Ad-Account-Usage": valor,
    }

    assert ler_uso(cabecalhos) == SEM_USO


def test_sem_cabecalhos_nao_ha_uso() -> None:
    assert ler_uso({}) == SEM_USO


def test_backoff_dobra_a_cada_tentativa_ate_o_teto() -> None:
    tetos = [calcular_espera_backoff(tentativa, 1.0) for tentativa in range(1, 7)]

    assert tetos[0] == ESPERA_INICIAL_SEGUNDOS
    for anterior, seguinte in itertools.pairwise(tetos):
        assert seguinte == min(anterior * 2, ESPERA_MAXIMA_SEGUNDOS)
    assert tetos[-1] == ESPERA_MAXIMA_SEGUNDOS


@pytest.mark.parametrize("tentativa", range(1, 7))
def test_jitter_sorteia_entre_metade_e_o_teto(tentativa: int) -> None:
    teto = calcular_espera_backoff(tentativa, 1.0)

    assert calcular_espera_backoff(tentativa, 0.0) == teto / 2
    assert teto / 2 < calcular_espera_backoff(tentativa, 0.5) < teto


def test_soma_minima_das_esperas_passa_do_bloqueio_do_nivel_limited() -> None:
    """Mesmo com o menor sorteio, a última tentativa sai depois dos 300 s de
    bloqueio do nível de desenvolvimento (R-15)."""
    esperas = [calcular_espera_backoff(n, 0.0) for n in range(1, MAXIMO_TENTATIVAS)]

    assert sum(esperas) > 300


@pytest.mark.parametrize(
    "tipo", [TipoErro.LIMITE_TAXA, TipoErro.TRANSITORIO, TipoErro.TEMPO_ESGOTADO]
)
def test_tenta_de_novo_os_erros_retentaveis_ate_o_maximo(tipo: TipoErro) -> None:
    esperas = [decidir_espera(tipo, n, SEM_USO, 1.0) for n in range(1, 10)]

    assert esperas[: MAXIMO_TENTATIVAS - 1] == [
        calcular_espera_backoff(n, 1.0) for n in range(1, MAXIMO_TENTATIVAS)
    ]
    assert all(espera is None for espera in esperas[MAXIMO_TENTATIVAS - 1 :])


@pytest.mark.parametrize(
    "tipo",
    [
        TipoErro.EXCESSO_LINHAS,
        TipoErro.AUTENTICACAO,
        TipoErro.PERMISSAO,
        TipoErro.DEFINITIVO,
    ],
)
def test_nao_tenta_de_novo_os_erros_definitivos(tipo: TipoErro) -> None:
    assert decidir_espera(tipo, 1, SEM_USO, 1.0) is None


def test_limite_espera_o_tempo_de_recuperacao_dos_cabecalhos() -> None:
    uso = UsoApi(percentual=100, espera_recuperacao_segundos=ESPERA_MAXIMA_SEGUNDOS)

    espera = decidir_espera(TipoErro.LIMITE_TAXA, 1, uso, 0.0)

    assert espera == ESPERA_MAXIMA_SEGUNDOS


def test_limite_desiste_quando_a_recuperacao_passa_da_espera_maxima() -> None:
    """A Meta orienta parar de chamar e voltar depois: esperar um bloqueio
    longo só atrasaria as outras empresas da execução."""
    uso = UsoApi(percentual=100, espera_recuperacao_segundos=ESPERA_MAXIMA_SEGUNDOS + 1)

    assert decidir_espera(TipoErro.LIMITE_TAXA, 1, uso, 0.0) is None


def test_erro_transitorio_nao_usa_o_tempo_de_recuperacao() -> None:
    uso = UsoApi(percentual=100, espera_recuperacao_segundos=ESPERA_MAXIMA_SEGUNDOS)

    espera = decidir_espera(TipoErro.TRANSITORIO, 1, uso, 0.0)

    assert espera == calcular_espera_backoff(1, 0.0)


def test_sem_pausa_preventiva_abaixo_do_limite_de_uso() -> None:
    uso = UsoApi(percentual=LIMITE_USO_PERCENTUAL - 0.1, espera_recuperacao_segundos=60)

    assert calcular_pausa_preventiva(uso) == 0


@pytest.mark.parametrize(
    ("recuperacao", "pausa"),
    [
        (0, ESPERA_INICIAL_SEGUNDOS),
        (ESPERA_INICIAL_SEGUNDOS + 30, ESPERA_INICIAL_SEGUNDOS + 30),
        (ESPERA_MAXIMA_SEGUNDOS * 10, ESPERA_MAXIMA_SEGUNDOS),
    ],
)
def test_pausa_preventiva_a_partir_do_limite_de_uso(
    recuperacao: float, pausa: float
) -> None:
    uso = UsoApi(
        percentual=LIMITE_USO_PERCENTUAL, espera_recuperacao_segundos=recuperacao
    )

    assert calcular_pausa_preventiva(uso) == pausa
