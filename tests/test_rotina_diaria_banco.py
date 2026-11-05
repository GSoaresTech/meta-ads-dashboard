"""Prova, contra o banco local e com a API simulada pelas fixtures, a rotina
diária de ponta a ponta, pela execução por empresa: a revisão da Meta dentro
da janela de 28 dias (RF-05), a ordem das etapas (ADR-0011), a janela no fuso
de cada conta e a transação única por empresa (RF-18; ADR-0009 §5). Exige o
banco local de pé.
"""

import copy
from collections.abc import Callable, Iterator, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import partial
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
import responses
from responses.registries import OrderedRegistry

from etl import rotina_diaria
from etl.cadastro import listar_empresas_ativas
from etl.cliente_api_meta import ClienteApiMeta
from etl.configuracao import Ambiente
from etl.execucao import (
    CODIGO_SAIDA_FALHA,
    CODIGO_SAIDA_SUCESSO,
    TIPO_COM_RETENCAO,
    StatusExecucao,
    executar_empresa,
    executar_empresas,
)
from etl.extracao import agora_utc
from etl.rotina_diaria import TarefaRotinaDiaria
from tests import alcance_exemplo, cadastro_exemplo
from tests.cadastro_exemplo import ID_META_CONTA
from tests.carga_exemplo import ler_estado
from tests.conftest import (
    LIMPEZA_EMPRESA,
    URL_BANCO_LOCAL,
    EmpresaTeste,
    criar_empresa,
)
from tests.insights_exemplo import ID_META_ANUNCIO_AUSENTE, simular_entidades
from tests.insights_exemplo import ler_fixtures as ler_fixtures_insights
from tests.rotina_diaria_exemplo import (
    ANTES,
    DEPOIS,
    DIA_FORA_DA_SEGUNDA_JANELA,
    DIA_REVISADO,
    DIA_SEM_REVISAO,
    PRIMEIRA_EXECUCAO,
    PRIMEIRO_DIA_SEGUNDA_JANELA,
    PRIMEIRO_HOJE,
    RESPOSTA_VAZIA,
    SEGUNDA_EXECUCAO,
    SEGUNDO_HOJE,
    ler_insights,
    ler_quebras,
    listar_linhas,
    simular_conta_vazia,
    simular_rotina,
)

pytestmark = pytest.mark.integracao

NOME_EMPRESA = "Empresa Exemplo Rotina"
NOME_OUTRA_EMPRESA = "Empresa Exemplo Rotina B"
NOME_EMPRESA_INATIVA = "Empresa Exemplo Rotina Inativa"
TOKEN = "EAAFicticio0000000000000000000000000000000000ZZ"
# A conexão do ponto de entrada não passa pelo SET ROLE de conectar_etl.
URL_BANCO_ETL = f"{URL_BANCO_LOCAL}?options=-crole%3Detl_carga"
ID_META_OUTRA_CONTA = "995000000000002"
ID_META_CONTA_LOS_ANGELES = "995000000000003"
FUSO_BRASILIA = "America/Sao_Paulo"
FUSO_LOS_ANGELES = "America/Los_Angeles"
ID_META_CAMPANHA_THRUPLAY = "995000000000000002"
ID_META_CONJUNTO_THRUPLAY = "995000000000000006"
ID_META_ANUNCIO_THRUPLAY = "995000000000000010"
ID_META_CONJUNTO_CONVERSAS = "995000000000000097"
ID_META_ANUNCIO_CONVERSAS = "995000000000000098"
TIPO_ACAO_CONVERSAS = "onsite_conversion.messaging_conversation_started_7d"
TIPO_ACAO_COMPRAS = "omni_purchase"
TIPO_ACAO_REMOVIDO = "offsite_conversion.fb_pixel_add_to_cart"
RETENCAO_DIAS = 35
# As linhas do alcance das fixtures, nos três níveis.
LINHAS_ALCANCE = 32

