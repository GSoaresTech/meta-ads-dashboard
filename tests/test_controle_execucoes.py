"""Prova, contra o banco local, que o registro de início da execução persiste
quando a transação da carga sofre rollback, e que a falha fica registrada
depois dele (RF-20; ADR-0009 §5).

Um arquivo pgTAP roda inteiro dentro de uma transação, e esta prova exige
transações confirmadas em separado. Por isso fica aqui, com o marcador
integracao, fora da suíte padrão. Exige o banco local de pé.
"""

from collections.abc import Iterator
from uuid import UUID

import psycopg
import pytest
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.integracao

# O padrão público do Supabase local, exibido por `supabase status`. Fica
# fixo, e não vem do ambiente, para que o teste nunca rode contra produção.
URL_BANCO_LOCAL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
NOME_EMPRESA = "Empresa Teste Integração"
ID_META_CONTA = "990000000000001"
ID_META_CAMPANHA = "990000000000000101"
MENSAGEM_ERRO = "Falha injetada no meio da carga."

# As FKs são NO ACTION (ADR-0009 §1): a limpeza apaga de baixo para cima. As
# tabelas da carga entram para o caso de o rollback não ter acontecido.
LIMPEZA_EMPRESA = (
    "DELETE FROM bruto.resposta_api WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.aviso_execucao WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.contagem_linhas_execucao WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.campanha WHERE empresa_id = %(empresa_id)s",
    "UPDATE normalizado.conta_anuncio SET execucao_id = NULL WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.execucao_carga WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.conta_anuncio WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.empresa WHERE id = %(empresa_id)s",
)


class FalhaInjetada(Exception):
    """Falha no meio da carga, depois de gravar o bruto e as entidades."""


@pytest.fixture
def conexao_operador() -> Iterator[psycopg.Connection]:
    with psycopg.connect(URL_BANCO_LOCAL, autocommit=True) as conexao:
        yield conexao


@pytest.fixture
def conexao_etl() -> Iterator[psycopg.Connection]:
    """Conexão com os privilégios da ETL, em que cada bloco de transação é
    uma transação real, e não um savepoint."""
    with psycopg.connect(URL_BANCO_LOCAL, autocommit=True) as conexao:
        conexao.execute("SET ROLE etl_carga")
        yield conexao


@pytest.fixture
def conta(conexao_operador: psycopg.Connection) -> Iterator[tuple[UUID, UUID]]:
    """Empresa e conta fictícias, confirmadas antes do teste e apagadas no fim."""
    # Uma execução interrompida sem teardown deixaria a conta, e o id_meta
    # repetido faria todo teste seguinte falhar.
    apagar_empresas_remanescentes(conexao_operador)
    with conexao_operador.transaction():
        empresa_id = conexao_operador.execute(
            "INSERT INTO normalizado.empresa (nome) VALUES (%s) RETURNING id",
            (NOME_EMPRESA,),
        ).fetchone()[0]
        conta_id = conexao_operador.execute(
            "INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)"
            " VALUES (%s, %s) RETURNING id",
            (empresa_id, ID_META_CONTA),
        ).fetchone()[0]
    try:
        yield empresa_id, conta_id
    finally:
        apagar_empresa(conexao_operador, empresa_id)


def apagar_empresas_remanescentes(conexao: psycopg.Connection) -> None:
    linhas = conexao.execute(
        "SELECT id FROM normalizado.empresa WHERE nome = %s", (NOME_EMPRESA,)
    ).fetchall()
    for (empresa_id,) in linhas:
        apagar_empresa(conexao, empresa_id)


def apagar_empresa(conexao: psycopg.Connection, empresa_id: UUID) -> None:
    with conexao.transaction():
        for comando in LIMPEZA_EMPRESA:
            conexao.execute(comando, {"empresa_id": empresa_id})


def registrar_inicio(conexao: psycopg.Connection, empresa_id: UUID) -> UUID:
    with conexao.transaction():
        return conexao.execute(
            "INSERT INTO normalizado.execucao_carga (empresa_id, tipo)"
            " VALUES (%s, 'diaria') RETURNING id",
            (empresa_id,),
        ).fetchone()[0]


