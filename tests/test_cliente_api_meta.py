import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import requests
import responses
from responses import matchers
from responses.registries import OrderedRegistry

from etl.cliente_api_meta import (
    ClienteApiMeta,
    Endpoint,
    ErroApiMeta,
    ErroAutenticacao,
    ErroExcessoLinhas,
    ErroJobAssincrono,
    ErroLimiteTaxa,
    ErroPermissao,
    ErroRespostaInvalida,
    ErroTransitorio,
)
from etl.configuracao import (
    ESPERA_INICIAL_SEGUNDOS,
    INTERVALO_CONSULTA_RELATORIO_SEGUNDOS,
    MAXIMO_TENTATIVAS,
    TEMPO_MAXIMO_RELATORIO_SEGUNDOS,
    URL_BASE_API_META,
    VERSAO_API_META,
)
from etl.limites_api_meta import calcular_espera_backoff

PASTA_FIXTURES = Path(__file__).parent / "fixtures"
TOKEN = "EAAFicticio0000000000000000000000000000000000ZZ"
CONTA = "act_990000000000001"
PARAMETROS_INSIGHTS = {"level": "ad", "time_increment": "1", "limit": "2"}
SORTEIO = 0.5


class RelogioFalso:
    """Relógio e espera injetados: o teste não dorme, e cada espera avança
    o relógio."""

    def __init__(self) -> None:
        self.agora = 0.0
        self.esperas: list[float] = []

    def __call__(self) -> float:
        return self.agora

    def dormir(self, segundos: float) -> None:
        self.esperas.append(segundos)
        self.agora += segundos


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    """Toda resposta simulada é consumida na ordem em que foi registrada, e
    o teste falha se sobrar alguma ou se sair uma chamada não registrada."""
    with responses.RequestsMock(registry=OrderedRegistry) as mock:
        yield mock


@pytest.fixture
def relogio() -> RelogioFalso:
    return RelogioFalso()


@pytest.fixture
def cliente(relogio: RelogioFalso) -> ClienteApiMeta:
    return ClienteApiMeta(
        TOKEN, dormir=relogio.dormir, relogio=relogio, sortear=lambda: SORTEIO
    )


def montar_url(caminho: str) -> str:
    return f"{URL_BASE_API_META}/{VERSAO_API_META}/{caminho}"


def ler_fixture(nome: str) -> dict:
    return json.loads((PASTA_FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))


def simular(
    api: responses.RequestsMock,
    caminho: str,
    fixture: dict,
    metodo: str = responses.GET,
    **opcoes: object,
) -> None:
    api.add(
        metodo,
        montar_url(caminho),
        json=fixture["corpo"],
        status=fixture["status"],
        headers=fixture["cabecalhos"],
        **opcoes,
    )


def montar_erro(codigo: int, subcodigo: int | None = None, status: int = 400) -> dict:
    """Erro no formato da Graph API, sem cabeçalhos de uso."""
    erro = {
        "message": "Mensagem fictícia",
        "type": "OAuthException",
        "is_transient": False,
        "code": codigo,
        "fbtrace_id": "AbCdEfGhIjKlMnOpQrStUv3",
    }
    if subcodigo is not None:
        erro["error_subcode"] = subcodigo
    return {"status": status, "cabecalhos": {}, "corpo": {"error": erro}}


