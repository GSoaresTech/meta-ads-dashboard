"""Prova, contra o banco local e com a API simulada pelas fixtures, a rotina
horária de ponta a ponta, pela execução por empresa: os dados de hoje e de
ontem iguais aos da API (RF-06), só os insights e as quebras desses dois dias
e os objetos com entrega neles relidos pelo ID, sem o cadastro completo nem o
alcance (ADR-0017), a janela no fuso da conta e a transação única por empresa
(RF-18). O cadastro vem antes, como a carga inicial o deixa. Exige o banco
local de pé.

Os dois dias são os das fixtures de insights e de quebras, 01 e 02/10/2026.
Os objetos relidos pelo ID respondem como no cadastro: a Meta devolve pelo ID
os mesmos campos que pela aresta.
"""

from collections import defaultdict
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import partial
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
import responses
from responses.registries import OrderedRegistry

from etl import rotina_horaria
from etl.cadastro import TarefaCadastro
from etl.carga_historica import TIPO_HISTORICA
from etl.cliente_api_meta import ClienteApiMeta
from etl.configuracao import VERSAO_API_META, Ambiente
from etl.execucao import CODIGO_SAIDA_SUCESSO, StatusExecucao, executar_empresa
from etl.extracao import agora_utc, montar_campos
from etl.mapa_campos import ObjetoApi
from etl.rotina_horaria import TIPO_HORARIA, TarefaRotinaHoraria
from tests import cadastro_exemplo
from tests.cadastro_exemplo import ID_META_CONTA
from tests.carga_exemplo import ler_estado
from tests.conftest import LIMPEZA_EMPRESA, URL_BANCO_LOCAL, EmpresaTeste, criar_empresa
from tests.insights_exemplo import (
    FIM,
    ID_META_ANUNCIO_AUSENTE,
    INICIO,
    NOMES_ENTIDADES,
    NOMES_PAGINAS,
    montar_parametros_insights,
    simular,
    simular_insights,
)
from tests.insights_exemplo import ler_fixtures as ler_fixtures_insights
from tests.insights_exemplo import listar_linhas as listar_linhas_insights
from tests.quebras_exemplo import (
    ID_META_CAMPANHA_AUSENTE,
    QUEBRAS,
    montar_parametros_quebra,
    simular_quebras,
)
from tests.quebras_exemplo import ler_fixtures as ler_fixtures_quebras
from tests.rotina_diaria_exemplo import RESPOSTA_VAZIA

pytestmark = pytest.mark.integracao

NOME_EMPRESA = "Empresa Exemplo Horaria"
TOKEN = "EAAFicticio0000000000000000000000000000000000ZZ"
# A conexão do ponto de entrada não passa pelo SET ROLE de conectar_etl.
URL_BANCO_ETL = f"{URL_BANCO_LOCAL}?options=-crole%3Detl_carga"
FUSO_BRASILIA = "America/Sao_Paulo"
# 02:17 UTC de 03/10 são 23:17 de 02/10 em Brasília, o fuso da conta das
# fixtures: hoje é 02/10, e não o dia em UTC.
INSTANTE: datetime = datetime(2026, 10, 3, 2, 17, tzinfo=UTC)
CADASTRO_EM: datetime = datetime(2026, 10, 1, 6, 43, tzinfo=UTC)
RETENCAO_DIAS = 35
ID_META_ANUNCIO_SEM_ENTREGA = "995000000000000019"
ID_META_CONJUNTO_SEM_ENTREGA = "995000000000000008"
ID_META_CAMPANHA_SEM_ENTREGA = "995000000000000004"
ID_META_CAMPANHA_RENOMEADA = "995000000000000002"
ID_META_CONJUNTO_NOVA_META = "995000000000000006"
ID_META_ANUNCIO_RENOMEADO = "995000000000000010"
NOMES_CADASTRO_OBJETOS = (
    "cadastro_campanhas",
    "cadastro_conjuntos",
    "cadastro_anuncios_pagina_1",
    "cadastro_anuncios_pagina_2",
)

