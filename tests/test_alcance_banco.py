"""Prova, contra o banco local e com a API simulada pelas fixtures, a extração
e a carga do alcance por semana, mês e ano de ponta a ponta, pela execução
por empresa (RF-04, RF-09, RF-17; ADR-0006). O cadastro da conta é carregado
antes pela tarefa de cadastro, salvo o anúncio excluído, que só existe pelo
ID. Exige o banco local de pé.
"""

from collections.abc import Callable, Iterator
from datetime import date
from uuid import UUID

import psycopg
import pytest
import responses
from responses.registries import OrderedRegistry

from etl.alcance import ErroCalendario, TarefaAlcancePeriodo, ler_periodos_janela
from etl.cadastro import TarefaCadastro
from etl.cliente_api_meta import ClienteApiMeta
from etl.execucao import StatusExecucao, TarefaCarga, executar_empresa
from etl.extracao import PeriodoAlcance, TipoPeriodo
from tests import cadastro_exemplo
from tests.alcance_exemplo import (
    FIM,
    INICIO,
    NIVEIS,
    PERIODOS,
    Fixtures,
    ler_fixtures,
    listar_linhas,
    simular_alcance,
)
from tests.cadastro_exemplo import ID_META_CONTA
from tests.carga_exemplo import ler_estado
from tests.conftest import LIMPEZA_EMPRESA, EmpresaTeste, criar_empresa

pytestmark = pytest.mark.integracao

NOME_EMPRESA = "Empresa Exemplo Alcance"
TOKEN = "EAAFicticio0000000000000000000000000000000000ZZ"
ID_META_CAMPANHA_DESCONHECIDA = "995000000000000098"
ID_META_OUTRA_CONTA = "995000000000099"
# Linhas por consulta nas fixtures: 8 da conta e 12 de cada outro nível.
LINHAS_ALCANCE = 32
# As 9 consultas de alcance e a leitura pelo ID do anúncio excluído, do
# conjunto e da campanha dele.
RESPOSTAS_BRUTAS = 12

# Cada linha com o nível e o ID da Meta da entidade, nulo na da conta.
LER_ALCANCE = """
SELECT
  CASE
    WHEN alcance.conta_anuncio_id IS NOT NULL THEN 'conta'
    WHEN alcance.campanha_id IS NOT NULL THEN 'campanha'
    ELSE 'anuncio'
  END,
  coalesce(campanha.id_meta, anuncio.id_meta),
  alcance.tipo_periodo, alcance.inicio_periodo, alcance.fim_periodo,
  alcance.alcance, alcance.impressoes
FROM normalizado.alcance_periodo AS alcance
LEFT JOIN normalizado.campanha AS campanha
  ON campanha.empresa_id = alcance.empresa_id AND campanha.id = alcance.campanha_id
LEFT JOIN normalizado.anuncio AS anuncio
  ON anuncio.empresa_id = alcance.empresa_id AND anuncio.id = alcance.anuncio_id
WHERE alcance.empresa_id = %s
"""

type LinhaAlcance = tuple[str, str | None, str, date, date, int | None, int | None]


@pytest.fixture
def empresa(conexao_operador: psycopg.Connection) -> Iterator[EmpresaTeste]:
    apagar_empresa_alcance(conexao_operador)
    criada = criar_empresa(conexao_operador, NOME_EMPRESA, ID_META_CONTA, indice=1)
    try:
        yield criada
    finally:
        apagar_empresa_alcance(conexao_operador)


def apagar_empresa_alcance(conexao: psycopg.Connection) -> None:
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
    """A empresa com o cadastro da conta já carregado, como na execução
    diária."""
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


def executar_alcance(
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    fixtures: Fixtures,
    *,
    com_entidades: bool = True,
) -> StatusExecucao:
    return executar(
        conectar,
        empresa_id,
        "diaria",
        lambda cliente: TarefaAlcancePeriodo(conectar, cliente, INICIO, FIM),
        lambda api: simular_alcance(api, fixtures, com_entidades=com_entidades),
    )


def ler_alcance(conexao: psycopg.Connection, empresa_id: UUID) -> set[LinhaAlcance]:
    return set(conexao.execute(LER_ALCANCE, (empresa_id,)).fetchall())