LER_METRICAS = """
SELECT anuncio.id_meta, metrica.data, metrica.investimento, metrica.impressoes,
       metrica.alcance
FROM normalizado.metrica_diaria_anuncio AS metrica
JOIN normalizado.anuncio AS anuncio
  ON anuncio.empresa_id = metrica.empresa_id AND anuncio.id = metrica.anuncio_id
WHERE metrica.empresa_id = %s AND metrica.data = ANY(%s)
"""

LER_ACOES = """
SELECT anuncio.id_meta, acao.data, acao.tipo_acao, acao.quantidade, acao.valor
FROM normalizado.acao_diaria_anuncio AS acao
JOIN normalizado.anuncio AS anuncio
  ON anuncio.empresa_id = acao.empresa_id AND anuncio.id = acao.anuncio_id
WHERE acao.empresa_id = %s AND acao.data = ANY(%s)
"""

LER_ACOES_QUEBRA = """
SELECT quebra.data, quebra.tipo_quebra, quebra.categoria, quebra.subcategoria,
       acao.tipo_acao, acao.quantidade, acao.valor
FROM normalizado.quebra_diaria_campanha AS quebra
JOIN normalizado.acao_quebra_diaria_campanha AS acao
  ON acao.empresa_id = quebra.empresa_id AND acao.quebra_diaria_campanha_id = quebra.id
WHERE quebra.empresa_id = %s AND quebra.data = ANY(%s)
"""

# As quebras e as ações delas pelo grão, sem a chave substituta, que muda a
# cada execução (ADR-0009 §5).
LER_QUEBRAS = """
SELECT campanha.id_meta, quebra.data, quebra.tipo_quebra, quebra.categoria,
       quebra.subcategoria, quebra.investimento, quebra.impressoes, quebra.alcance,
       acao.tipo_acao, acao.quantidade, acao.valor
FROM normalizado.quebra_diaria_campanha AS quebra
JOIN normalizado.campanha AS campanha
  ON campanha.empresa_id = quebra.empresa_id AND campanha.id = quebra.campanha_id
LEFT JOIN normalizado.acao_quebra_diaria_campanha AS acao
  ON acao.empresa_id = quebra.empresa_id AND acao.quebra_diaria_campanha_id = quebra.id
WHERE quebra.empresa_id = %s
"""

LER_EXECUCOES = """
SELECT tipo, status FROM normalizado.execucao_carga WHERE empresa_id = %s
"""

LER_CONTAGENS = """
SELECT tabela, linhas FROM normalizado.contagem_linhas_execucao WHERE empresa_id = %s
"""

type Linhas = set[tuple]


def apagar_empresas_rotina(conexao: psycopg.Connection) -> None:
    for (empresa_id,) in conexao.execute(
        "SELECT id FROM normalizado.empresa WHERE nome = ANY(%s)",
        ([NOME_EMPRESA, NOME_OUTRA_EMPRESA, NOME_EMPRESA_INATIVA],),
    ).fetchall():
        with conexao.transaction():
            for comando in LIMPEZA_EMPRESA:
                conexao.execute(comando, {"empresa_id": empresa_id})


@pytest.fixture
def empresa(conexao_operador: psycopg.Connection) -> Iterator[EmpresaTeste]:
    apagar_empresas_rotina(conexao_operador)
    criada = criar_empresa(conexao_operador, NOME_EMPRESA, ID_META_CONTA, indice=1)
    try:
        yield criada
    finally:
        apagar_empresas_rotina(conexao_operador)


def executar_rotina(
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    instante: datetime,
    simular: Callable[[responses.RequestsMock], None],
) -> StatusExecucao:
    """Uma execução com a API simulada. Uma chamada não simulada falha a
    execução."""
    with responses.RequestsMock(registry=OrderedRegistry) as api:
        simular(api)
        cliente = ClienteApiMeta(TOKEN, dormir=lambda segundos: None)
        tarefa = TarefaRotinaDiaria(conectar, cliente, relogio=lambda: instante)
        return executar_empresa(conectar, empresa_id, TIPO_COM_RETENCAO, tarefa)