LER_METRICAS = """
SELECT anuncio.id_meta, metrica.data, metrica.investimento, metrica.impressoes,
       metrica.alcance
FROM normalizado.metrica_diaria_anuncio AS metrica
JOIN normalizado.anuncio AS anuncio
  ON anuncio.empresa_id = metrica.empresa_id AND anuncio.id = metrica.anuncio_id
WHERE metrica.empresa_id = %s AND metrica.data BETWEEN %s AND %s
"""

LER_ACOES = """
SELECT anuncio.id_meta, acao.data, acao.tipo_acao, acao.quantidade
FROM normalizado.acao_diaria_anuncio AS acao
JOIN normalizado.anuncio AS anuncio
  ON anuncio.empresa_id = acao.empresa_id AND anuncio.id = acao.anuncio_id
WHERE acao.empresa_id = %s AND acao.data BETWEEN %s AND %s
"""

# O investimento das quebras por campanha, dia e tipo: a categoria e a
# subcategoria saem da transformação, e a soma não depende delas.
LER_INVESTIMENTO_QUEBRAS = """
SELECT campanha.id_meta, quebra.data, quebra.tipo_quebra, sum(quebra.investimento)
FROM normalizado.quebra_diaria_campanha AS quebra
JOIN normalizado.campanha AS campanha
  ON campanha.empresa_id = quebra.empresa_id AND campanha.id = quebra.campanha_id
WHERE quebra.empresa_id = %s AND quebra.data BETWEEN %s AND %s
GROUP BY 1, 2, 3
"""

LER_EXECUCOES = """
SELECT tipo, status FROM normalizado.execucao_carga
WHERE empresa_id = %s ORDER BY iniciado_em
"""

type Objetos = dict[str, dict]
type Linhas = set[tuple]


def apagar_empresa_horaria(conexao: psycopg.Connection) -> None:
    for (empresa_id,) in conexao.execute(
        "SELECT id FROM normalizado.empresa WHERE nome = %s", (NOME_EMPRESA,)
    ).fetchall():
        with conexao.transaction():
            for comando in LIMPEZA_EMPRESA:
                conexao.execute(comando, {"empresa_id": empresa_id})


@pytest.fixture
def empresa(conexao_operador: psycopg.Connection) -> Iterator[EmpresaTeste]:
    apagar_empresa_horaria(conexao_operador)
    criada = criar_empresa(conexao_operador, NOME_EMPRESA, ID_META_CONTA, indice=1)
    try:
        yield criada
    finally:
        apagar_empresa_horaria(conexao_operador)


def carregar_cadastro(
    conectar: Callable[[], psycopg.Connection], empresa_id: UUID
) -> None:
    """O cadastro completo da conta das fixtures, como a carga inicial o deixa:
    com o fuso de Brasília e as entidades não excluídas (ADR-0017)."""
    with responses.RequestsMock(registry=OrderedRegistry) as api:
        cadastro_exemplo.simular_cadastro(api, cadastro_exemplo.ler_fixtures())
        cliente = ClienteApiMeta(TOKEN, dormir=lambda segundos: None)
        tarefa = TarefaCadastro(conectar, cliente, relogio=lambda: CADASTRO_EM)
        status = executar_empresa(conectar, empresa_id, TIPO_HISTORICA, tarefa)
    assert status is StatusExecucao.SUCESSO


def montar_objetos_por_id() -> Objetos:
    """A resposta da leitura pelo ID de cada objeto das fixtures: os do
    cadastro e o anúncio excluído, com o conjunto e a campanha dele."""
    cadastro = cadastro_exemplo.ler_fixtures()
    objetos = {
        objeto["id"]: {"status": 200, "cabecalhos": {}, "corpo": objeto}
        for nome in NOMES_CADASTRO_OBJETOS
        for objeto in cadastro[nome]["corpo"]["data"]
    }
    entidades = ler_fixtures_insights()
    objetos.update(
        {entidades[nome]["corpo"]["id"]: entidades[nome] for nome, _ in NOMES_ENTIDADES}
    )
    return objetos