def carregar_ate_falhar(
    conexao: psycopg.Connection, empresa_id: UUID, conta_id: UUID, execucao_id: UUID
) -> None:
    """Grava o bruto, a conta, uma campanha e um aviso, e falha antes do fim,
    na ordem da carga do ADR-0009 §5."""
    ids = {"empresa_id": empresa_id, "conta_id": conta_id, "execucao_id": execucao_id}
    with conexao.transaction():
        conexao.execute(
            "INSERT INTO bruto.resposta_api (empresa_id, execucao_id, conta_anuncio_id,"
            " endpoint, parametros, data_referencia, resposta)"
            " VALUES (%(empresa_id)s, %(execucao_id)s, %(conta_id)s, 'act_990000000000001/campaigns',"
            " %(parametros)s, current_date, %(resposta)s)",
            ids
            | {
                "parametros": Jsonb({"fields": "id,name,objective,status"}),
                "resposta": Jsonb({"data": []}),
            },
        )
        conexao.execute(
            "UPDATE normalizado.conta_anuncio SET nome = 'Conta Teste',"
            " fuso_horario = 'America/Sao_Paulo', moeda = 'BRL',"
            " execucao_id = %(execucao_id)s, atualizado_em = now()"
            " WHERE id = %(conta_id)s",
            ids,
        )
        campanha_id = conexao.execute(
            "INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta,"
            " objetivo, status, execucao_id)"
            " VALUES (%(empresa_id)s, %(conta_id)s, %(id_meta)s, 'OBJETIVO_NOVO_DA_META',"
            " 'ACTIVE', %(execucao_id)s) RETURNING id",
            ids | {"id_meta": ID_META_CAMPANHA},
        ).fetchone()[0]
        conexao.execute(
            "INSERT INTO normalizado.aviso_execucao (empresa_id, execucao_id, tipo, campanha_id)"
            " VALUES (%(empresa_id)s, %(execucao_id)s, 'objetivo_nao_classificado',"
            " %(campanha_id)s)",
            ids | {"campanha_id": campanha_id},
        )
        raise FalhaInjetada


def registrar_falha(conexao: psycopg.Connection, execucao_id: UUID) -> None:
    with conexao.transaction():
        conexao.execute(
            "UPDATE normalizado.execucao_carga"
            " SET status = 'falha', terminado_em = now(), erro = %s WHERE id = %s",
            (MENSAGEM_ERRO, execucao_id),
        )


def executar_carga_que_falha(
    conexao: psycopg.Connection, empresa_id: UUID, conta_id: UUID
) -> UUID:
    execucao_id = registrar_inicio(conexao, empresa_id)
    with pytest.raises(FalhaInjetada):
        carregar_ate_falhar(conexao, empresa_id, conta_id, execucao_id)
    return execucao_id


def ler_execucao(conexao: psycopg.Connection, execucao_id: UUID) -> tuple:
    return conexao.execute(
        "SELECT status, terminado_em IS NOT NULL, erro"
        " FROM normalizado.execucao_carga WHERE id = %s",
        (execucao_id,),
    ).fetchone()


def ler_linhas_da_carga(
    conexao: psycopg.Connection, execucao_id: UUID
) -> dict[str, int]:
    return dict(
        conexao.execute(
            "SELECT 'resposta_api', count(*) FROM bruto.resposta_api WHERE execucao_id = %(id)s"
            " UNION ALL SELECT 'conta_anuncio', count(*) FROM normalizado.conta_anuncio"
            " WHERE execucao_id = %(id)s"
            " UNION ALL SELECT 'campanha', count(*) FROM normalizado.campanha"
            " WHERE execucao_id = %(id)s"
            " UNION ALL SELECT 'aviso_execucao', count(*) FROM normalizado.aviso_execucao"
            " WHERE execucao_id = %(id)s",
            {"id": execucao_id},
        ).fetchall()
    )


def test_registro_de_inicio_persiste_apos_rollback_da_carga(
    conexao_operador: psycopg.Connection,
    conexao_etl: psycopg.Connection,
    conta: tuple[UUID, UUID],
) -> None:
    execucao_id = executar_carga_que_falha(conexao_etl, *conta)

    # Lido por outra conexão: só o que foi confirmado aparece.
    assert ler_execucao(conexao_operador, execucao_id) == ("em_andamento", False, None)
    assert ler_linhas_da_carga(conexao_operador, execucao_id) == {
        "resposta_api": 0,
        "conta_anuncio": 0,
        "campanha": 0,
        "aviso_execucao": 0,
    }


def test_falha_fica_registrada_apos_rollback_da_carga(
    conexao_operador: psycopg.Connection,
    conexao_etl: psycopg.Connection,
    conta: tuple[UUID, UUID],
) -> None:
    execucao_id = executar_carga_que_falha(conexao_etl, *conta)

    registrar_falha(conexao_etl, execucao_id)

    assert ler_execucao(conexao_operador, execucao_id) == ("falha", True, MENSAGEM_ERRO)
