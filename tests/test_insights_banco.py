"""Prova, contra o banco local e com a API simulada pelas fixtures, a extração
e a carga dos insights diários por anúncio e das ações de ponta a ponta, pela
execução por empresa (RF-02, RF-09, RF-12, RF-17). O cadastro da conta é
carregado antes pela tarefa de cadastro, salvo o anúncio excluído, que só
existe pelo ID. Exige o banco local de pé.
"""

from collections import Counter
from collections.abc import Callable, Iterator
from datetime import date
from decimal import Decimal
from uuid import UUID

import psycopg
import pytest
import responses
from responses.registries import OrderedRegistry

from etl.cadastro import TarefaCadastro
from etl.carga import ErroAnuncioAusente
from etl.cliente_api_meta import ClienteApiMeta, Endpoint
from etl.execucao import StatusExecucao, TarefaCarga, executar_empresa
from etl.extracao import Consulta, EntidadesExtraidas
from etl.insights import InsightsContaExtraidos, TarefaInsightsDiarios
from tests import cadastro_exemplo
from tests.cadastro_exemplo import ID_META_CONTA
from tests.carga_exemplo import ler_estado
from tests.conftest import LIMPEZA_EMPRESA, EmpresaTeste, criar_empresa
from tests.insights_exemplo import (
    FIM,
    ID_META_ANUNCIO_AUSENTE,
    INICIO,
    NOMES_PAGINAS,
    Fixtures,
    ler_fixtures,
    listar_linhas,
    montar_parametros_insights,
    simular_insights,
)

pytestmark = pytest.mark.integracao

NOME_EMPRESA = "Empresa Exemplo Insights"
TOKEN = "EAAFicticio0000000000000000000000000000000000ZZ"
ID_META_ANUNCIO_VENDAS = "995000000000000020"
# Diferença máxima entre a soma por conta no banco e a API no nível de conta
# (RF-02).
TOLERANCIA_INVESTIMENTO = Decimal("0.01")

# O investimento por dia da conta, pelo caminho até ela: os fatos não guardam
# a conta (ADR-0009 §2).
SOMAR_INVESTIMENTO_POR_DIA = """
SELECT metrica.data, sum(metrica.investimento)
FROM normalizado.metrica_diaria_anuncio AS metrica
JOIN normalizado.anuncio AS anuncio
  ON anuncio.empresa_id = metrica.empresa_id AND anuncio.id = metrica.anuncio_id
JOIN normalizado.conjunto_anuncio AS conjunto
  ON conjunto.empresa_id = anuncio.empresa_id AND conjunto.id = anuncio.conjunto_anuncio_id
JOIN normalizado.campanha AS campanha
  ON campanha.empresa_id = conjunto.empresa_id AND campanha.id = conjunto.campanha_id
WHERE metrica.empresa_id = %s AND campanha.conta_anuncio_id = %s
GROUP BY metrica.data
ORDER BY metrica.data
"""

LER_ACOES_DO_ANUNCIO = """
SELECT acao.tipo_acao, acao.quantidade, acao.valor
FROM normalizado.acao_diaria_anuncio AS acao
JOIN normalizado.anuncio AS anuncio
  ON anuncio.empresa_id = acao.empresa_id AND anuncio.id = acao.anuncio_id
WHERE acao.empresa_id = %s AND anuncio.id_meta = %s AND acao.data = %s
ORDER BY acao.tipo_acao
"""


@pytest.fixture
def empresa(conexao_operador: psycopg.Connection) -> Iterator[EmpresaTeste]:
    apagar_empresa_insights(conexao_operador)
    criada = criar_empresa(conexao_operador, NOME_EMPRESA, ID_META_CONTA, indice=1)
    try:
        yield criada
    finally:
        apagar_empresa_insights(conexao_operador)


def apagar_empresa_insights(conexao: psycopg.Connection) -> None:
    for (empresa_id,) in conexao.execute(
        "SELECT id FROM normalizado.empresa WHERE nome = %s", (NOME_EMPRESA,)
    ).fetchall():
        with conexao.transaction():
            for comando in LIMPEZA_EMPRESA:
                conexao.execute(comando, {"empresa_id": empresa_id})


