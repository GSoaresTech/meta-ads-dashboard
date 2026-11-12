"""Prova, contra o banco local e com a API simulada pelas fixtures, a extração
e a carga das quebras diárias por campanha de ponta a ponta, pela execução
por empresa (RF-03, RF-09, RF-17; ADR-0011). O cadastro da conta é carregado
antes pela tarefa de cadastro, salvo a campanha do anúncio excluído, que só
existe pelo ID. Exige o banco local de pé.
"""

import copy
from collections.abc import Callable, Iterator
from datetime import date
from decimal import Decimal
from uuid import UUID

import psycopg
import pytest
import responses
from responses.registries import OrderedRegistry

from etl.cadastro import TarefaCadastro
from etl.cliente_api_meta import ClienteApiMeta
from etl.execucao import StatusExecucao, TarefaCarga, executar_empresa
from etl.insights import TarefaInsightsDiarios
from etl.quebras import TarefaQuebrasCampanha
from tests import cadastro_exemplo, insights_exemplo
from tests.cadastro_exemplo import ID_META_CONTA
from tests.conftest import LIMPEZA_EMPRESA, EmpresaTeste, criar_empresa
from tests.insights_exemplo import FIM, INICIO
from tests.quebras_exemplo import (
    CAMPANHAS_SEM_ACAO_RESULTADO,
    ID_META_CAMPANHA_AUSENTE,
    TIPOS_ACAO_RESULTADO,
    Fixtures,
    ler_fixtures,
    listar_linhas,
    simular_quebras,
)

pytestmark = pytest.mark.integracao

NOME_EMPRESA = "Empresa Exemplo Quebras"
TOKEN = "EAAFicticio0000000000000000000000000000000000ZZ"
# Diferença máxima entre a soma do investimento das categorias de cada
# quebra e o investimento da campanha no dia (RF-03).
TOLERANCIA_RELATIVA = Decimal("0.01")
# As três quebras de cada campanha e dia das fixtures, com o dia sem
# investimento da campanha de ThruPlay.
GRUPOS_QUEBRA = 24
LINHAS_QUEBRA = 88
# As categorias das três quebras no único dia da campanha do anúncio
# excluído.
LINHAS_CAMPANHA_AUSENTE = 11
ID_META_CAMPANHA_CADASTROS = "995000000000000003"

# Por campanha, dia e tipo de quebra: o investimento das categorias e o da
# campanha, somado dos anúncios dela pelo caminho até a campanha (ADR-0009
# §2).
COMPARAR_INVESTIMENTO = """
WITH quebra AS (
  SELECT quebra.campanha_id, quebra.data, quebra.tipo_quebra,
         sum(quebra.investimento) AS investimento
  FROM normalizado.quebra_diaria_campanha AS quebra
  WHERE quebra.empresa_id = %(empresa_id)s
  GROUP BY 1, 2, 3
),
campanha AS (
  SELECT conjunto.campanha_id, metrica.data, sum(metrica.investimento) AS investimento
  FROM normalizado.metrica_diaria_anuncio AS metrica
  JOIN normalizado.anuncio AS anuncio
    ON anuncio.empresa_id = metrica.empresa_id AND anuncio.id = metrica.anuncio_id
  JOIN normalizado.conjunto_anuncio AS conjunto
    ON conjunto.empresa_id = anuncio.empresa_id AND conjunto.id = anuncio.conjunto_anuncio_id
  WHERE metrica.empresa_id = %(empresa_id)s
  GROUP BY 1, 2
)
SELECT nome.id_meta, campanha.data, quebra.tipo_quebra,
       quebra.investimento, campanha.investimento
FROM campanha
JOIN normalizado.campanha AS nome
  ON nome.empresa_id = %(empresa_id)s AND nome.id = campanha.campanha_id
LEFT JOIN quebra
  ON quebra.campanha_id = campanha.campanha_id AND quebra.data = campanha.data
ORDER BY 1, 2, 3
"""