def test_pagina_pelo_cursor_ate_a_ultima_pagina(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    pagina_1 = ler_fixture("insights_anuncio_dia_pagina_1")
    pagina_2 = ler_fixture("insights_anuncio_dia_pagina_2")
    cursor = pagina_1["corpo"]["paging"]["cursors"]["after"]
    simular(
        api,
        f"{CONTA}/insights",
        pagina_1,
        match=[matchers.query_param_matcher(PARAMETROS_INSIGHTS)],
    )
    simular(
        api,
        f"{CONTA}/insights",
        pagina_2,
        match=[matchers.query_param_matcher({**PARAMETROS_INSIGHTS, "after": cursor})],
    )

    paginas = cliente.paginar(CONTA, Endpoint.INSIGHTS, PARAMETROS_INSIGHTS)

    assert paginas == [pagina_1["corpo"], pagina_2["corpo"]]


def test_envia_o_token_no_cabecalho_e_nunca_na_url(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    simular(
        api,
        CONTA,
        ler_fixture("insights_anuncio_dia_pagina_2"),
        match=[matchers.header_matcher({"Authorization": f"Bearer {TOKEN}"})],
    )

    cliente.obter(CONTA, Endpoint.OBJETO, {"fields": "name"})

    assert TOKEN not in api.calls[0].request.url
    assert "access_token" not in api.calls[0].request.url


def test_recusa_access_token_nos_parametros(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    with pytest.raises(ValueError, match="access_token") as erro:
        cliente.obter(CONTA, Endpoint.OBJETO, {"access_token": TOKEN})

    assert TOKEN not in str(erro.value)
    assert len(api.calls) == 0


def test_repr_do_cliente_nao_expoe_o_token(cliente: ClienteApiMeta) -> None:
    assert TOKEN not in repr(cliente)


@pytest.mark.parametrize("codigo", [4, 17, 613, *range(80000, 80015)])
def test_limite_espera_e_tenta_de_novo_ate_maximo_tentativas(
    api: responses.RequestsMock,
    cliente: ClienteApiMeta,
    relogio: RelogioFalso,
    codigo: int,
) -> None:
    """Critério de aceite do RF-08, na parte do cliente: esgotadas as
    tentativas, a falha sobe tipada, com o código, para quem registra a
    falha da empresa."""
    fixture = ler_fixture("erro_limite_taxa")
    fixture["corpo"]["error"]["code"] = codigo
    for _ in range(MAXIMO_TENTATIVAS):
        simular(api, f"{CONTA}/insights", fixture)

    with pytest.raises(ErroLimiteTaxa) as erro:
        cliente.paginar(CONTA, Endpoint.INSIGHTS, PARAMETROS_INSIGHTS)

    assert len(api.calls) == MAXIMO_TENTATIVAS
    assert erro.value.tentativas == MAXIMO_TENTATIVAS
    assert erro.value.codigo == codigo
    assert erro.value.subcodigo == 2446079
    # A fixture informa 1 minuto até a recuperação do acesso.
    assert relogio.esperas == [
        max(calcular_espera_backoff(n, SORTEIO), 60)
        for n in range(1, MAXIMO_TENTATIVAS)
    ]


def test_limite_seguido_de_sucesso_devolve_a_resposta(
    api: responses.RequestsMock, cliente: ClienteApiMeta, relogio: RelogioFalso
) -> None:
    pagina = ler_fixture("insights_anuncio_dia_pagina_2")
    simular(api, f"{CONTA}/insights", ler_fixture("erro_limite_taxa"))
    simular(api, f"{CONTA}/insights", pagina)

    paginas = cliente.paginar(CONTA, Endpoint.INSIGHTS, PARAMETROS_INSIGHTS)

    assert paginas == [pagina["corpo"]]
    assert relogio.esperas == [max(calcular_espera_backoff(1, SORTEIO), 60)]


def test_limite_espera_o_tempo_de_recuperacao_do_cabecalho(
    api: responses.RequestsMock, cliente: ClienteApiMeta, relogio: RelogioFalso
) -> None:
    fixture = ler_fixture("erro_limite_taxa")
    fixture["cabecalhos"] = {
        "X-Ad-Account-Usage": json.dumps(
            {"acc_id_util_pct": 100, "reset_time_duration": 290}
        )
    }
    simular(api, f"{CONTA}/insights", fixture)
    simular(api, f"{CONTA}/insights", ler_fixture("insights_anuncio_dia_pagina_2"))

    cliente.paginar(CONTA, Endpoint.INSIGHTS, PARAMETROS_INSIGHTS)

    assert relogio.esperas == [290]


def test_limite_com_recuperacao_longa_desiste_sem_esperar(
    api: responses.RequestsMock, cliente: ClienteApiMeta, relogio: RelogioFalso
) -> None:
    fixture = ler_fixture("erro_limite_taxa")
    uso = json.loads(fixture["cabecalhos"]["X-Business-Use-Case-Usage"])
    uso["990000000000009"][0]["estimated_time_to_regain_access"] = 45
    fixture["cabecalhos"]["X-Business-Use-Case-Usage"] = json.dumps(uso)
    simular(api, f"{CONTA}/insights", fixture)

    with pytest.raises(ErroLimiteTaxa) as erro:
        cliente.paginar(CONTA, Endpoint.INSIGHTS, PARAMETROS_INSIGHTS)

    assert erro.value.tentativas == 1
    assert relogio.esperas == []


@pytest.mark.parametrize(
    "opcoes",
    [
        {"json": montar_erro(2, status=500)["corpo"], "status": 500},
        {"json": montar_erro(1, 99, status=500)["corpo"], "status": 500},
        {"body": "<html>Bad Gateway</html>", "status": 502},
        {"body": requests.ConnectionError("conexão recusada")},
        {"body": requests.ReadTimeout("tempo esgotado")},
    ],
    ids=["codigo-2", "codigo-1", "502-sem-json", "conexao", "tempo"],
)
def test_erro_transitorio_e_repetido_com_backoff(
    api: responses.RequestsMock,
    cliente: ClienteApiMeta,
    relogio: RelogioFalso,
    opcoes: dict[str, object],
) -> None:
    pagina = ler_fixture("insights_anuncio_dia_pagina_2")
    api.add(responses.GET, montar_url(CONTA), **opcoes)
    api.add(responses.GET, montar_url(CONTA), **opcoes)
    simular(api, CONTA, pagina)

    assert cliente.obter(CONTA, Endpoint.OBJETO, {}) == pagina["corpo"]
    assert relogio.esperas == [
        calcular_espera_backoff(1, SORTEIO),
        calcular_espera_backoff(2, SORTEIO),
    ]


def test_erro_transitorio_esgota_as_tentativas(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    for _ in range(MAXIMO_TENTATIVAS):
        api.add(responses.GET, montar_url(CONTA), body=requests.ConnectionError())

    with pytest.raises(ErroTransitorio) as erro:
        cliente.obter(CONTA, Endpoint.OBJETO, {})

    assert erro.value.tentativas == MAXIMO_TENTATIVAS
    assert erro.value.codigo is None


@pytest.mark.parametrize(
    ("fixture", "excecao"),
    [
        (montar_erro(190, 463, status=401), ErroAutenticacao),
        (montar_erro(10, status=403), ErroPermissao),
        (montar_erro(100, 33), ErroApiMeta),
    ],
)
def test_erro_definitivo_vira_excecao_tipada_sem_nova_tentativa(
    api: responses.RequestsMock,
    cliente: ClienteApiMeta,
    relogio: RelogioFalso,
    fixture: dict,
    excecao: type[ErroApiMeta],
) -> None:
    simular(api, CONTA, fixture)

    with pytest.raises(excecao) as erro:
        cliente.obter(CONTA, Endpoint.OBJETO, {})

    assert type(erro.value) is excecao
    assert erro.value.codigo == fixture["corpo"]["error"]["code"]
    assert erro.value.subcodigo == fixture["corpo"]["error"].get("error_subcode")
    assert erro.value.tentativas == 1
    assert relogio.esperas == []


def test_erro_http_sem_json_e_definitivo(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    api.add(responses.GET, montar_url(CONTA), body="não encontrado", status=404)

    with pytest.raises(ErroApiMeta) as erro:
        cliente.obter(CONTA, Endpoint.OBJETO, {})

    assert type(erro.value) is ErroApiMeta
    assert erro.value.codigo is None


def test_excecao_nao_expoe_mensagem_da_meta_nem_ids(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    """Os logs do Actions são públicos (RNF-17): a exceção leva só os
    códigos, nunca a mensagem, a URL ou o ID da conta."""
    fixture = ler_fixture("erro_excesso_linhas")
    fixture["corpo"]["error"]["error_subcode"] = 33
    simular(api, f"{CONTA}/insights", fixture)

    with pytest.raises(ErroApiMeta) as erro:
        cliente.paginar(CONTA, Endpoint.INSIGHTS, PARAMETROS_INSIGHTS)

    texto = str(erro.value) + repr(erro.value)
    assert "100" in texto
    for trecho in (
        "990000000000001",
        "Empresa Exemplo",
        "Número excessivo",
        "reduce the amount",
        "AbCdEfGhIjKlMnOpQrStUv2",
    ):
        assert trecho not in texto


def listar_cadeia(erro: BaseException) -> list[BaseException]:
    cadeia: list[BaseException] = []
    atual: BaseException | None = erro
    while atual is not None and atual not in cadeia:
        cadeia.append(atual)
        atual = atual.__cause__ or atual.__context__
    return cadeia


@pytest.mark.parametrize(
    "falha",
    [requests.ConnectionError, requests.ReadTimeout],
    ids=["conexao", "tempo"],
)
def test_falha_de_rede_nao_guarda_a_url_na_cadeia_da_excecao(
    api: responses.RequestsMock,
    cliente: ClienteApiMeta,
    falha: type[requests.RequestException],
) -> None:
    """A exceção do requests traz a URL, com o ID da conta: nenhum elo da
    cadeia que chega a quem chamou pode guardá-la, nem para um formatador
    que percorra __context__."""
    for _ in range(MAXIMO_TENTATIVAS):
        api.add(
            responses.GET,
            montar_url(CONTA),
            body=falha(f"falhou em {montar_url(CONTA)}"),
        )

    with pytest.raises(ErroTransitorio) as erro:
        cliente.obter(CONTA, Endpoint.OBJETO, {})

    for elo in listar_cadeia(erro.value):
        assert not isinstance(elo, requests.RequestException)
        assert "990000000000001" not in str(elo) + repr(elo)


def test_uso_alto_pausa_antes_da_chamada_seguinte(
    api: responses.RequestsMock, cliente: ClienteApiMeta, relogio: RelogioFalso
) -> None:
    pagina_1 = ler_fixture("insights_anuncio_dia_pagina_1")
    pagina_1["cabecalhos"]["X-FB-Ads-Insights-Throttle"] = json.dumps(
        {"app_id_util_pct": 4, "acc_id_util_pct": 95}
    )
    simular(api, f"{CONTA}/insights", pagina_1)
    simular(api, f"{CONTA}/insights", ler_fixture("insights_anuncio_dia_pagina_2"))
    simular(api, CONTA, ler_fixture("insights_anuncio_dia_pagina_2"))

    cliente.paginar(CONTA, Endpoint.INSIGHTS, PARAMETROS_INSIGHTS)
    cliente.obter(CONTA, Endpoint.OBJETO, {})

    assert relogio.esperas == [ESPERA_INICIAL_SEGUNDOS]


@pytest.mark.parametrize(
    "opcoes",
    [
        {"body": "<html></html>", "status": 200},
        {"json": [1, 2], "status": 200},
    ],
)
def test_resposta_de_sucesso_sem_objeto_json_e_invalida(
    api: responses.RequestsMock,
    cliente: ClienteApiMeta,
    opcoes: dict[str, object],
) -> None:
    api.add(responses.GET, montar_url(CONTA), **opcoes)

    with pytest.raises(ErroRespostaInvalida):
        cliente.obter(CONTA, Endpoint.OBJETO, {})


def test_pagina_seguinte_sem_cursor_e_resposta_invalida(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    pagina = ler_fixture("insights_anuncio_dia_pagina_1")
    del pagina["corpo"]["paging"]["cursors"]
    simular(api, f"{CONTA}/insights", pagina)

    with pytest.raises(ErroRespostaInvalida):
        cliente.paginar(CONTA, Endpoint.INSIGHTS, PARAMETROS_INSIGHTS)


def test_lista_de_endpoints_nao_contem_endpoints_de_leads() -> None:
    """Critério de aceite do RNF-24: a ETL não chama endpoints de leads."""
    assert {endpoint.value for endpoint in Endpoint} == {
        "",
        "campaigns",
        "adsets",
        "ads",
        "adcreatives",
        "insights",
    }
    for endpoint in Endpoint:
        assert "lead" not in endpoint.value


@pytest.mark.parametrize("aresta", ["leads", "leadgen_forms", "ads/leads", "Ads"])
def test_recusa_endpoint_fora_da_lista_sem_chamar_a_api(
    api: responses.RequestsMock, cliente: ClienteApiMeta, aresta: str
) -> None:
    with pytest.raises(TypeError, match="endpoint"):
        cliente.paginar("990000000000301", aresta, {})  # type: ignore[arg-type]

    assert len(api.calls) == 0


@pytest.mark.parametrize(
    "campos",
    [
        "id,leads",
        "id,leads{field_data}",
        "name,leadgen_forms.limit(10){id}",
        "creative{id},leadgen_forms",
        " Leads ",
    ],
)
def test_recusa_expansao_de_campo_para_leads_sem_chamar_a_api(
    api: responses.RequestsMock, cliente: ClienteApiMeta, campos: str
) -> None:
    """RNF-24: a expansão de campo leria a aresta de leads por um endpoint
    da lista."""
    with pytest.raises(ValueError, match="fields"):
        cliente.paginar(CONTA, Endpoint.ANUNCIOS, {"fields": campos})

    assert len(api.calls) == 0


def test_aceita_campos_sem_aresta_de_leads(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    """O tipo de ação lead é métrica agregada (R-21), não a aresta de leads."""
    pagina = ler_fixture("insights_anuncio_dia_pagina_2")
    parametros = {
        "fields": "ad_id,spend,actions,cost_per_action_type",
        "filtering": '[{"field":"action_type","operator":"IN","value":["lead"]}]',
    }
    simular(api, f"{CONTA}/insights", pagina)

    assert cliente.paginar(CONTA, Endpoint.INSIGHTS, parametros) == [pagina["corpo"]]


@pytest.mark.parametrize(
    "objeto_id",
    [
        "990000000000301/leads",
        "act_990000000000001/leadgen_forms",
        "../me",
        "990000000000301?fields=leads",
        "",
        "act_",
        "nome",
        "٩٩٠",
        990000000000301,
    ],
)
def test_recusa_objeto_fora_do_formato_de_id_da_meta(
    api: responses.RequestsMock, cliente: ClienteApiMeta, objeto_id: object
) -> None:
    """Um caminho no ID escaparia da lista de endpoints."""
    with pytest.raises((TypeError, ValueError), match="objeto_id") as erro:
        cliente.obter(objeto_id, Endpoint.OBJETO, {})  # type: ignore[arg-type]

    assert "990000000000" not in str(erro.value)
    assert len(api.calls) == 0


@pytest.mark.parametrize(
    "objeto_id", ["act_990000000000001", "990000000000301", "990000000000401_123"]
)
def test_aceita_ids_de_conta_objeto_e_publicacao(
    api: responses.RequestsMock, cliente: ClienteApiMeta, objeto_id: str
) -> None:
    pagina = ler_fixture("insights_anuncio_dia_pagina_2")
    simular(api, objeto_id, pagina)

    assert cliente.obter(objeto_id, Endpoint.OBJETO, {}) == pagina["corpo"]


RELATORIO = "990000000000777"
CAMPOS_ESTADO_RELATORIO = {
    "fields": "async_status,async_percent_completion,error_code,error_subcode"
}


def simular_job_ate_concluir(api: responses.RequestsMock) -> list[dict]:
    """Criação, uma consulta em andamento, a conclusão e o resultado em duas
    páginas. Devolve os corpos das páginas do resultado."""
    pagina_1 = ler_fixture("insights_anuncio_dia_pagina_1")
    pagina_2 = ler_fixture("insights_anuncio_dia_pagina_2")
    simular(
        api,
        f"{CONTA}/insights",
        ler_fixture("relatorio_assincrono_criado"),
        metodo=responses.POST,
        match=[
            matchers.urlencoded_params_matcher(PARAMETROS_INSIGHTS),
            matchers.header_matcher({"Authorization": f"Bearer {TOKEN}"}),
        ],
    )
    estado = [matchers.query_param_matcher(CAMPOS_ESTADO_RELATORIO)]
    simular(
        api, RELATORIO, ler_fixture("relatorio_assincrono_em_execucao"), match=estado
    )
    simular(api, RELATORIO, ler_fixture("relatorio_assincrono_concluido"), match=estado)
    cursor = pagina_1["corpo"]["paging"]["cursors"]["after"]
    simular(
        api,
        f"{RELATORIO}/insights",
        pagina_1,
        match=[matchers.query_param_matcher({"limit": "2"})],
    )
    simular(
        api,
        f"{RELATORIO}/insights",
        pagina_2,
        match=[matchers.query_param_matcher({"limit": "2", "after": cursor})],
    )
    return [pagina_1["corpo"], pagina_2["corpo"]]


def test_fluxo_assincrono_ate_job_completed(
    api: responses.RequestsMock, cliente: ClienteApiMeta, relogio: RelogioFalso
) -> None:
    """Critério de aceite da #17: criação do job, consulta do report_run_id
    até Job Completed e leitura do resultado."""
    esperado = simular_job_ate_concluir(api)

    paginas = cliente.executar_relatorio_assincrono(CONTA, PARAMETROS_INSIGHTS)

    assert paginas == esperado
    assert relogio.esperas == [INTERVALO_CONSULTA_RELATORIO_SEGUNDOS]
    assert "access_token" not in str(api.calls[0].request.body)


def test_excesso_de_linhas_na_consulta_sincrona_refaz_por_job_assincrono(
    api: responses.RequestsMock, cliente: ClienteApiMeta, relogio: RelogioFalso
) -> None:
    """Critério de aceite do RF-08: o excesso de linhas (100/1487534) refaz a
    mesma consulta por job assíncrono, sem tentar de novo a síncrona."""
    simular(api, f"{CONTA}/insights", ler_fixture("erro_excesso_linhas"))
    esperado = simular_job_ate_concluir(api)

    paginas = cliente.ler_insights(CONTA, PARAMETROS_INSIGHTS)

    assert paginas == esperado
    assert relogio.esperas == [INTERVALO_CONSULTA_RELATORIO_SEGUNDOS]


def test_excesso_de_linhas_na_segunda_pagina_descarta_a_primeira(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    simular(api, f"{CONTA}/insights", ler_fixture("insights_anuncio_dia_pagina_1"))
    simular(api, f"{CONTA}/insights", ler_fixture("erro_excesso_linhas"))
    esperado = simular_job_ate_concluir(api)

    assert cliente.ler_insights(CONTA, PARAMETROS_INSIGHTS) == esperado


def test_tempo_esgotado_na_consulta_sincrona_refaz_por_job_assincrono(
    api: responses.RequestsMock, cliente: ClienteApiMeta, relogio: RelogioFalso
) -> None:
    api.add(
        responses.GET,
        montar_url(f"{CONTA}/insights"),
        body=requests.ReadTimeout("tempo esgotado"),
    )
    esperado = simular_job_ate_concluir(api)

    assert cliente.ler_insights(CONTA, PARAMETROS_INSIGHTS) == esperado
    assert relogio.esperas == [INTERVALO_CONSULTA_RELATORIO_SEGUNDOS]


def test_consulta_sincrona_bem_sucedida_nao_cria_job(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    pagina = ler_fixture("insights_anuncio_dia_pagina_2")
    simular(api, f"{CONTA}/insights", pagina)

    assert cliente.ler_insights(CONTA, PARAMETROS_INSIGHTS) == [pagina["corpo"]]


def test_falha_de_conexao_na_sincrona_nao_vira_job(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    for _ in range(MAXIMO_TENTATIVAS):
        api.add(
            responses.GET,
            montar_url(f"{CONTA}/insights"),
            body=requests.ConnectionError(),
        )

    with pytest.raises(ErroTransitorio) as erro:
        cliente.ler_insights(CONTA, PARAMETROS_INSIGHTS)

    assert type(erro.value) is ErroTransitorio


def test_job_que_falha_por_excesso_de_linhas_sobe_para_fatiar(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    """Se nem o job dá conta, quem chamou fatia o intervalo (R-39)."""
    simular(api, f"{CONTA}/insights", ler_fixture("erro_excesso_linhas"))
    simular(
        api,
        f"{CONTA}/insights",
        ler_fixture("relatorio_assincrono_criado"),
        metodo=responses.POST,
    )
    simular(api, RELATORIO, ler_fixture("relatorio_assincrono_falhou"))

    with pytest.raises(ErroExcessoLinhas) as erro:
        cliente.ler_insights(CONTA, PARAMETROS_INSIGHTS)

    assert (erro.value.codigo, erro.value.subcodigo) == (100, 1487534)


@pytest.mark.parametrize(
    ("status", "codigo", "subcodigo"),
    [("Job Failed", 1, None), ("Job Failed", None, None), ("Job Skipped", None, None)],
)
def test_job_falho_ou_expirado_vira_erro_tipado(
    api: responses.RequestsMock,
    cliente: ClienteApiMeta,
    status: str,
    codigo: int | None,
    subcodigo: int | None,
) -> None:
    falhou = ler_fixture("relatorio_assincrono_falhou")
    falhou["corpo"].update(async_status=status)
    for campo, valor in (("error_code", codigo), ("error_subcode", subcodigo)):
        if valor is None:
            del falhou["corpo"][campo]
        else:
            falhou["corpo"][campo] = valor
    simular(
        api,
        f"{CONTA}/insights",
        ler_fixture("relatorio_assincrono_criado"),
        metodo=responses.POST,
    )
    simular(api, RELATORIO, falhou)

    with pytest.raises(ErroJobAssincrono) as erro:
        cliente.executar_relatorio_assincrono(CONTA, PARAMETROS_INSIGHTS)

    assert (erro.value.codigo, erro.value.subcodigo) == (codigo, subcodigo)


def test_job_concluido_abaixo_de_100_por_cento_segue_consultando(
    api: responses.RequestsMock, cliente: ClienteApiMeta
) -> None:
    quase = ler_fixture("relatorio_assincrono_concluido")
    quase["corpo"]["async_percent_completion"] = 99
    pagina = ler_fixture("insights_anuncio_dia_pagina_2")
    simular(
        api,
        f"{CONTA}/insights",
        ler_fixture("relatorio_assincrono_criado"),
        metodo=responses.POST,
    )
    simular(api, RELATORIO, quase)
    simular(api, RELATORIO, ler_fixture("relatorio_assincrono_concluido"))
    simular(api, f"{RELATORIO}/insights", pagina)

    paginas = cliente.executar_relatorio_assincrono(CONTA, PARAMETROS_INSIGHTS)

    assert paginas == [pagina["corpo"]]


def test_job_sem_conclusao_desiste_no_tempo_maximo(
    api: responses.RequestsMock, cliente: ClienteApiMeta, relogio: RelogioFalso
) -> None:
    """Um job pode levar até 1 h (R-18); depois disso, a falha é da empresa."""
    simular(
        api,
        f"{CONTA}/insights",
        ler_fixture("relatorio_assincrono_criado"),
        metodo=responses.POST,
    )
    consultas = TEMPO_MAXIMO_RELATORIO_SEGUNDOS // INTERVALO_CONSULTA_RELATORIO_SEGUNDOS
    for _ in range(consultas + 1):
        simular(api, RELATORIO, ler_fixture("relatorio_assincrono_em_execucao"))

    with pytest.raises(ErroJobAssincrono):
        cliente.executar_relatorio_assincrono(CONTA, PARAMETROS_INSIGHTS)

    assert relogio.agora == TEMPO_MAXIMO_RELATORIO_SEGUNDOS


@pytest.mark.parametrize(
    "criacao", [{}, {"report_run_id": ""}, {"report_run_id": "1/leads"}, {"id": 1}]
)
def test_criacao_sem_report_run_id_valido_e_resposta_invalida(
    api: responses.RequestsMock, cliente: ClienteApiMeta, criacao: dict
) -> None:
    api.add(responses.POST, montar_url(f"{CONTA}/insights"), json=criacao)

    with pytest.raises(ErroRespostaInvalida):
        cliente.executar_relatorio_assincrono(CONTA, PARAMETROS_INSIGHTS)