def listar_esperadas(fixtures: Fixtures) -> set[LinhaAlcance]:
    """As linhas de todas as respostas, como a carga deve gravá-las."""
    esperadas = set()
    for _, nivel, campos in NIVEIS:
        campo_id = campos.split(",")[0] if nivel != "conta" else None
        for tipo, *_ in PERIODOS:
            for linha in listar_linhas(fixtures, nivel, tipo):
                esperadas.add(
                    (
                        nivel,
                        linha[campo_id] if campo_id else None,
                        tipo,
                        date.fromisoformat(linha["date_start"]),
                        date.fromisoformat(linha["date_stop"]),
                        int(linha["reach"]),
                        int(linha["impressions"]),
                    )
                )
    return esperadas


def test_semanas_gravadas_comecam_sempre_numa_segunda_feira(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # Critério da #24. A janela começa numa terça-feira, e o dia da semana
    # vem do calendário, a única fonte do agrupamento (CLAUDE.md §5).
    status = executar_alcance(conectar_etl, cadastrada.empresa_id, ler_fixtures())

    assert status is StatusExecucao.SUCESSO
    dia_inicio = conexao_operador.execute(
        "SELECT dia_semana_iso FROM normalizado.calendario WHERE data = %s",
        (INICIO,),
    ).fetchone()[0]
    assert dia_inicio != 1
    dias_semana = conexao_operador.execute(
        "SELECT calendario.dia_semana_iso, count(*)"
        " FROM normalizado.alcance_periodo AS alcance"
        " JOIN normalizado.calendario AS calendario"
        "  ON calendario.data = alcance.inicio_periodo"
        " WHERE alcance.empresa_id = %s AND alcance.tipo_periodo = 'semana'"
        " GROUP BY calendario.dia_semana_iso",
        (cadastrada.empresa_id,),
    ).fetchall()
    assert dias_semana == [(1, 17)]


def test_semana_que_nao_comeca_na_segunda_feira_e_recusada_sem_gravar_nada(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # Um bloco desalinhado da API não entra como semana ISO: a carga falha
    # inteira, e o alcance da carga anterior, que o DELETE já tinha tirado,
    # volta com o rollback (RF-18).
    executar_alcance(conectar_etl, cadastrada.empresa_id, ler_fixtures())
    antes = ler_estado(conexao_operador, [cadastrada.empresa_id])
    fixtures = ler_fixtures()
    listar_linhas(fixtures, "conta", "semana")[0].update(
        date_start="2026-03-10", date_stop="2026-03-16"
    )

    status = executar_alcance(
        conectar_etl, cadastrada.empresa_id, fixtures, com_entidades=False
    )

    assert status is StatusExecucao.FALHA
    assert ler_estado(conexao_operador, [cadastrada.empresa_id]) == antes
    assert antes["alcance_periodo"][0] == LINHAS_ALCANCE
    erro = conexao_operador.execute(
        "SELECT erro FROM normalizado.execucao_carga"
        " WHERE empresa_id = %s AND status = 'falha'",
        (cadastrada.empresa_id,),
    ).fetchone()[0]
    assert "alcance_periodo_semana_check" in erro


def test_alcance_da_campanha_em_marco_e_igual_ao_da_api_para_o_mes_inteiro(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # Critério do RF-04: o mês no banco é o intervalo de 01/03 a 31/03/2026
    # da API sem quebra diária, e não a soma dos dias nem das semanas.
    fixtures = ler_fixtures()

    executar_alcance(conectar_etl, cadastrada.empresa_id, fixtures)

    no_banco = {
        id_meta: (alcance, impressoes)
        for nivel, id_meta, tipo, inicio, fim, alcance, impressoes in ler_alcance(
            conexao_operador, cadastrada.empresa_id
        )
        if (nivel, tipo, inicio, fim)
        == ("campanha", "mes", date(2026, 3, 1), date(2026, 3, 31))
    }
    na_api = {
        linha["campaign_id"]: (int(linha["reach"]), int(linha["impressions"]))
        for linha in fixtures["alcance_campanha_marco"]["corpo"]["data"]
    }
    assert no_banco == na_api
    semanas = sum(
        int(linha["reach"])
        for linha in listar_linhas(fixtures, "campanha", "semana")
        if linha["campaign_id"] == "995000000000000003"
        and linha["date_start"].startswith("2026-03")
    )
    assert no_banco["995000000000000003"][0] != semanas


def test_alcance_vem_por_conta_campanha_e_anuncio_como_a_api_agregou(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # As três entidades em cada tipo de período, com o anúncio excluído e a
    # campanha dele, lidos pelo ID antes do alcance (ADR-0009 §5).
    fixtures = ler_fixtures()

    status = executar_alcance(conectar_etl, cadastrada.empresa_id, fixtures)

    assert status is StatusExecucao.SUCESSO
    gravadas = ler_alcance(conexao_operador, cadastrada.empresa_id)
    assert gravadas == listar_esperadas(fixtures)
    assert len(gravadas) == LINHAS_ALCANCE


def test_reprocessamento_com_a_mesma_resposta_produz_estado_identico(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # Critério do RF-17. Na segunda execução, o anúncio excluído já está no
    # banco e não é lido de novo: uma leitura pelo ID falharia a execução.
    executar_alcance(conectar_etl, cadastrada.empresa_id, ler_fixtures())
    antes = ler_estado(conexao_operador, [cadastrada.empresa_id])

    status = executar_alcance(
        conectar_etl, cadastrada.empresa_id, ler_fixtures(), com_entidades=False
    )

    assert status is StatusExecucao.SUCESSO
    assert ler_estado(conexao_operador, [cadastrada.empresa_id]) == antes
    assert antes["alcance_periodo"][0] == LINHAS_ALCANCE


def test_reprocessamento_troca_os_periodos_que_tocam_a_janela_e_preserva_os_demais(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # A semana que some na revisão deixa de existir e a semana em andamento
    # muda de valor. Ficam os períodos de outras execuções fora do escopo:
    # antes do since e depois do fim da janela, em cada tipo, e os da outra
    # conta da empresa nos mesmos períodos da janela (ADR-0009 §5).
    executar_alcance(conectar_etl, cadastrada.empresa_id, ler_fixtures())
    outra_conta = conexao_operador.execute(
        "INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, situacao)"
        " VALUES (%s, %s, 'inativa') RETURNING id",
        (cadastrada.empresa_id, ID_META_OUTRA_CONTA),
    ).fetchone()[0]
    preservadas = {
        (cadastrada.conta_id, "semana", date(2026, 3, 2), date(2026, 3, 8)),
        (cadastrada.conta_id, "semana", date(2026, 4, 13), date(2026, 4, 19)),
        (cadastrada.conta_id, "mes", date(2026, 2, 1), date(2026, 2, 28)),
        (cadastrada.conta_id, "ano", date(2025, 1, 1), date(2025, 12, 31)),
        (outra_conta, "semana", date(2026, 3, 9), date(2026, 3, 15)),
        (outra_conta, "mes", date(2026, 3, 1), date(2026, 3, 31)),
        (outra_conta, "ano", date(2026, 1, 1), FIM),
    }
    for conta_id, tipo, inicio, fim in preservadas:
        conexao_operador.execute(
            "INSERT INTO normalizado.alcance_periodo"
            " (empresa_id, conta_anuncio_id, tipo_periodo, inicio_periodo,"
            "  fim_periodo, alcance, impressoes, execucao_id)"
            " SELECT empresa_id, %s, %s, %s, %s, 7000, 12000, execucao_id"
            " FROM normalizado.alcance_periodo WHERE empresa_id = %s LIMIT 1",
            (conta_id, tipo, inicio, fim, cadastrada.empresa_id),
        )
    fixtures = ler_fixtures()
    removida = listar_linhas(fixtures, "campanha", "semana").pop(1)
    listar_linhas(fixtures, "anuncio", "semana")[-1]["reach"] = "1712"

    status = executar_alcance(
        conectar_etl, cadastrada.empresa_id, fixtures, com_entidades=False
    )

    assert status is StatusExecucao.SUCESSO
    contas = conexao_operador.execute(
        "SELECT conta_anuncio_id, tipo_periodo, inicio_periodo, fim_periodo"
        " FROM normalizado.alcance_periodo"
        " WHERE empresa_id = %s AND alcance = 7000 AND impressoes = 12000",
        (cadastrada.empresa_id,),
    ).fetchall()
    assert set(contas) == preservadas
    da_conta = {
        linha
        for linha in ler_alcance(conexao_operador, cadastrada.empresa_id)
        if linha[5:] != (7000, 12000)
    }
    assert da_conta == listar_esperadas(fixtures)
    assert not any(
        linha[:4] == ("campanha", removida["campaign_id"], "semana", date(2026, 3, 16))
        for linha in da_conta
    )
    assert ("anuncio", "995000000000000015", "semana", FIM, FIM, 1712, 2240) in (
        da_conta
    )


def test_campanha_fora_do_banco_falha_sem_gravar_nada_nem_citar_o_id(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    # A FK recusaria a linha; a carga falha antes, e o erro guardado não
    # traz o ID (RNF-17).
    fixtures = ler_fixtures()
    listar_linhas(fixtures, "campanha", "semana")[0]["campaign_id"] = (
        ID_META_CAMPANHA_DESCONHECIDA
    )

    status = executar_alcance(conectar_etl, cadastrada.empresa_id, fixtures)

    assert status is StatusExecucao.FALHA
    assert ler_alcance(conexao_operador, cadastrada.empresa_id) == set()
    erro = conexao_operador.execute(
        "SELECT erro FROM normalizado.execucao_carga"
        " WHERE empresa_id = %s AND status = 'falha'",
        (cadastrada.empresa_id,),
    ).fetchone()[0]
    assert "fora da conta" in erro
    assert ID_META_CAMPANHA_DESCONHECIDA not in erro


def test_cada_resposta_vai_para_o_bruto_com_o_fim_da_janela_e_conta_no_registro(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    cadastrada: EmpresaTeste,
) -> None:
    executar_alcance(conectar_etl, cadastrada.empresa_id, ler_fixtures())

    respostas = conexao_operador.execute(
        "SELECT resposta.endpoint, resposta.data_referencia, count(*)"
        " FROM bruto.resposta_api AS resposta"
        " JOIN normalizado.execucao_carga AS execucao"
        "  ON execucao.empresa_id = resposta.empresa_id"
        "  AND execucao.id = resposta.execucao_id"
        " JOIN normalizado.contagem_linhas_execucao AS contagem"
        "  ON contagem.empresa_id = execucao.empresa_id"
        "  AND contagem.execucao_id = execucao.id"
        "  AND contagem.tabela = 'alcance_periodo'"
        " WHERE resposta.empresa_id = %s AND contagem.linhas = %s"
        " GROUP BY 1, 2 ORDER BY 1",
        (cadastrada.empresa_id, LINHAS_ALCANCE),
    ).fetchall()
    assert respostas == [("insights", FIM, 9), ("objeto", FIM, 3)]
    assert sum(linhas for *_, linhas in respostas) == RESPOSTAS_BRUTAS


def test_periodos_da_janela_vem_do_calendario(
    conexao_operador: psycopg.Connection,
) -> None:
    # A semana começa na segunda-feira e o mês no dia 1 do primeiro dia da
    # janela; o ano é consultado para cada ano que a janela toca, todos
    # cortados no último dia (ADR-0006).
    assert ler_periodos_janela(conexao_operador, INICIO, FIM) == [
        PeriodoAlcance(TipoPeriodo(tipo), inicio, fim) for tipo, inicio, fim in PERIODOS
    ]
    assert ler_periodos_janela(
        conexao_operador, date(2025, 12, 20), date(2026, 1, 16)
    ) == [
        PeriodoAlcance(TipoPeriodo.SEMANA, date(2025, 12, 15), date(2026, 1, 16)),
        PeriodoAlcance(TipoPeriodo.MES, date(2025, 12, 1), date(2026, 1, 16)),
        PeriodoAlcance(TipoPeriodo.ANO, date(2025, 1, 1), date(2025, 12, 31)),
        PeriodoAlcance(TipoPeriodo.ANO, date(2026, 1, 1), date(2026, 1, 16)),
    ]


def test_janela_fora_do_calendario_e_recusada(
    conexao_operador: psycopg.Connection,
) -> None:
    with pytest.raises(ErroCalendario):
        ler_periodos_janela(conexao_operador, date(2035, 12, 20), date(2036, 1, 16))