def executar(
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    tipo: str,
    montar_tarefa: Callable[[ClienteApiMeta], TarefaCarga],
    simular: Callable[[responses.RequestsMock], None],
) -> StatusExecucao:
    """Uma execução com a API simulada. Uma chamada não simulada falha a
    execução."""
    with responses.RequestsMock(registry=OrderedRegistry) as api:
        simular(api)
        cliente = ClienteApiMeta(TOKEN, dormir=lambda segundos: None)
        return executar_empresa(conectar, empresa_id, tipo, montar_tarefa(cliente))


@pytest.fixture
def cadastrada(
    conectar_etl: Callable[[], psycopg.Connection], empresa: EmpresaTeste
) -> EmpresaTeste:
    """A empresa com o cadastro da conta já carregado, como depois da
    execução diária."""
    status = executar(
        conectar_etl,
        empresa.empresa_id,
        "diaria",
        lambda cliente: TarefaCadastro(conectar_etl, cliente),
        lambda api: cadastro_exemplo.simular_cadastro(
            api, cadastro_exemplo.ler_fixtures()
        ),
    )
    assert status is StatusExecucao.SUCESSO
    return empresa


def executar_insights(
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    fixtures: Fixtures,
    *,
    com_entidades: bool = True,
) -> StatusExecucao:
    return executar(
        conectar,
        empresa_id,
        "horaria",
        lambda cliente: TarefaInsightsDiarios(conectar, cliente, INICIO, FIM),
        lambda api: simular_insights(api, fixtures, com_entidades=com_entidades),
    )