def listar_releituras(
    insights: dict[str, dict], objetos: Objetos
) -> list[tuple[str, ObjetoApi]]:
    """Os objetos que a horária relê pelo ID, na ordem: os anúncios dos
    insights, depois o conjunto de cada um e a campanha de cada conjunto,
    cada um uma vez."""
    anuncios = list(
        dict.fromkeys(linha["ad_id"] for linha in listar_linhas_insights(insights))
    )
    conjuntos = list(
        dict.fromkeys(objetos[anuncio]["corpo"]["adset_id"] for anuncio in anuncios)
    )
    campanhas = list(
        dict.fromkeys(
            objetos[conjunto]["corpo"]["campaign_id"] for conjunto in conjuntos
        )
    )
    return [
        *((id_meta, ObjetoApi.ANUNCIO) for id_meta in anuncios),
        *((id_meta, ObjetoApi.CONJUNTO) for id_meta in conjuntos),
        *((id_meta, ObjetoApi.CAMPANHA) for id_meta in campanhas),
    ]


def simular_horaria(
    api: responses.RequestsMock,
    insights: dict[str, dict],
    quebras: dict[str, dict],
    objetos: Objetos,
) -> None:
    """Registra, na ordem da extração, os insights e as três quebras de 01 e
    02/10 e a leitura pelo ID de cada objeto com entrega."""
    simular_insights(api, insights, com_entidades=False)
    simular_quebras(api, quebras, com_campanha=False)
    for id_meta, objeto in listar_releituras(insights, objetos):
        simular(api, id_meta, objetos[id_meta], {"fields": montar_campos(objeto)})


def executar_horaria(
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    simular_api: Callable[[responses.RequestsMock], None],
    instante: datetime = INSTANTE,
) -> tuple[StatusExecucao, list[str]]:
    """Uma execução com a API simulada e a URL de cada chamada, na ordem.
    Uma chamada não simulada falha a execução, e uma simulada sem chamada
    falha o teste."""
    with responses.RequestsMock(registry=OrderedRegistry) as api:
        simular_api(api)
        cliente = ClienteApiMeta(TOKEN, dormir=lambda segundos: None)
        tarefa = TarefaRotinaHoraria(conectar, cliente, relogio=lambda: instante)
        status = executar_empresa(conectar, empresa_id, TIPO_HORARIA, tarefa)
        return status, [chamada.request.url for chamada in api.calls]


def executar_com_fixtures(
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    insights: dict[str, dict] | None = None,
    quebras: dict[str, dict] | None = None,
    objetos: Objetos | None = None,
) -> tuple[StatusExecucao, list[str]]:
    insights = ler_fixtures_insights() if insights is None else insights
    quebras = ler_fixtures_quebras() if quebras is None else quebras
    objetos = montar_objetos_por_id() if objetos is None else objetos
    return executar_horaria(
        conectar,
        empresa_id,
        lambda api: simular_horaria(api, insights, quebras, objetos),
    )


def listar_linhas_quebras(quebras: dict[str, dict]) -> list[tuple[str, dict]]:
    return [
        (tipo, linha)
        for tipo, _, nome in QUEBRAS
        for linha in quebras[nome]["corpo"]["data"]
    ]


def revisar_dados(insights: dict[str, dict], quebras: dict[str, dict]) -> None:
    """Como a Meta entrega o dia que avança e revisa o anterior: hoje mais
    investimento e impressões em cada linha, e ontem uma ação a menos."""
    for linha in listar_linhas_insights(insights) + [
        linha for _, linha in listar_linhas_quebras(quebras)
    ]:
        if linha["date_start"] == FIM.isoformat():
            linha["spend"] = str(Decimal(linha["spend"]) + Decimal("7.25"))
            linha["impressions"] = str(int(linha["impressions"]) + 300)
    linha_ontem = next(
        linha
        for linha in listar_linhas_insights(insights)
        if linha["date_start"] == INICIO.isoformat() and len(linha["actions"]) > 1
    )
    linha_ontem["actions"].pop()


