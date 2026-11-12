"""Prova, contra o banco local e com a API simulada pelas fixtures, a revisão
diária leve de ponta a ponta, pela execução por empresa: a revisão da Meta
dentro da janela de 28 dias (RF-05), sem o cadastro completo e com o alcance
dos períodos que contêm ontem, retomado dos dias perdidos depois de uma
falha (ADR-0017), a ordem das etapas (ADR-0011), a
janela no fuso de cada conta e a transação única por empresa (RF-18;
ADR-0009 §5). O cadastro vem antes, como a carga inicial o deixa. Exige o
banco local de pé.
"""

import copy
import json
from collections.abc import Callable, Iterator, Sequence
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

from etl import rotina_diaria
from etl.cadastro import TarefaCadastro, listar_empresas_ativas
from etl.carga_historica import TIPO_HISTORICA
from etl.cliente_api_meta import ClienteApiMeta
from etl.configuracao import VERSAO_API_META, Ambiente
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
from tests.insights_exemplo import (
    ID_META_ANUNCIO_AUSENTE,
    NOMES_ENTIDADES,
    simular_entidades,
)
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
    calcular_janela,
    ler_insights,
    ler_quebras,
    listar_linhas,
    montar_alcance_periodos,
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
SELECT tipo, status FROM normalizado.execucao_carga
WHERE empresa_id = %s ORDER BY iniciado_em
"""

LER_CONTAGENS_DIARIA = """
SELECT contagem.tabela, contagem.linhas
FROM normalizado.contagem_linhas_execucao AS contagem
JOIN normalizado.execucao_carga AS execucao
  ON execucao.empresa_id = contagem.empresa_id AND execucao.id = contagem.execucao_id
WHERE contagem.empresa_id = %s AND execucao.tipo = 'diaria'
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


def carregar_cadastro(
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    cadastro: dict[str, dict] | None = None,
) -> None:
    """O cadastro completo da conta das fixtures, como a carga inicial o deixa
    antes da revisão: com fuso, moeda e as entidades não excluídas
    (ADR-0017)."""
    with responses.RequestsMock(registry=OrderedRegistry) as api:
        cadastro_exemplo.simular_cadastro(
            api, cadastro_exemplo.ler_fixtures() if cadastro is None else cadastro
        )
        cliente = ClienteApiMeta(TOKEN, dormir=lambda segundos: None)
        tarefa = TarefaCadastro(conectar, cliente, relogio=lambda: PRIMEIRA_EXECUCAO)
        status = executar_empresa(conectar, empresa_id, TIPO_HISTORICA, tarefa)
    assert status is StatusExecucao.SUCESSO


def definir_fuso(conexao: psycopg.Connection, conta_id: UUID, fuso: str) -> None:
    """O fuso e a moeda que a carga inicial grava com o cadastro da conta."""
    conexao.execute(
        "UPDATE normalizado.conta_anuncio SET fuso_horario = %s, moeda = 'BRL'"
        " WHERE id = %s",
        (fuso, conta_id),
    )


def inserir_conta(conexao: psycopg.Connection, empresa_id: UUID, id_meta: str) -> UUID:
    """Uma conta recém-cadastrada, só com o ID da Meta."""
    return conexao.execute(
        "INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)"
        " VALUES (%s, %s) RETURNING id",
        (empresa_id, id_meta),
    ).fetchone()[0]


def executar_rotina(
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    instante: datetime,
    simular: Callable[[responses.RequestsMock], None],
) -> StatusExecucao:
    """Uma execução com a API simulada. Uma chamada não simulada falha a
    execução."""
    status, _ = executar_rotina_com_chamadas(conectar, empresa_id, instante, simular)
    return status


def executar_rotina_com_chamadas(
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    instante: datetime,
    simular: Callable[[responses.RequestsMock], None],
) -> tuple[StatusExecucao, list[str]]:
    """Uma execução com a API simulada e a URL de cada chamada, na ordem."""
    with responses.RequestsMock(registry=OrderedRegistry) as api:
        simular(api)
        cliente = ClienteApiMeta(TOKEN, dormir=lambda segundos: None)
        tarefa = TarefaRotinaDiaria(conectar, cliente, relogio=lambda: instante)
        status = executar_empresa(conectar, empresa_id, TIPO_COM_RETENCAO, tarefa)
        return status, [chamada.request.url for chamada in api.calls]