def executar_primeira(
    conectar: Callable[[], psycopg.Connection], empresa_id: UUID
) -> StatusExecucao:
    """A primeira execução da conta, com o banco vazio: pelo ID, só o anúncio
    excluído, o único que o cadastro não traz."""
    alcance = alcance_exemplo.ler_fixtures()

    def simular(api: responses.RequestsMock) -> None:
        simular_rotina(
            api, PRIMEIRO_HOJE, ler_insights(ANTES), ler_quebras(ANTES), alcance
        )
        simular_entidades(api, ler_fixtures_insights())

    return executar_rotina(conectar, empresa_id, PRIMEIRA_EXECUCAO, simular)


def executar_segunda(
    conectar: Callable[[], psycopg.Connection], empresa_id: UUID
) -> StatusExecucao:
    """A execução do dia seguinte, depois da revisão da Meta."""
    return executar_rotina(
        conectar,
        empresa_id,
        SEGUNDA_EXECUCAO,
        lambda api: simular_rotina(
            api,
            SEGUNDO_HOJE,
            ler_insights(DEPOIS),
            ler_quebras(DEPOIS),
            alcance_exemplo.ler_fixtures(),
        ),
    )


def ler_linhas(
    conexao: psycopg.Connection,
    consulta: str,
    empresa_id: UUID,
    dias: Sequence[date],
) -> Linhas:
    return set(conexao.execute(consulta, (empresa_id, list(dias))).fetchall())


def ler_todas_as_quebras(conexao: psycopg.Connection, empresa_id: UUID) -> Linhas:
    return set(conexao.execute(LER_QUEBRAS, (empresa_id,)).fetchall())


def converter_data(linha: dict) -> date:
    return date.fromisoformat(linha["date_start"])


def montar_metricas_api(fixture: dict, dias: Sequence[date]) -> Linhas:
    """As métricas como a resposta da API as traz, sem passar pela ETL."""
    return {
        (
            linha["ad_id"],
            converter_data(linha),
            Decimal(linha["spend"]),
            int(linha["impressions"]),
            int(linha["reach"]),
        )
        for dia in dias
        for linha in listar_linhas(fixture, dia)
    }


def ler_valor_acao(linha: dict, tipo_acao: str) -> Decimal | None:
    valores = {
        item["action_type"]: Decimal(item["value"])
        for item in linha.get("action_values", [])
    }
    return valores.get(tipo_acao)


def montar_acoes_api(fixture: dict, dias: Sequence[date]) -> Linhas:
    return {
        (
            linha["ad_id"],
            converter_data(linha),
            acao["action_type"],
            int(acao["value"]),
            ler_valor_acao(linha, acao["action_type"]),
        )
        for dia in dias
        for linha in listar_linhas(fixture, dia)
        for acao in linha["actions"]
    }


def montar_compras_quebra_api(fixtures: dict[str, dict], dia: date) -> Linhas:
    """A ação do resultado principal da campanha de vendas em cada categoria.
    A região não traz compras (R-23)."""
    dimensoes = {
        "idade_genero": ("age", "gender"),
        "plataforma_posicionamento": ("publisher_platform", "platform_position"),
    }
    return {
        (
            dia,
            tipo,
            linha[categoria],
            linha[subcategoria],
            TIPO_ACAO_COMPRAS,
            int(acao["value"]),
            ler_valor_acao(linha, TIPO_ACAO_COMPRAS),
        )
        for tipo, (categoria, subcategoria) in dimensoes.items()
        for linha in listar_linhas(fixtures[tipo], dia)
        for acao in linha["actions"]
        if acao["action_type"] == TIPO_ACAO_COMPRAS
    }