def montar_metricas_api(insights: dict[str, dict]) -> Linhas:
    return {
        (
            linha["ad_id"],
            date.fromisoformat(linha["date_start"]),
            Decimal(linha["spend"]),
            int(linha["impressions"]),
            int(linha["reach"]),
        )
        for linha in listar_linhas_insights(insights)
    }


def montar_acoes_api(insights: dict[str, dict]) -> Linhas:
    return {
        (
            linha["ad_id"],
            date.fromisoformat(linha["date_start"]),
            acao["action_type"],
            int(acao["value"]),
        )
        for linha in listar_linhas_insights(insights)
        for acao in linha["actions"]
    }


def montar_investimento_quebras_api(quebras: dict[str, dict]) -> Linhas:
    somas: defaultdict[tuple[str, date, str], Decimal] = defaultdict(Decimal)
    for tipo, linha in listar_linhas_quebras(quebras):
        chave = (linha["campaign_id"], date.fromisoformat(linha["date_start"]), tipo)
        somas[chave] += Decimal(linha["spend"])
    return {(*chave, soma) for chave, soma in somas.items()}


def ler_linhas(conexao: psycopg.Connection, consulta: str, empresa_id: UUID) -> Linhas:
    return set(conexao.execute(consulta, (empresa_id, INICIO, FIM)).fetchall())