def simular_primeira(api: responses.RequestsMock) -> None:
    """A revisão de 07/04 depois da carga inicial: pelo ID, só o anúncio
    excluído, o único que o cadastro não traz, com o conjunto e a campanha
    dele. Sem alcance extraído, os períodos são os da janela inteira."""
    simular_rotina(
        api,
        PRIMEIRO_HOJE,
        ler_insights(ANTES),
        ler_quebras(ANTES),
        alcance_exemplo.ler_fixtures(),
    )
    simular_entidades(api, ler_fixtures_insights())


def executar_primeira(
    conectar: Callable[[], psycopg.Connection], empresa_id: UUID
) -> StatusExecucao:
    """O cadastro da carga inicial e a primeira revisão da conta."""
    carregar_cadastro(conectar, empresa_id)
    return executar_rotina(conectar, empresa_id, PRIMEIRA_EXECUCAO, simular_primeira)


def executar_segunda(
    conectar: Callable[[], psycopg.Connection], empresa_id: UUID
) -> StatusExecucao:
    """A revisão do dia seguinte, depois da revisão da Meta. A primeira
    extraiu o alcance até 06/04, e esta lê só os períodos de ontem."""
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
            desde=SEGUNDO_HOJE - timedelta(days=1),
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


def test_revisao_le_pelo_id_so_os_objetos_novos_sem_o_cadastro_completo(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # A revisão não lê o cadastro completo (ADR-0017): com os dados já
    # carregados, as únicas leituras de cadastro são as do anúncio que o banco
    # não tem, excluído e por isso fora das arestas, e as do conjunto e da
    # campanha dele, pelo ID. Nenhuma chamada vai à conta nem às arestas de
    # anúncios, conjuntos e campanhas; as demais são consultas de insights.
    carregar_cadastro(conectar_etl, empresa.empresa_id)
    fixtures = ler_fixtures_insights()
    novos = [fixtures[nome]["corpo"]["id"] for nome, _ in NOMES_ENTIDADES]
    assert novos[0] == ID_META_ANUNCIO_AUSENTE

    status, urls = executar_rotina_com_chamadas(
        conectar_etl, empresa.empresa_id, PRIMEIRA_EXECUCAO, simular_primeira
    )

    assert status is StatusExecucao.SUCESSO
    caminhos = [urlsplit(url).path.removeprefix(f"/{VERSAO_API_META}/") for url in urls]
    assert [caminho for caminho in caminhos if not caminho.endswith("/insights")] == (
        novos
    )
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
    # Uma execução diária depois da histórica da carga inicial, sem as linhas
    # da conta, que só o cadastro completo grava.
    assert executar_primeira(conectar_etl, empresa.empresa_id) is StatusExecucao.SUCESSO

    assert conexao_operador.execute(
        LER_EXECUCOES, (empresa.empresa_id,)
    ).fetchall() == [("historica", "sucesso"), ("diaria", "sucesso")]
    contagens = dict(
        conexao_operador.execute(LER_CONTAGENS_DIARIA, (empresa.empresa_id,)).fetchall()
    )
    alcance = montar_alcance_periodos(
        alcance_exemplo.ler_fixtures(), *calcular_janela(PRIMEIRO_HOJE)
    )
    assert contagens["alcance_periodo"] == sum(
        len(resposta["corpo"]["data"]) for resposta in alcance.values()
    )
    assert contagens["metrica_diaria_anuncio"] == len(
        listar_linhas(ler_insights(ANTES))
    )
    assert {
        "campanha",
        "anuncio",
        "acao_diaria_anuncio",
        "quebra_diaria_campanha",
        "acao_quebra_diaria_campanha",
        "resposta_api",
    } <= contagens.keys()
    assert "conta_anuncio" not in contagens


def test_rotina_duas_vezes_com_a_mesma_resposta_produz_o_mesmo_estado(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # A segunda execução já não lê nada pelo ID: tudo está no banco. O
    # alcance já foi extraído até ontem, e ela relê só os períodos de ontem.
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
                desde=PRIMEIRO_HOJE - timedelta(days=1),
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
    # sem investimento escolheria o conjunto de menor ID, de ThruPlay, cujo
    # resultado a quebra não traz, e nenhuma ação seria gravada (ADR-0011). A
    # resolução usa o hoje do banco, então os dias são os de agora.
    carregar_cadastro(conectar_etl, empresa.empresa_id, montar_cadastro_com_conversas())
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
    # conta da empresa tem a própria janela, no fuso que a carga inicial
    # gravou (ADR-0009 §5). A simulação só responde à janela certa de cada uma.
    with conexao_operador.transaction():
        definir_fuso(conexao_operador, empresa.conta_id, FUSO_BRASILIA)
        conta_los_angeles = inserir_conta(
            conexao_operador, empresa.empresa_id, ID_META_CONTA_LOS_ANGELES
        )
        definir_fuso(conexao_operador, conta_los_angeles, FUSO_LOS_ANGELES)

    def simular(api: responses.RequestsMock) -> None:
        simular_conta_vazia(api, ID_META_CONTA, PRIMEIRO_HOJE)
        simular_conta_vazia(
            api, ID_META_CONTA_LOS_ANGELES, PRIMEIRO_HOJE - timedelta(days=1)
        )

    status = executar_rotina(
        conectar_etl, empresa.empresa_id, PRIMEIRA_EXECUCAO, simular
    )

    assert status is StatusExecucao.SUCESSO


def test_conta_sem_carga_inicial_fica_fora_da_revisao(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # A conta recém-cadastrada ainda não tem o fuso, que só o cadastro
    # completo da carga inicial grava, e sem ele não há janela: a revisão não
    # chama a API para ela, que espera a carga inicial (ADR-0017). A outra
    # conta da empresa é revisada, e a simulação não responde a mais nada.
    with conexao_operador.transaction():
        definir_fuso(conexao_operador, empresa.conta_id, FUSO_BRASILIA)
        inserir_conta(conexao_operador, empresa.empresa_id, ID_META_OUTRA_CONTA)

    status = executar_rotina(
        conectar_etl,
        empresa.empresa_id,
        PRIMEIRA_EXECUCAO,
        lambda api: simular_conta_vazia(api, ID_META_CONTA, PRIMEIRO_HOJE),
    )

    assert status is StatusExecucao.SUCESSO


def test_alcance_e_o_da_semana_do_mes_e_do_ano_que_contem_ontem(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # Em 10/01/2027, a janela vai de 13/12/2026 a 09/01/2027 e toca dois
    # anos, e a revisão de ontem extraiu o alcance até 08/01. Esta lê só a
    # semana, o mês e o ano que contêm ontem, cada um do primeiro dia até
    # ontem. O ano em andamento continua atualizado, e os períodos que não
    # contêm ontem ficam com o que já foi gravado (ADR-0016; ADR-0017).
    definir_fuso(conexao_operador, empresa.conta_id, FUSO_BRASILIA)
    gravar_alcance_extraido(conexao_operador, empresa, date(2027, 1, 8))
    hoje = date(2027, 1, 10)

    status, urls = executar_rotina_com_chamadas(
        conectar_etl,
        empresa.empresa_id,
        datetime(2027, 1, 10, 6, 43, tzinfo=UTC),
        lambda api: simular_conta_vazia(
            api, ID_META_CONTA, hoje, desde=date(2027, 1, 9)
        ),
    )

    assert status is StatusExecucao.SUCESSO
    assert ler_periodos_consultados(urls) == {
        ("7", "2027-01-04", "2027-01-09"),
        ("monthly", "2027-01-01", "2027-01-09"),
        ("all_days", "2027-01-01", "2027-01-09"),
    }


def test_alcance_retoma_os_periodos_dos_dias_perdidos_depois_de_uma_falha(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # A revisão de 01/12/2026, com ontem em 30/11, falhou, e o alcance da
    # conta ficou extraído até 29/11. A de 02/12 relê os períodos de 30/11 e
    # de 01/12: novembro, que termina em 30/11, sai inteiro, em vez de ficar
    # cortado em 29/11 para sempre (RF-04; ADR-0017).
    definir_fuso(conexao_operador, empresa.conta_id, FUSO_BRASILIA)
    gravar_alcance_extraido(conexao_operador, empresa, date(2026, 11, 29))
    hoje = date(2026, 12, 2)

    status, urls = executar_rotina_com_chamadas(
        conectar_etl,
        empresa.empresa_id,
        datetime(2026, 12, 2, 6, 43, tzinfo=UTC),
        lambda api: simular_conta_vazia(
            api, ID_META_CONTA, hoje, desde=date(2026, 11, 30)
        ),
    )

    assert status is StatusExecucao.SUCESSO
    assert ler_periodos_consultados(urls) == {
        ("7", "2026-11-30", "2026-12-01"),
        ("monthly", "2026-11-01", "2026-12-01"),
        ("all_days", "2026-01-01", "2026-12-01"),
    }


def gravar_alcance_extraido(
    conexao: psycopg.Connection, empresa: EmpresaTeste, ate: date
) -> None:
    """O alcance do ano da própria conta extraído até o dia dado, como a
    revisão anterior o deixa."""
    with conexao.transaction():
        execucao_id = conexao.execute(
            "INSERT INTO normalizado.execucao_carga (empresa_id, tipo)"
            " VALUES (%s, 'diaria') RETURNING id",
            (empresa.empresa_id,),
        ).fetchone()[0]
        conexao.execute(
            "INSERT INTO normalizado.alcance_periodo (empresa_id, conta_anuncio_id,"
            " tipo_periodo, inicio_periodo, fim_periodo, alcance, impressoes,"
            " execucao_id) VALUES (%s, %s, 'ano', %s, %s, 10, 12, %s)",
            (
                empresa.empresa_id,
                empresa.conta_id,
                date(ate.year, 1, 1),
                ate,
                execucao_id,
            ),
        )


def ler_periodos_consultados(urls: Sequence[str]) -> set[tuple[str, str, str]]:
    """O incremento, o since e o until de cada consulta de alcance."""
    consultas = [parse_qs(urlsplit(url).query) for url in urls]
    return {
        (
            consulta["time_increment"][0],
            json.loads(consulta["time_range"][0])["since"],
            json.loads(consulta["time_range"][0])["until"],
        )
        for consulta in consultas
        if consulta["time_increment"][0] != "1"
    }


def test_falha_no_alcance_desfaz_a_empresa_e_a_outra_carrega(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # A última etapa da carga falha, no alcance do ano, com os insights e as
    # quebras já gravados na transação: nada da revisão fica, nem a retenção
    # (RF-18), a outra empresa carrega e o job sai com falha (RF-50).
    carregar_cadastro(conectar_etl, empresa.empresa_id)
    outra = criar_empresa(
        conexao_operador, NOME_OUTRA_EMPRESA, ID_META_OUTRA_CONTA, indice=2
    )
    definir_fuso(conexao_operador, outra.conta_id, FUSO_BRASILIA)
    alcance = alcance_exemplo.ler_fixtures()
    alcance["alcance_campanha_ano"]["corpo"]["data"][0]["campaign_id"] = (
        "995000000000000099"
    )
    estado = ler_estado(conexao_operador, [empresa.empresa_id])
    bruto = contar_bruto(conexao_operador, empresa.empresa_id)

    with responses.RequestsMock(registry=OrderedRegistry) as api:
        simular_rotina(
            api, PRIMEIRO_HOJE, ler_insights(ANTES), ler_quebras(ANTES), alcance
        )
        simular_entidades(api, ler_fixtures_insights())
        simular_conta_vazia(api, ID_META_OUTRA_CONTA, PRIMEIRO_HOJE)
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
    ).fetchall() == [("historica", "sucesso"), ("diaria", "falha")]
    assert conexao_operador.execute(LER_EXECUCOES, (outra.empresa_id,)).fetchall() == [
        ("diaria", "sucesso")
    ]
    assert ler_estado(conexao_operador, [empresa.empresa_id]) == estado
    assert contar_bruto(conexao_operador, empresa.empresa_id) == bruto


def contar_bruto(conexao: psycopg.Connection, empresa_id: UUID) -> int:
    return conexao.execute(
        "SELECT count(*) FROM bruto.resposta_api WHERE empresa_id = %s",
        (empresa_id,),
    ).fetchone()[0]


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
        # A conta tem o fuso que a carga inicial grava: sem ele, a revisão não
        # a lê, e a retenção usaria o dia em UTC, que das 21h às 24h de
        # Brasília já é o seguinte.
        definir_fuso(conexao_operador, empresa.conta_id, FUSO_BRASILIA)
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