def test_conversoes_revisadas_na_janela_ficam_iguais_as_da_api(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # O critério do RF-05: a Meta revisa as conversões de um dia da janela, e
    # a execução diária seguinte deixa o banco igual à API.
    assert executar_primeira(conectar_etl, empresa.empresa_id) is StatusExecucao.SUCESSO
    dias = [
        PRIMEIRO_DIA_SEGUNDA_JANELA,
        DIA_REVISADO,
        DIA_SEM_REVISAO,
        SEGUNDO_HOJE - timedelta(days=1),
    ]
    antes = ler_linhas(conexao_operador, LER_ACOES, empresa.empresa_id, dias)
    assert antes != montar_acoes_api(ler_insights(DEPOIS), dias)

    assert executar_segunda(conectar_etl, empresa.empresa_id) is StatusExecucao.SUCESSO

    depois = ler_insights(DEPOIS)
    assert ler_linhas(
        conexao_operador, LER_ACOES, empresa.empresa_id, dias
    ) == montar_acoes_api(depois, dias)
    assert ler_linhas(
        conexao_operador, LER_METRICAS, empresa.empresa_id, dias
    ) == montar_metricas_api(depois, dias)


def test_acao_que_some_na_revisao_deixa_de_existir(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    assert executar_primeira(conectar_etl, empresa.empresa_id) is StatusExecucao.SUCESSO
    tipos_antes = {
        linha[2]
        for linha in ler_linhas(
            conexao_operador, LER_ACOES, empresa.empresa_id, [DIA_REVISADO]
        )
    }
    assert TIPO_ACAO_REMOVIDO in tipos_antes

    assert executar_segunda(conectar_etl, empresa.empresa_id) is StatusExecucao.SUCESSO

    tipos_depois = {
        linha[2]
        for linha in ler_linhas(
            conexao_operador, LER_ACOES, empresa.empresa_id, [DIA_REVISADO]
        )
    }
    assert TIPO_ACAO_REMOVIDO not in tipos_depois


def test_quebras_revisadas_ficam_iguais_as_da_api(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    assert executar_primeira(conectar_etl, empresa.empresa_id) is StatusExecucao.SUCESSO
    assert ler_linhas(
        conexao_operador, LER_ACOES_QUEBRA, empresa.empresa_id, [DIA_REVISADO]
    ) == montar_compras_quebra_api(ler_quebras(ANTES), DIA_REVISADO)

    assert executar_segunda(conectar_etl, empresa.empresa_id) is StatusExecucao.SUCESSO

    assert ler_linhas(
        conexao_operador, LER_ACOES_QUEBRA, empresa.empresa_id, [DIA_REVISADO]
    ) == montar_compras_quebra_api(ler_quebras(DEPOIS), DIA_REVISADO)


def test_dia_fora_da_janela_fica_como_estava(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # O dia anterior à janela não vem na segunda resposta, e a substituição
    # não pode apagá-lo (RF-17): a janela tem 28 dias, e não 29.
    dias = [DIA_FORA_DA_SEGUNDA_JANELA]
    assert executar_primeira(conectar_etl, empresa.empresa_id) is StatusExecucao.SUCESSO
    consultas = (LER_METRICAS, LER_ACOES, LER_ACOES_QUEBRA)
    antes = [
        ler_linhas(conexao_operador, consulta, empresa.empresa_id, dias)
        for consulta in consultas
    ]
    assert all(antes)

    assert executar_segunda(conectar_etl, empresa.empresa_id) is StatusExecucao.SUCESSO

    assert antes == [
        ler_linhas(conexao_operador, consulta, empresa.empresa_id, dias)
        for consulta in consultas
    ]


def test_primeira_execucao_le_pelo_id_so_o_que_o_cadastro_nao_trouxe(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # Com o banco vazio, os anúncios dos insights e do alcance que o cadastro
    # traz não são lidos pelo ID: a simulação não responde a essas leituras,
    # que numa conta real seriam uma chamada por anúncio.
    assert executar_primeira(conectar_etl, empresa.empresa_id) is StatusExecucao.SUCESSO
    assert (
        conexao_operador.execute(
            "SELECT count(*) FROM normalizado.anuncio"
            " WHERE empresa_id = %s AND id_meta = %s",
            (empresa.empresa_id, ID_META_ANUNCIO_AUSENTE),
        ).fetchone()[0]
        == 1
    )


def test_uma_execucao_diaria_por_empresa_com_as_tabelas_de_todas_as_etapas(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    assert executar_primeira(conectar_etl, empresa.empresa_id) is StatusExecucao.SUCESSO

    assert conexao_operador.execute(
        LER_EXECUCOES, (empresa.empresa_id,)
    ).fetchall() == [("diaria", "sucesso")]
    contagens = dict(
        conexao_operador.execute(LER_CONTAGENS, (empresa.empresa_id,)).fetchall()
    )
    assert contagens["alcance_periodo"] == LINHAS_ALCANCE
    assert contagens["metrica_diaria_anuncio"] == len(
        listar_linhas(ler_insights(ANTES))
    )
    assert {
        "conta_anuncio",
        "campanha",
        "anuncio",
        "acao_diaria_anuncio",
        "quebra_diaria_campanha",
        "acao_quebra_diaria_campanha",
        "resposta_api",
    } <= contagens.keys()


def test_rotina_duas_vezes_com_a_mesma_resposta_produz_o_mesmo_estado(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # A segunda execução já não lê nada pelo ID: tudo está no banco.
    def repetir() -> StatusExecucao:
        return executar_rotina(
            conectar_etl,
            empresa.empresa_id,
            PRIMEIRA_EXECUCAO,
            lambda api: simular_rotina(
                api,
                PRIMEIRO_HOJE,
                ler_insights(ANTES),
                ler_quebras(ANTES),
                alcance_exemplo.ler_fixtures(),
            ),
        )

    assert executar_primeira(conectar_etl, empresa.empresa_id) is StatusExecucao.SUCESSO
    estado = ler_estado(conexao_operador, [empresa.empresa_id])
    quebras = ler_todas_as_quebras(conexao_operador, empresa.empresa_id)
    assert quebras

    assert repetir() is StatusExecucao.SUCESSO

    assert ler_estado(conexao_operador, [empresa.empresa_id]) == estado
    assert ler_todas_as_quebras(conexao_operador, empresa.empresa_id) == quebras


def montar_cadastro_com_conversas() -> dict[str, dict]:
    """O cadastro com mais um conjunto na campanha de ThruPlay, otimizado
    para conversas, e um anúncio nele."""
    cadastro = cadastro_exemplo.ler_fixtures()
    conjuntos = cadastro["cadastro_conjuntos"]["corpo"]["data"]
    conjuntos.append(
        {
            **copy.deepcopy(conjuntos[0]),
            "id": ID_META_CONJUNTO_CONVERSAS,
            "optimization_goal": "CONVERSATIONS",
        }
    )
    anuncios = cadastro["cadastro_anuncios_pagina_2"]["corpo"]["data"]
    anuncios.append(
        {
            **copy.deepcopy(anuncios[0]),
            "id": ID_META_ANUNCIO_CONVERSAS,
            "adset_id": ID_META_CONJUNTO_CONVERSAS,
        }
    )
    return cadastro


def montar_linha_insights(id_meta_anuncio: str, dia: date, investimento: str) -> dict:
    return {
        "ad_id": id_meta_anuncio,
        "spend": investimento,
        "impressions": "100",
        "reach": "90",
        "date_start": dia.isoformat(),
        "date_stop": dia.isoformat(),
    }


def montar_quebra_com_duas_acoes(dia: date) -> dict:
    return {
        "status": 200,
        "cabecalhos": {},
        "corpo": {
            "data": [
                {
                    "campaign_id": ID_META_CAMPANHA_THRUPLAY,
                    "spend": "51.00",
                    "impressions": "200",
                    "reach": "180",
                    "actions": [
                        {"action_type": "post_engagement", "value": "10"},
                        {"action_type": TIPO_ACAO_CONVERSAS, "value": "3"},
                    ],
                    "date_start": dia.isoformat(),
                    "date_stop": dia.isoformat(),
                    "age": "25-34",
                    "gender": "female",
                }
            ]
        },
    }


def test_quebras_resolvem_o_resultado_pelo_investimento_carregado_na_execucao(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # A campanha tem dois conjuntos com resultados diferentes, e o de maior
    # investimento nos últimos 28 dias decide (ADR-0007). O investimento vem
    # dos insights da mesma execução: com as quebras antes deles, o empate
    # sem investimento escolheria o conjunto de menor ID, de ThruPlay, e a
    # ação gravada seria a do engajamento (ADR-0011). A resolução usa o hoje
    # do banco, então os dias são os de agora.
    instante = agora_utc()
    hoje = instante.astimezone(ZoneInfo(FUSO_BRASILIA)).date()
    ontem = hoje - timedelta(days=1)
    insights = {
        "status": 200,
        "cabecalhos": {},
        "corpo": {
            "data": [
                montar_linha_insights(ID_META_ANUNCIO_THRUPLAY, ontem, "1.00"),
                montar_linha_insights(ID_META_ANUNCIO_CONVERSAS, ontem, "50.00"),
            ]
        },
    }

    status = executar_rotina(
        conectar_etl,
        empresa.empresa_id,
        instante,
        lambda api: simular_rotina(
            api,
            hoje,
            insights,
            {"idade_genero": montar_quebra_com_duas_acoes(ontem)},
            {},
            cadastro=montar_cadastro_com_conversas(),
        ),
    )

    assert status is StatusExecucao.SUCESSO
    assert {
        linha[4]
        for linha in ler_linhas(
            conexao_operador, LER_ACOES_QUEBRA, empresa.empresa_id, [ontem]
        )
    } == {TIPO_ACAO_CONVERSAS}


def test_janela_e_a_do_fuso_de_cada_conta(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # Às 06:43 UTC já é dia 7 em Brasília e ainda é dia 6 em Los Angeles: cada
    # conta da empresa tem a própria janela (ADR-0009 §5). A simulação só
    # responde à janela certa de cada uma, e a conta sem fuso, na primeira
    # execução, o recebe do cadastro.
    conexao_operador.execute(
        "INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta) VALUES (%s, %s)",
        (empresa.empresa_id, ID_META_CONTA_LOS_ANGELES),
    )

    def simular(api: responses.RequestsMock) -> None:
        simular_conta_vazia(api, ID_META_CONTA, FUSO_BRASILIA, PRIMEIRO_HOJE)
        simular_conta_vazia(
            api,
            ID_META_CONTA_LOS_ANGELES,
            FUSO_LOS_ANGELES,
            PRIMEIRO_HOJE - timedelta(days=1),
        )

    status = executar_rotina(
        conectar_etl, empresa.empresa_id, PRIMEIRA_EXECUCAO, simular
    )

    assert status is StatusExecucao.SUCESSO
    assert dict(
        conexao_operador.execute(
            "SELECT id_meta, fuso_horario FROM normalizado.conta_anuncio"
            " WHERE empresa_id = %s",
            (empresa.empresa_id,),
        ).fetchall()
    ) == {
        ID_META_CONTA: FUSO_BRASILIA,
        ID_META_CONTA_LOS_ANGELES: FUSO_LOS_ANGELES,
    }


def test_falha_no_alcance_desfaz_a_empresa_e_a_outra_carrega(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # A última etapa da carga falha, com o cadastro, os insights e as quebras
    # já gravados na transação: nada da empresa fica (RF-18), a outra carrega
    # e o job sai com falha (RF-50).
    outra = criar_empresa(
        conexao_operador, NOME_OUTRA_EMPRESA, ID_META_OUTRA_CONTA, indice=2
    )
    alcance = alcance_exemplo.ler_fixtures()
    alcance["alcance_campanha_semana"]["corpo"]["data"][0]["campaign_id"] = (
        "995000000000000099"
    )

    with responses.RequestsMock(registry=OrderedRegistry) as api:
        simular_rotina(
            api, PRIMEIRO_HOJE, ler_insights(ANTES), ler_quebras(ANTES), alcance
        )
        simular_entidades(api, ler_fixtures_insights())
        simular_conta_vazia(api, ID_META_OUTRA_CONTA, FUSO_BRASILIA, PRIMEIRO_HOJE)
        cliente = ClienteApiMeta(TOKEN, dormir=lambda segundos: None)
        tarefa = TarefaRotinaDiaria(
            conectar_etl, cliente, relogio=lambda: PRIMEIRA_EXECUCAO
        )
        codigo = executar_empresas(
            conectar_etl,
            [empresa.empresa_id, outra.empresa_id],
            TIPO_COM_RETENCAO,
            tarefa,
        )

    assert codigo == CODIGO_SAIDA_FALHA
    assert conexao_operador.execute(
        LER_EXECUCOES, (empresa.empresa_id,)
    ).fetchall() == [("diaria", "falha")]
    assert conexao_operador.execute(LER_EXECUCOES, (outra.empresa_id,)).fetchall() == [
        ("diaria", "sucesso")
    ]
    estado = ler_estado(conexao_operador, [empresa.empresa_id])
    assert all(contagem == 0 for contagem, _ in estado.values())
    assert (
        conexao_operador.execute(
            "SELECT count(*) FROM bruto.resposta_api WHERE empresa_id = %s",
            (empresa.empresa_id,),
        ).fetchone()[0]
        == 0
    )


def test_ponto_de_entrada_roda_a_rotina_e_aplica_a_retencao_de_bruto(
    monkeypatch: pytest.MonkeyPatch,
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # O ponto de entrada, com os privilégios da ETL. O dia da retenção é o
    # de agora, no fuso da conta (RF-21). Só a empresa do teste entra, porque
    # o seed do banco local tem outras, e sem as esperas do cliente, para que
    # uma chamada não simulada falhe na hora.
    monkeypatch.setattr(
        rotina_diaria,
        "listar_empresas_ativas",
        lambda conexao: [empresa.empresa_id],
    )
    monkeypatch.setattr(
        rotina_diaria,
        "ClienteApiMeta",
        partial(ClienteApiMeta, dormir=lambda segundos: None),
    )
    hoje = agora_utc().astimezone(ZoneInfo(FUSO_BRASILIA)).date()
    execucao_id = uuid4()
    with conexao_operador.transaction():
        # A retenção roda antes da carga do cadastro. Sem o fuso, ela usaria
        # o dia em UTC, que das 21h às 24h de Brasília já é o seguinte.
        conexao_operador.execute(
            "UPDATE normalizado.conta_anuncio SET fuso_horario = %s, moeda = %s"
            " WHERE id = %s",
            (FUSO_BRASILIA, "BRL", empresa.conta_id),
        )
        conexao_operador.execute(
            "INSERT INTO normalizado.execucao_carga (id, empresa_id, tipo)"
            " VALUES (%s, %s, 'diaria')",
            (execucao_id, empresa.empresa_id),
        )
        for dias in (RETENCAO_DIAS, RETENCAO_DIAS + 1):
            conexao_operador.execute(
                "INSERT INTO bruto.resposta_api (empresa_id, execucao_id,"
                " conta_anuncio_id, endpoint, parametros, data_referencia, resposta)"
                " VALUES (%s, %s, %s, 'insights', '{}', %s, '{}')",
                (
                    empresa.empresa_id,
                    execucao_id,
                    empresa.conta_id,
                    hoje - timedelta(days=dias),
                ),
            )

    with responses.RequestsMock(registry=OrderedRegistry) as api:
        simular_rotina(api, hoje, RESPOSTA_VAZIA, {}, {})
        codigo = rotina_diaria.executar_rotina(Ambiente(TOKEN, URL_BANCO_ETL))

    assert codigo == CODIGO_SAIDA_SUCESSO
    limite = hoje - timedelta(days=RETENCAO_DIAS)
    assert conexao_operador.execute(
        "SELECT min(data_referencia) FROM bruto.resposta_api WHERE empresa_id = %s",
        (empresa.empresa_id,),
    ).fetchone() == (limite,)


def test_lista_so_as_empresas_ativas(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # A empresa inativa não entra nas execuções (RF-48).
    with conexao_operador.transaction():
        inativa = conexao_operador.execute(
            "INSERT INTO normalizado.empresa (nome, situacao)"
            " VALUES (%s, 'inativa') RETURNING id",
            (NOME_EMPRESA_INATIVA,),
        ).fetchone()[0]

    with conectar_etl() as conexao:
        ativas = listar_empresas_ativas(conexao)

    assert empresa.empresa_id in ativas
    assert inativa not in ativas
