"""Carga de normalizado: a transação por empresa ou por fatia, com o lock que
põe em série as execuções da mesma empresa (CLAUDE.md §6; ADR-0009 §5).

A conexão é direta, por psycopg, e em autocommit: cada bloco transaction() é
uma transação real, com BEGIN e COMMIT, e não um savepoint dentro de uma
transação implícita que o psycopg abriria sozinho.
"""

import time
from collections.abc import Callable
from typing import Final
from uuid import UUID

import psycopg

from etl.configuracao import (
    ESPERA_MAXIMA_LOCK_SEGUNDOS,
    INTERVALO_TENTATIVA_LOCK_SEGUNDOS,
)

# Linhas gravadas por tabela, para o registro de fim (RF-20).
type Contagens = dict[str, int]

BYTES_CHAVE_LOCK: Final = 8


def conectar_banco(url_banco: str) -> psycopg.Connection:
    """Conecta pelo pooler de sessão do Supabase, que mantém a sessão do
    cliente numa só conexão do Postgres enquanto ela durar."""
    return psycopg.connect(url_banco, autocommit=True)


def calcular_chave_lock(empresa_id: UUID) -> int:
    """Os primeiros 64 bits do UUID, como o bigint com sinal que o
    pg_try_advisory_xact_lock recebe. Duas empresas com a mesma chave só
    seriam postas em série, sem perder dado."""
    return int.from_bytes(
        empresa_id.bytes[:BYTES_CHAVE_LOCK], byteorder="big", signed=True
    )


def tentar_lock_empresa(conexao: psycopg.Connection, empresa_id: UUID) -> bool:
    """Tenta o lock sem esperar. É de transação, e não de sessão: sai sozinho
    no COMMIT ou no ROLLBACK, inclusive pelo pooler, e nunca fica preso a uma
    conexão reaproveitada."""
    return conexao.execute(
        "SELECT pg_try_advisory_xact_lock(%s)", (calcular_chave_lock(empresa_id),)
    ).fetchone()[0]


def executar_com_lock(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    carregar: Callable[[psycopg.Connection], Contagens],
    *,
    espera_maxima_segundos: float = ESPERA_MAXIMA_LOCK_SEGUNDOS,
    intervalo_segundos: float = INTERVALO_TENTATIVA_LOCK_SEGUNDOS,
    dormir: Callable[[float], None] = time.sleep,
    relogio: Callable[[], float] = time.monotonic,
) -> Contagens | None:
    """Roda carregar numa única transação que detém o lock da empresa
    (RF-18, RF-19).

    Sem o lock, tenta de novo a cada intervalo, numa transação nova, até a
    espera máxima, e devolve None sem ter chamado carregar. Uma exceção de
    carregar desfaz a transação inteira e é propagada.
    """
    prazo = relogio() + espera_maxima_segundos
    while True:
        with conexao.transaction():
            if tentar_lock_empresa(conexao, empresa_id):
                return carregar(conexao)
        restante = prazo - relogio()
        if restante <= 0:
            return None
        dormir(min(intervalo_segundos, restante))