# As linhas de quebra e as ações delas pelo grão, sem a chave substituta,
# que muda a cada execução (ADR-0009 §5).
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
ORDER BY 1, 2, 3, 4, 5, 9
"""

LER_ACOES = """
SELECT campanha.id_meta, quebra.tipo_quebra, acao.tipo_acao, acao.quantidade
FROM normalizado.acao_quebra_diaria_campanha AS acao
JOIN normalizado.quebra_diaria_campanha AS quebra
  ON quebra.empresa_id = acao.empresa_id AND quebra.id = acao.quebra_diaria_campanha_id
JOIN normalizado.campanha AS campanha
  ON campanha.empresa_id = quebra.empresa_id AND campanha.id = quebra.campanha_id
WHERE acao.empresa_id = %s
"""


@pytest.fixture
def empresa(conexao_operador: psycopg.Connection) -> Iterator[EmpresaTeste]:
    apagar_empresa_quebras(conexao_operador)
    criada = criar_empresa(conexao_operador, NOME_EMPRESA, ID_META_CONTA, indice=1)
    try:
        yield criada
    finally:
        apagar_empresa_quebras(conexao_operador)


def apagar_empresa_quebras(conexao: psycopg.Connection) -> None:
    for (empresa_id,) in conexao.execute(
        "SELECT id FROM normalizado.empresa WHERE nome = %s", (NOME_EMPRESA,)
    ).fetchall():
        with conexao.transaction():
            for comando in LIMPEZA_EMPRESA:
                conexao.execute(comando, {"empresa_id": empresa_id})


def executar(
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    montar_tarefa: Callable[[ClienteApiMeta], TarefaCarga],
    simular: Callable[[responses.RequestsMock], None],
) -> StatusExecucao:
    """Uma execução com a API simulada. Uma chamada não simulada falha a
    execução."""
    with responses.RequestsMock(registry=OrderedRegistry) as api:
        simular(api)
        cliente = ClienteApiMeta(TOKEN, dormir=lambda segundos: None)
        return executar_empresa(conectar, empresa_id, "horaria", montar_tarefa(cliente))


@pytest.fixture
def cadastrada(
    conectar_etl: Callable[[], psycopg.Connection], empresa: EmpresaTeste
) -> EmpresaTeste:
    """A empresa com o cadastro da conta já carregado, como depois da
    execução diária."""
    status = executar(
        conectar_etl,
        empresa.empresa_id,
        lambda cliente: TarefaCadastro(conectar_etl, cliente),
        lambda api: cadastro_exemplo.simular_cadastro(
            api, cadastro_exemplo.ler_fixtures()
        ),
    )
    assert status is StatusExecucao.SUCESSO
    return empresa


@pytest.fixture
def com_insights(
    conectar_etl: Callable[[], psycopg.Connection], cadastrada: EmpresaTeste
) -> EmpresaTeste:
    """A empresa com os insights diários por anúncio dos mesmos dias, que
    trazem a campanha do anúncio excluído."""
    status = executar(
        conectar_etl,
        cadastrada.empresa_id,
        lambda cliente: TarefaInsightsDiarios(conectar_etl, cliente, INICIO, FIM),
        lambda api: insights_exemplo.simular_insights(
            api, insights_exemplo.ler_fixtures()
        ),
    )
    assert status is StatusExecucao.SUCESSO
    return cadastrada


def executar_quebras(
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    fixtures: Fixtures,
    *,
    com_campanha: bool = False,
) -> StatusExecucao:
    return executar(
        conectar,
        empresa_id,
        lambda cliente: TarefaQuebrasCampanha(conectar, cliente, INICIO, FIM),
        lambda api: simular_quebras(api, fixtures, com_campanha=com_campanha),
    )


def ler_quebras(conexao: psycopg.Connection, empresa_id: UUID) -> list[tuple]:
    return conexao.execute(LER_QUEBRAS, (empresa_id,)).fetchall()


def sobrescrever_com_interacoes(
    conexao_operador: psycopg.Connection, empresa_id: UUID
) -> None:
    """Dá às campanhas de ThruPlay, cujo resultado as fixtures não trazem, as
    interações como resultado, que vêm em todas as quebras, inclusive na
    região (RF-49)."""
    conexao_operador.execute(
        "INSERT INTO normalizado.sobrescrita_resultado_campanha"
        " (empresa_id, campanha_id, metrica_resultado, metrica_kpi)"
        " SELECT empresa_id, id, 'interacoes_publicacao', 'custo_interacao'"
        " FROM normalizado.campanha WHERE empresa_id = %s AND id_meta = ANY(%s)",
        (empresa_id, list(CAMPANHAS_SEM_ACAO_RESULTADO)),
    )


def ler_acoes(conexao: psycopg.Connection, empresa_id: UUID) -> list[tuple]:
    return conexao.execute(LER_ACOES, (empresa_id,)).fetchall()


def test_investimento_das_categorias_difere_no_maximo_1_porcento_do_da_campanha(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    com_insights: EmpresaTeste,
) -> None:
    # Critério do RF-03: em cada campanha e dia, cada uma das três quebras
    # soma o investimento da campanha, com a tolerância das estimativas da
    # Meta (R-23).
    status = executar_quebras(conectar_etl, com_insights.empresa_id, ler_fixtures())

    assert status is StatusExecucao.SUCESSO
    grupos = conexao_operador.execute(
        COMPARAR_INVESTIMENTO, {"empresa_id": com_insights.empresa_id}
    ).fetchall()
    assert len(grupos) == GRUPOS_QUEBRA
    assert {tipo for _, _, tipo, _, _ in grupos} == {
        "idade_genero",
        "plataforma_posicionamento",
        "regiao",
    }
    for _, _, _, das_categorias, da_campanha in grupos:
        assert abs(das_categorias - da_campanha) <= TOLERANCIA_RELATIVA * da_campanha
    assert any(c != d for *_, c, d in grupos)


def test_quebras_vem_como_a_api_as_devolveu_com_a_acao_do_resultado(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    com_insights: EmpresaTeste,
) -> None:
    # O tipo de ação de cada campanha vem da resolução do resultado
    # principal no banco (ADR-0011), e não da resposta. As campanhas cujo
    # resultado não veio na resposta ficam sem ações.
    status = executar_quebras(conectar_etl, com_insights.empresa_id, ler_fixtures())

    assert status is StatusExecucao.SUCESSO
    linhas = ler_quebras(conexao_operador, com_insights.empresa_id)
    assert len({linha[:5] for linha in linhas}) == LINHAS_QUEBRA
    assert (
        "995000000000000005",
        date(2026, 10, 1),
        "idade_genero",
        "25-34",
        "female",
        Decimal("18.29"),
        1981,
        1674,
        "omni_purchase",
        2,
        Decimal("259.8"),
    ) in linhas
    acoes = ler_acoes(conexao_operador, com_insights.empresa_id)
    assert {(id_meta, tipo) for id_meta, _, tipo, _ in acoes} == {
        (id_meta, tipo)
        for id_meta, tipo in TIPOS_ACAO_RESULTADO.items()
        if id_meta != ID_META_CAMPANHA_AUSENTE
        and id_meta not in CAMPANHAS_SEM_ACAO_RESULTADO
    }


def test_regiao_sem_acao_de_fora_da_meta_fica_sem_linha_e_nao_com_zero(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    com_insights: EmpresaTeste,
) -> None:
    # Cadastros e compras não vêm na região (R-23), e a carga não completa
    # com zero: a falta é "não disponível" na leitura (ADR-0011).
    sobrescrever_com_interacoes(conexao_operador, com_insights.empresa_id)
    executar_quebras(conectar_etl, com_insights.empresa_id, ler_fixtures())

    acoes = ler_acoes(conexao_operador, com_insights.empresa_id)
    na_regiao = {id_meta for id_meta, tipo, _, _ in acoes if tipo == "regiao"}
    assert na_regiao == CAMPANHAS_SEM_ACAO_RESULTADO
    assert all(quantidade > 0 for *_, quantidade in acoes)


def test_sobrescrita_do_resultado_muda_a_acao_gravada(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    com_insights: EmpresaTeste,
) -> None:
    # A sobrescrita vence o catálogo (RF-49): a campanha de cadastros passa
    # a ter os cliques no link como resultado nas quebras recarregadas.
    conexao_operador.execute(
        "INSERT INTO normalizado.sobrescrita_resultado_campanha"
        " (empresa_id, campanha_id, metrica_resultado, metrica_kpi)"
        " SELECT empresa_id, id, 'cliques_link', 'cpc' FROM normalizado.campanha"
        " WHERE empresa_id = %s AND id_meta = %s",
        (com_insights.empresa_id, ID_META_CAMPANHA_CADASTROS),
    )

    executar_quebras(conectar_etl, com_insights.empresa_id, ler_fixtures())

    tipos = {
        tipo
        for id_meta, _, tipo, _ in ler_acoes(conexao_operador, com_insights.empresa_id)
        if id_meta == ID_META_CAMPANHA_CADASTROS
    }
    assert tipos == {"link_click"}


def test_thruplay_da_campanha_de_thruplay_vira_a_acao_da_quebra(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    com_insights: EmpresaTeste,
) -> None:
    # O ThruPlay é o resultado das campanhas de ThruPlay e vem fora de
    # actions; a carga grava o tipo que o catálogo lê (REQUIREMENTS §7.2;
    # ADR-0007). As fixtures não o trazem, e o teste o acrescenta.
    fixtures = ler_fixtures()
    com_thruplay = [
        linha
        for linha in listar_linhas(fixtures, "idade_genero")
        if linha["campaign_id"] in CAMPANHAS_SEM_ACAO_RESULTADO
    ]
    for linha in com_thruplay:
        linha["video_thruplay_watched_actions"] = [
            {"action_type": "video_view", "value": "7"}
        ]

    status = executar_quebras(conectar_etl, com_insights.empresa_id, fixtures)

    assert status is StatusExecucao.SUCESSO
    acoes = [
        acao
        for acao in ler_acoes(conexao_operador, com_insights.empresa_id)
        if acao[0] in CAMPANHAS_SEM_ACAO_RESULTADO
    ]
    assert len(acoes) == len(com_thruplay)
    assert set(acoes) == {
        (id_meta, "idade_genero", "video_thruplay_watched_actions", 7)
        for id_meta in {linha["campaign_id"] for linha in com_thruplay}
    }


def test_campanha_ausente_do_banco_e_lida_pelo_id_antes_das_quebras(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # Sem os insights diários, a campanha do anúncio excluído não está no
    # banco: a FK recusaria a quebra. Lida pelo ID, ela entra sem conjunto,
    # antes das quebras.
    status = executar_quebras(
        conectar_etl, cadastrada.empresa_id, ler_fixtures(), com_campanha=True
    )

    assert status is StatusExecucao.SUCESSO
    da_campanha = [
        linha
        for linha in ler_quebras(conexao_operador, cadastrada.empresa_id)
        if linha[0] == ID_META_CAMPANHA_AUSENTE
    ]
    assert len(da_campanha) == LINHAS_CAMPANHA_AUSENTE
    # Sem compras na resposta, a campanha de vendas fica sem ações, e os
    # cliques que vieram não entram.
    assert {linha[8] for linha in da_campanha} == {None}
    # Cada resposta vai para o bruto com o fim da janela, na execução das
    # quebras (RF-09, RF-21).
    respostas = conexao_operador.execute(
        "SELECT endpoint, data_referencia, count(*) FROM bruto.resposta_api"
        " WHERE empresa_id = %s AND execucao_id IN ("
        "  SELECT execucao_id FROM normalizado.quebra_diaria_campanha"
        "  WHERE empresa_id = %s)"
        " GROUP BY 1, 2 ORDER BY 1",
        (cadastrada.empresa_id, cadastrada.empresa_id),
    ).fetchall()
    assert respostas == [("insights", FIM, 3), ("objeto", FIM, 1)]


def test_reprocessamento_com_a_mesma_resposta_produz_estado_identico(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    com_insights: EmpresaTeste,
) -> None:
    # Critério do RF-17, pelas colunas de negócio, sem a chave substituta.
    executar_quebras(conectar_etl, com_insights.empresa_id, ler_fixtures())
    antes = ler_quebras(conexao_operador, com_insights.empresa_id)

    status = executar_quebras(conectar_etl, com_insights.empresa_id, ler_fixtures())

    assert status is StatusExecucao.SUCESSO
    assert ler_quebras(conexao_operador, com_insights.empresa_id) == antes
    assert len(antes) == LINHAS_QUEBRA


def test_reprocessamento_troca_a_janela_e_preserva_os_dias_fora_dela(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    com_insights: EmpresaTeste,
) -> None:
    # A categoria que some na revisão sai do banco com as ações dela, e a
    # quebra de um dia fora da janela fica (ADR-0009 §5).
    executar_quebras(conectar_etl, com_insights.empresa_id, ler_fixtures())
    conexao_operador.execute(
        "INSERT INTO normalizado.quebra_diaria_campanha"
        " (empresa_id, campanha_id, data, tipo_quebra, categoria, investimento,"
        "  impressoes, alcance, execucao_id)"
        " SELECT empresa_id, campanha_id, '2026-09-30', tipo_quebra, categoria,"
        "  investimento, impressoes, alcance, execucao_id"
        " FROM normalizado.quebra_diaria_campanha"
        " WHERE empresa_id = %s AND tipo_quebra = 'regiao' LIMIT 1",
        (com_insights.empresa_id,),
    )
    fixtures = ler_fixtures()
    removida = listar_linhas(fixtures, "idade_genero").pop(0)

    status = executar_quebras(conectar_etl, com_insights.empresa_id, fixtures)

    assert status is StatusExecucao.SUCESSO
    linhas = ler_quebras(conexao_operador, com_insights.empresa_id)
    assert not any(
        linha[:5]
        == (
            removida["campaign_id"],
            date.fromisoformat(removida["date_start"]),
            "idade_genero",
            removida["age"],
            removida["gender"],
        )
        for linha in linhas
    )
    assert sum(linha[1] == date(2026, 9, 30) for linha in linhas) == 1
    assert len({linha[:5] for linha in linhas}) == LINHAS_QUEBRA


def test_acao_que_some_na_revisao_sai_e_a_categoria_fica(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    com_insights: EmpresaTeste,
) -> None:
    # Critério do RF-17 para a tabela longa: a categoria continua na
    # resposta, sem a ação do resultado, e a ação antiga não fica órfã.
    sobrescrever_com_interacoes(conexao_operador, com_insights.empresa_id)
    executar_quebras(conectar_etl, com_insights.empresa_id, ler_fixtures())
    fixtures = ler_fixtures()
    revista = listar_linhas(fixtures, "regiao")[0]
    grao = (
        revista["campaign_id"],
        date.fromisoformat(revista["date_start"]),
        "regiao",
        revista["region"],
        None,
    )
    antes = [
        linha
        for linha in ler_quebras(conexao_operador, com_insights.empresa_id)
        if linha[:5] == grao
    ]
    assert [linha[8] for linha in antes] == ["post_engagement"]
    revista["actions"] = [
        item for item in revista["actions"] if item["action_type"] != "post_engagement"
    ]

    status = executar_quebras(conectar_etl, com_insights.empresa_id, fixtures)

    assert status is StatusExecucao.SUCESSO
    linhas = [
        linha
        for linha in ler_quebras(conexao_operador, com_insights.empresa_id)
        if linha[:5] == grao
    ]
    assert len(linhas) == 1
    assert linhas[0][8:] == (None, None, None)


def test_quebra_recusada_falha_a_empresa_sem_desfazer_a_carga_anterior(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    com_insights: EmpresaTeste,
) -> None:
    # Uma categoria repetida falha a transformação dentro da transação: o
    # DELETE da janela e o bruto da execução voltam com o rollback (RF-18).
    executar_quebras(conectar_etl, com_insights.empresa_id, ler_fixtures())
    antes = ler_quebras(conexao_operador, com_insights.empresa_id)
    fixtures = ler_fixtures()
    linhas = listar_linhas(fixtures, "regiao")
    linhas.append(copy.deepcopy(linhas[0]))

    status = executar_quebras(conectar_etl, com_insights.empresa_id, fixtures)

    assert status is StatusExecucao.FALHA
    assert ler_quebras(conexao_operador, com_insights.empresa_id) == antes
    erro = conexao_operador.execute(
        "SELECT erro FROM normalizado.execucao_carga"
        " WHERE empresa_id = %s AND status = 'falha'",
        (com_insights.empresa_id,),
    ).fetchone()[0]
    assert "repetidas" in erro
    assert "995000000000000002" not in erro