def test_soma_do_investimento_por_conta_bate_com_a_api_no_nivel_de_conta(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # Critério do RF-02, para cada dia fechado da resposta da conta.
    fixtures = ler_fixtures()

    status = executar_insights(conectar_etl, cadastrada.empresa_id, fixtures)

    assert status is StatusExecucao.SUCESSO
    no_banco = dict(
        conexao_operador.execute(
            SOMAR_INVESTIMENTO_POR_DIA, (cadastrada.empresa_id, cadastrada.conta_id)
        ).fetchall()
    )
    na_api = {
        date.fromisoformat(linha["date_start"]): Decimal(linha["spend"])
        for linha in fixtures["insights_diarios_conta"]["corpo"]["data"]
    }
    assert no_banco.keys() == na_api.keys()
    for dia, investimento in na_api.items():
        assert abs(no_banco[dia] - investimento) <= TOLERANCIA_INVESTIMENTO


def test_soma_por_tipo_de_acao_no_banco_e_igual_a_da_resposta_bruta(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # Critério do RF-12, na quantidade (actions) e no valor (action_values).
    fixtures = ler_fixtures()
    esperadas: Counter[tuple[str, str]] = Counter()
    for linha in listar_linhas(fixtures):
        for lista, medida, tipo in (
            ("actions", "quantidade", int),
            ("action_values", "valor", Decimal),
        ):
            for item in linha.get(lista, ()):
                esperadas[(medida, item["action_type"])] += tipo(item["value"])

    executar_insights(conectar_etl, cadastrada.empresa_id, fixtures)

    obtidas: Counter[tuple[str, str]] = Counter()
    for tipo_acao, quantidade, valor in conexao_operador.execute(
        "SELECT tipo_acao, sum(quantidade), sum(valor)"
        " FROM normalizado.acao_diaria_anuncio WHERE empresa_id = %s"
        " GROUP BY tipo_acao",
        (cadastrada.empresa_id,),
    ).fetchall():
        if quantidade is not None:
            obtidas[("quantidade", tipo_acao)] = quantidade
        if valor is not None:
            obtidas[("valor", tipo_acao)] = valor
    assert obtidas == esperadas


def test_resposta_com_12_itens_em_actions_gera_12_linhas_no_banco(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # Critério do RF-12.
    fixtures = ler_fixtures()
    linha = listar_linhas(fixtures)[2]
    assert (linha["ad_id"], len(linha["actions"])) == (ID_META_ANUNCIO_VENDAS, 12)

    executar_insights(conectar_etl, cadastrada.empresa_id, fixtures)

    acoes = conexao_operador.execute(
        LER_ACOES_DO_ANUNCIO, (cadastrada.empresa_id, ID_META_ANUNCIO_VENDAS, INICIO)
    ).fetchall()
    assert len(acoes) == 12


def test_tipo_de_acao_que_some_na_revisao_deixa_de_existir_apos_o_reprocessamento(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # Critério da #22, pelo RF-17: a Meta deixa de devolver a compra do dia
    # na revisão, e o reprocessamento da mesma janela a tira do banco.
    fixtures = ler_fixtures()
    executar_insights(conectar_etl, cadastrada.empresa_id, fixtures)

    def ler_tipos() -> set[str]:
        linhas = conexao_operador.execute(
            LER_ACOES_DO_ANUNCIO,
            (cadastrada.empresa_id, ID_META_ANUNCIO_VENDAS, INICIO),
        ).fetchall()
        return {tipo for tipo, _, _ in linhas}

    assert "omni_purchase" in ler_tipos()
    linha = listar_linhas(fixtures)[2]
    for lista in ("actions", "action_values"):
        linha[lista] = [i for i in linha[lista] if i["action_type"] != "omni_purchase"]

    status = executar_insights(
        conectar_etl, cadastrada.empresa_id, fixtures, com_entidades=False
    )

    assert status is StatusExecucao.SUCESSO
    tipos = ler_tipos()
    assert "omni_purchase" not in tipos
    assert len(tipos) == 11


def test_reprocessamento_com_a_mesma_resposta_produz_estado_identico(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # Critério do RF-17. Na segunda execução, o anúncio excluído já está no
    # banco e não é lido de novo: uma leitura pelo ID falharia a execução.
    executar_insights(conectar_etl, cadastrada.empresa_id, ler_fixtures())
    antes = ler_estado(conexao_operador, [cadastrada.empresa_id])

    status = executar_insights(
        conectar_etl, cadastrada.empresa_id, ler_fixtures(), com_entidades=False
    )

    assert status is StatusExecucao.SUCESSO
    assert ler_estado(conexao_operador, [cadastrada.empresa_id]) == antes
    assert antes["acao_diaria_anuncio"][0] > 0


def test_anuncio_ausente_do_banco_entra_com_conjunto_campanha_e_criativo(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # ADR-0009 §5: o anúncio excluído, que as arestas não devolvem (R-38), é
    # lido pelo ID antes dos fatos, que a FK recusaria sem ele.
    executar_insights(conectar_etl, cadastrada.empresa_id, ler_fixtures())

    anuncio = conexao_operador.execute(
        "SELECT anuncio.status, conjunto.id_meta, campanha.id_meta,"
        " campanha.conta_anuncio_id, criativo.id_meta, count(metrica.data)"
        " FROM normalizado.anuncio AS anuncio"
        " JOIN normalizado.conjunto_anuncio AS conjunto"
        "  ON conjunto.empresa_id = anuncio.empresa_id"
        "  AND conjunto.id = anuncio.conjunto_anuncio_id"
        " JOIN normalizado.campanha AS campanha"
        "  ON campanha.empresa_id = conjunto.empresa_id"
        "  AND campanha.id = conjunto.campanha_id"
        " JOIN normalizado.criativo AS criativo"
        "  ON criativo.empresa_id = anuncio.empresa_id"
        "  AND criativo.id = anuncio.criativo_id"
        " JOIN normalizado.metrica_diaria_anuncio AS metrica"
        "  ON metrica.empresa_id = anuncio.empresa_id"
        "  AND metrica.anuncio_id = anuncio.id"
        " WHERE anuncio.empresa_id = %s AND anuncio.id_meta = %s"
        " GROUP BY 1, 2, 3, 4, 5",
        (cadastrada.empresa_id, ID_META_ANUNCIO_AUSENTE),
    ).fetchone()
    assert anuncio == (
        "DELETED",
        "995000000000000025",
        "995000000000000026",
        cadastrada.conta_id,
        "9950000000000027",
        1,
    )


def test_cada_resposta_vai_para_o_bruto_com_a_execucao_e_o_fim_do_intervalo(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    executar_insights(conectar_etl, cadastrada.empresa_id, ler_fixtures())

    respostas = conexao_operador.execute(
        "SELECT resposta.endpoint, resposta.data_referencia, resposta.conta_anuncio_id"
        " FROM bruto.resposta_api AS resposta"
        " JOIN normalizado.execucao_carga AS execucao"
        "  ON execucao.empresa_id = resposta.empresa_id"
        "  AND execucao.id = resposta.execucao_id"
        " WHERE resposta.empresa_id = %s AND execucao.tipo = 'horaria'"
        " ORDER BY resposta.id",
        (cadastrada.empresa_id,),
    ).fetchall()
    assert respostas == [
        ("insights", FIM, cadastrada.conta_id),
        ("insights", FIM, cadastrada.conta_id),
        ("objeto", FIM, cadastrada.conta_id),
        ("objeto", FIM, cadastrada.conta_id),
        ("objeto", FIM, cadastrada.conta_id),
    ]


def test_registro_de_fim_traz_as_linhas_de_metricas_e_acoes(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    fixtures = ler_fixtures()
    acoes = sum(
        len(
            {
                i["action_type"]
                for i in (*linha["actions"], *linha.get("action_values", ()))
            }
        )
        for linha in listar_linhas(fixtures)
    )

    executar_insights(conectar_etl, cadastrada.empresa_id, fixtures)

    contagens = dict(
        conexao_operador.execute(
            "SELECT contagem.tabela, contagem.linhas"
            " FROM normalizado.contagem_linhas_execucao AS contagem"
            " JOIN normalizado.execucao_carga AS execucao"
            "  ON execucao.empresa_id = contagem.empresa_id"
            "  AND execucao.id = contagem.execucao_id"
            " WHERE contagem.empresa_id = %s AND execucao.tipo = 'horaria'",
            (cadastrada.empresa_id,),
        ).fetchall()
    )
    assert contagens["metrica_diaria_anuncio"] == 8
    assert contagens["acao_diaria_anuncio"] == acoes
    assert contagens["anuncio"] == 1
    assert contagens["resposta_api"] == 5


def test_anuncio_fora_do_banco_sem_leitura_pelo_id_falha_sem_gravar_nada(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # Depois de uma carga, a revisão traz um anúncio que o banco não tem, e a
    # leitura pelo ID não aconteceu: a carga falha, e nem o bruto nem os
    # fatos da carga anterior mudam (RF-18).
    executar_insights(conectar_etl, cadastrada.empresa_id, ler_fixtures())
    antes = ler_estado(conexao_operador, [cadastrada.empresa_id])
    fixtures = ler_fixtures()
    listar_linhas(fixtures)[0]["ad_id"] = "995000000000000099"
    insights = Consulta(
        Endpoint.INSIGHTS,
        montar_parametros_insights(),
        [fixtures[nome]["corpo"] for nome in NOMES_PAGINAS],
    )
    nenhuma = Consulta(Endpoint.OBJETO, {}, [])
    dados = [
        InsightsContaExtraidos(
            cadastrada.conta_id, insights, EntidadesExtraidas(nenhuma, nenhuma, nenhuma)
        )
    ]
    tarefa = TarefaInsightsDiarios(conectar_etl, ClienteApiMeta(TOKEN), INICIO, FIM)

    with conectar_etl() as conexao:
        execucao_id = conexao.execute(
            "INSERT INTO normalizado.execucao_carga (empresa_id, tipo)"
            " VALUES (%s, 'horaria') RETURNING id",
            (cadastrada.empresa_id,),
        ).fetchone()[0]
        with pytest.raises(ErroAnuncioAusente) as erro, conexao.transaction():
            tarefa.carregar(conexao, cadastrada.empresa_id, execucao_id, dados)

    assert "995000000000000099" not in str(erro.value)
    assert ler_estado(conexao_operador, [cadastrada.empresa_id]) == antes
    respostas = conexao_operador.execute(
        "SELECT count(*) FROM bruto.resposta_api WHERE execucao_id = %s",
        (execucao_id,),
    ).fetchone()[0]
    assert respostas == 0