def test_dados_de_hoje_e_ontem_ficam_iguais_aos_da_api(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # O critério do RF-06: depois de uma execução horária, hoje e ontem ficam
    # no banco como a API os devolveu, inclusive o que mudou desde a anterior.
    carregar_cadastro(conectar_etl, empresa.empresa_id)
    status, _ = executar_com_fixtures(conectar_etl, empresa.empresa_id)
    assert status is StatusExecucao.SUCESSO
    insights, quebras = ler_fixtures_insights(), ler_fixtures_quebras()
    revisar_dados(insights, quebras)
    assert ler_linhas(conexao_operador, LER_METRICAS, empresa.empresa_id) != (
        montar_metricas_api(insights)
    )

    status, _ = executar_com_fixtures(
        conectar_etl, empresa.empresa_id, insights, quebras
    )

    assert status is StatusExecucao.SUCESSO
    assert ler_linhas(
        conexao_operador, LER_METRICAS, empresa.empresa_id
    ) == montar_metricas_api(insights)
    assert ler_linhas(
        conexao_operador, LER_ACOES, empresa.empresa_id
    ) == montar_acoes_api(insights)
    assert ler_linhas(
        conexao_operador, LER_INVESTIMENTO_QUEBRAS, empresa.empresa_id
    ) == montar_investimento_quebras_api(quebras)


def remover_entrega(
    insights: dict[str, dict],
    quebras: dict[str, dict],
    anuncio: str,
    campanha: str | None = None,
) -> None:
    """Tira das respostas o anúncio e, quando dada, a campanha, como se não
    tivessem tido entrega em nenhum dos dois dias."""
    for nome in NOMES_PAGINAS:
        corpo = insights[nome]["corpo"]
        corpo["data"] = [linha for linha in corpo["data"] if linha["ad_id"] != anuncio]
    for _, _, nome in QUEBRAS:
        corpo = quebras[nome]["corpo"]
        corpo["data"] = [
            linha for linha in corpo["data"] if linha["campaign_id"] != campanha
        ]


def test_le_so_hoje_e_ontem_e_pelo_id_os_objetos_com_entrega(
    conectar_etl: Callable[[], psycopg.Connection],
    empresa: EmpresaTeste,
) -> None:
    # A horária não lê o cadastro completo nem o alcance (ADR-0017): as
    # consultas de insights são as duas páginas por anúncio e as três quebras,
    # todas de ontem a hoje, por dia; as demais chamadas são as leituras pelo
    # ID de cada anúncio com entrega, mesmo os que o banco já tem, e do
    # conjunto e da campanha deles. O anúncio e a campanha sem entrega não
    # são lidos, e nenhuma chamada vai à conta nem às arestas de cadastro.
    carregar_cadastro(conectar_etl, empresa.empresa_id)
    insights, quebras, objetos = (
        ler_fixtures_insights(),
        ler_fixtures_quebras(),
        montar_objetos_por_id(),
    )
    remover_entrega(
        insights, quebras, ID_META_ANUNCIO_SEM_ENTREGA, ID_META_CAMPANHA_SEM_ENTREGA
    )

    status, urls = executar_com_fixtures(
        conectar_etl, empresa.empresa_id, insights, quebras, objetos
    )

    assert status is StatusExecucao.SUCESSO
    caminhos = [urlsplit(url).path.removeprefix(f"/{VERSAO_API_META}/") for url in urls]
    consultas_insights = [
        parse_qs(urlsplit(url).query)
        for url, caminho in zip(urls, caminhos, strict=True)
        if caminho == f"{cadastro_exemplo.CONTA}/insights"
    ]
    assert len(consultas_insights) == len(NOMES_PAGINAS) + len(QUEBRAS)
    assert {
        (
            consulta["time_range"][0],
            consulta["time_increment"][0],
            consulta["level"][0],
            consulta.get("breakdowns", [None])[0],
        )
        for consulta in consultas_insights
    } == {
        (
            f'{{"since": "{INICIO.isoformat()}", "until": "{FIM.isoformat()}"}}',
            "1",
            nivel,
            quebra,
        )
        for nivel, quebra in [("ad", None), *(("campaign", q) for _, q, _ in QUEBRAS)]
    }
    releituras = [id_meta for id_meta, _ in listar_releituras(insights, objetos)]
    assert [
        caminho for caminho in caminhos if not caminho.endswith("/insights")
    ] == releituras
    assert len(urls) == len(consultas_insights) + len(releituras)
    assert not {
        ID_META_ANUNCIO_SEM_ENTREGA,
        ID_META_CONJUNTO_SEM_ENTREGA,
        ID_META_CAMPANHA_SEM_ENTREGA,
    } & set(caminhos)


def test_releitura_pelo_id_atualiza_nome_status_e_meta(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # A campanha renomeada e pausada, o conjunto com outra meta e o anúncio
    # renomeado, com outro título no criativo, já estão no banco pelo
    # cadastro, e só a releitura pelo ID da horária os atualiza (ADR-0017).
    carregar_cadastro(conectar_etl, empresa.empresa_id)
    objetos = montar_objetos_por_id()
    campanha = objetos[ID_META_CAMPANHA_RENOMEADA]["corpo"]
    campanha.update(name="Campanha Exemplo Renomeada", status="PAUSED")
    objetos[ID_META_CONJUNTO_NOVA_META]["corpo"]["optimization_goal"] = "LINK_CLICKS"
    anuncio = objetos[ID_META_ANUNCIO_RENOMEADO]["corpo"]
    anuncio["name"] = "Anúncio Exemplo Renomeado"
    # O criativo é N:1, e a API o devolve igual em todo anúncio que o usa.
    for objeto in objetos.values():
        criativo = objeto["corpo"].get("creative")
        if criativo is not None and criativo["id"] == anuncio["creative"]["id"]:
            criativo["title"] = "Título Exemplo Revisado"

    status, _ = executar_com_fixtures(conectar_etl, empresa.empresa_id, objetos=objetos)

    assert status is StatusExecucao.SUCESSO
    assert conexao_operador.execute(
        "SELECT nome, status FROM normalizado.campanha"
        " WHERE empresa_id = %s AND id_meta = %s",
        (empresa.empresa_id, ID_META_CAMPANHA_RENOMEADA),
    ).fetchone() == ("Campanha Exemplo Renomeada", "PAUSED")
    assert conexao_operador.execute(
        "SELECT meta_otimizacao FROM normalizado.conjunto_anuncio"
        " WHERE empresa_id = %s AND id_meta = %s",
        (empresa.empresa_id, ID_META_CONJUNTO_NOVA_META),
    ).fetchone() == ("LINK_CLICKS",)
    assert conexao_operador.execute(
        "SELECT nome FROM normalizado.anuncio WHERE empresa_id = %s AND id_meta = %s",
        (empresa.empresa_id, ID_META_ANUNCIO_RENOMEADO),
    ).fetchone() == ("Anúncio Exemplo Renomeado",)
    assert conexao_operador.execute(
        "SELECT titulo FROM normalizado.criativo WHERE empresa_id = %s AND id_meta = %s",
        (empresa.empresa_id, anuncio["creative"]["id"]),
    ).fetchone() == ("Título Exemplo Revisado",)


def test_campanha_que_so_aparece_nas_quebras_e_lida_pelo_id(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # Sem o anúncio excluído nos insights, a campanha dele, que o banco não
    # tem, só aparece nas quebras: ela é lida pelo ID depois dos anúncios, e
    # as quebras dela entram com a FK satisfeita.
    carregar_cadastro(conectar_etl, empresa.empresa_id)
    insights, quebras, objetos = (
        ler_fixtures_insights(),
        ler_fixtures_quebras(),
        montar_objetos_por_id(),
    )
    remover_entrega(insights, quebras, ID_META_ANUNCIO_AUSENTE)

    def simular_api(api: responses.RequestsMock) -> None:
        simular_horaria(api, insights, quebras, objetos)
        simular(
            api,
            ID_META_CAMPANHA_AUSENTE,
            objetos[ID_META_CAMPANHA_AUSENTE],
            {"fields": montar_campos(ObjetoApi.CAMPANHA)},
        )

    status, urls = executar_horaria(conectar_etl, empresa.empresa_id, simular_api)

    assert status is StatusExecucao.SUCESSO
    assert urlsplit(urls[-1]).path.endswith(f"/{ID_META_CAMPANHA_AUSENTE}")
    assert ler_linhas(
        conexao_operador, LER_INVESTIMENTO_QUEBRAS, empresa.empresa_id
    ) == montar_investimento_quebras_api(quebras)
    assert any(
        linha[0] == ID_META_CAMPANHA_AUSENTE
        for linha in ler_linhas(
            conexao_operador, LER_INVESTIMENTO_QUEBRAS, empresa.empresa_id
        )
    )


def test_horaria_duas_vezes_com_a_mesma_resposta_produz_o_mesmo_estado(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    carregar_cadastro(conectar_etl, empresa.empresa_id)
    assert executar_com_fixtures(conectar_etl, empresa.empresa_id)[0] is (
        StatusExecucao.SUCESSO
    )
    estado = ler_estado(conexao_operador, [empresa.empresa_id])

    assert executar_com_fixtures(conectar_etl, empresa.empresa_id)[0] is (
        StatusExecucao.SUCESSO
    )

    assert ler_estado(conexao_operador, [empresa.empresa_id]) == estado


def test_falha_nas_quebras_desfaz_os_insights_da_mesma_execucao(
    monkeypatch: pytest.MonkeyPatch,
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # Os insights já carregados na transação da empresa saem com ela (RF-18).
    carregar_cadastro(conectar_etl, empresa.empresa_id)
    estado = ler_estado(conexao_operador, [empresa.empresa_id])

    def falhar(*args: object) -> None:
        raise RuntimeError("falha injetada nas quebras")

    monkeypatch.setattr(rotina_horaria, "carregar_quebras_conta", falhar)

    status, _ = executar_com_fixtures(conectar_etl, empresa.empresa_id)

    assert status is StatusExecucao.FALHA
    assert ler_estado(conexao_operador, [empresa.empresa_id]) == estado
    assert conexao_operador.execute(
        LER_EXECUCOES, (empresa.empresa_id,)
    ).fetchall() == [(TIPO_HISTORICA, "sucesso"), (TIPO_HORARIA, "falha")]


def test_conta_sem_carga_inicial_fica_fora_da_horaria(
    conectar_etl: Callable[[], psycopg.Connection],
    empresa: EmpresaTeste,
) -> None:
    # Sem fuso, não há como saber o hoje da conta: ela espera a carga inicial.
    status, urls = executar_horaria(conectar_etl, empresa.empresa_id, lambda api: None)

    assert status is StatusExecucao.SUCESSO
    assert urls == []


def test_ponto_de_entrada_roda_a_horaria_sem_a_retencao_de_bruto(
    monkeypatch: pytest.MonkeyPatch,
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # O ponto de entrada, com os privilégios da ETL e o relógio real. Só a
    # empresa do teste entra, porque o seed do banco local tem outras, e sem
    # as esperas do cliente, para que uma chamada não simulada falhe na hora.
    # A resposta vencida continua no bruto: a retenção é da revisão diária.
    monkeypatch.setattr(
        rotina_horaria, "listar_empresas_ativas", lambda conexao: [empresa.empresa_id]
    )
    monkeypatch.setattr(
        rotina_horaria,
        "ClienteApiMeta",
        partial(ClienteApiMeta, dormir=lambda segundos: None),
    )
    hoje = agora_utc().astimezone(ZoneInfo(FUSO_BRASILIA)).date()
    vencida = hoje - timedelta(days=RETENCAO_DIAS + 1)
    execucao_id = uuid4()
    with conexao_operador.transaction():
        conexao_operador.execute(
            "UPDATE normalizado.conta_anuncio SET fuso_horario = %s, moeda = 'BRL'"
            " WHERE id = %s",
            (FUSO_BRASILIA, empresa.conta_id),
        )
        conexao_operador.execute(
            "INSERT INTO normalizado.execucao_carga (id, empresa_id, tipo)"
            " VALUES (%s, %s, 'diaria')",
            (execucao_id, empresa.empresa_id),
        )
        conexao_operador.execute(
            "INSERT INTO bruto.resposta_api (empresa_id, execucao_id,"
            " conta_anuncio_id, endpoint, parametros, data_referencia, resposta)"
            " VALUES (%s, %s, %s, 'insights', '{}', %s, '{}')",
            (empresa.empresa_id, execucao_id, empresa.conta_id, vencida),
        )

    with responses.RequestsMock(registry=OrderedRegistry) as api:
        simular_vazia(api, hoje)
        codigo = rotina_horaria.executar_rotina(Ambiente(TOKEN, URL_BANCO_ETL))

    assert codigo == CODIGO_SAIDA_SUCESSO
    assert conexao_operador.execute(
        "SELECT tipo, status FROM normalizado.execucao_carga"
        " WHERE empresa_id = %s AND id <> %s",
        (empresa.empresa_id, execucao_id),
    ).fetchall() == [(TIPO_HORARIA, "sucesso")]
    assert conexao_operador.execute(
        "SELECT min(data_referencia) FROM bruto.resposta_api WHERE empresa_id = %s",
        (empresa.empresa_id,),
    ).fetchone() == (vencida,)


def simular_vazia(api: responses.RequestsMock, hoje: date) -> None:
    """Os insights e as quebras de ontem e hoje de uma conta sem entrega."""
    ontem = hoje - timedelta(days=1)
    conta = cadastro_exemplo.CONTA
    simular(
        api,
        f"{conta}/insights",
        RESPOSTA_VAZIA,
        montar_parametros_insights(ontem, hoje),
    )
    for _, breakdowns, _ in QUEBRAS:
        simular(
            api,
            f"{conta}/insights",
            RESPOSTA_VAZIA,
            montar_parametros_quebra(breakdowns, ontem, hoje),
        )
