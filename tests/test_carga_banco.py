"""Prova, contra o banco local e com transações reais em paralelo, a
transação por empresa com advisory lock (RF-18, RF-19; ADR-0009 §5). Exige o
banco local de pé.
"""

import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import UUID

import psycopg
import pytest

from etl.carga import Contagens, executar_com_lock
from tests.conftest import EmpresaTeste

pytestmark = pytest.mark.integracao

# Teto de espera de cada sincronização entre threads, para que um defeito
# trave o teste por segundos, e não para sempre.
TEMPO_MAXIMO_SINCRONIA_SEGUNDOS = 10
ESPERA_CURTA_SEGUNDOS = 0.3
INTERVALO_CURTO_SEGUNDOS = 0.05
CONTAGENS_FICTICIAS: Contagens = {"tabela_ficticia": 1}


class FalhaInjetada(Exception):
    """Falha no meio da carga."""


class CargaRetida:
    """Uma carga que fica dentro da transação, com o lock da empresa, até ser
    liberada."""

    def __init__(self) -> None:
        self.dentro = threading.Event()
        self.liberar = threading.Event()

    def carregar(self, conexao: psycopg.Connection) -> Contagens:
        self.dentro.set()
        if not self.liberar.wait(TEMPO_MAXIMO_SINCRONIA_SEGUNDOS):
            raise TimeoutError("a carga retida não foi liberada")
        return CONTAGENS_FICTICIAS


@contextmanager
def reter_lock(
    conectar: Callable[[], psycopg.Connection], empresa_id: UUID
) -> Iterator[CargaRetida]:
    """Roda numa thread uma carga que segura o lock da empresa enquanto o
    bloco executa."""
    retida = CargaRetida()

    def executar() -> Contagens | None:
        with conectar() as conexao:
            return executar_com_lock(conexao, empresa_id, retida.carregar)

    with ThreadPoolExecutor(max_workers=1) as executor:
        futuro = executor.submit(executar)
        try:
            assert retida.dentro.wait(TEMPO_MAXIMO_SINCRONIA_SEGUNDOS)
            yield retida
        finally:
            retida.liberar.set()
        assert futuro.result(TEMPO_MAXIMO_SINCRONIA_SEGUNDOS) == CONTAGENS_FICTICIAS


def carregar_vazio(conexao: psycopg.Connection) -> Contagens:
    return CONTAGENS_FICTICIAS


def nao_carregar(conexao: psycopg.Connection) -> Contagens:
    raise AssertionError("a carga não podia rodar sem o lock")


def test_segunda_carga_da_mesma_empresa_desiste_apos_a_espera(
    conectar_etl: Callable[[], psycopg.Connection],
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa = empresas[0]

    with reter_lock(conectar_etl, empresa.empresa_id), conectar_etl() as conexao:
        inicio = time.monotonic()
        resultado = executar_com_lock(
            conexao,
            empresa.empresa_id,
            nao_carregar,
            espera_maxima_segundos=ESPERA_CURTA_SEGUNDOS,
            intervalo_segundos=INTERVALO_CURTO_SEGUNDOS,
        )
        esperado = time.monotonic() - inicio

    assert resultado is None
    assert esperado >= ESPERA_CURTA_SEGUNDOS


def test_segunda_carga_obtem_o_lock_quando_a_primeira_termina(
    conectar_etl: Callable[[], psycopg.Connection],
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa = empresas[0]
    tentou_sem_lock = threading.Event()
    primeira_terminou = threading.Event()

    def dormir(segundos: float) -> None:
        tentou_sem_lock.set()
        time.sleep(segundos)

    def carregar_depois_da_primeira(conexao: psycopg.Connection) -> Contagens:
        assert primeira_terminou.is_set()
        return CONTAGENS_FICTICIAS

    def executar_segunda() -> Contagens | None:
        with conectar_etl() as conexao:
            return executar_com_lock(
                conexao,
                empresa.empresa_id,
                carregar_depois_da_primeira,
                espera_maxima_segundos=TEMPO_MAXIMO_SINCRONIA_SEGUNDOS,
                intervalo_segundos=INTERVALO_CURTO_SEGUNDOS,
                dormir=dormir,
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        with reter_lock(conectar_etl, empresa.empresa_id):
            segunda = executor.submit(executar_segunda)
            assert tentou_sem_lock.wait(TEMPO_MAXIMO_SINCRONIA_SEGUNDOS)
            primeira_terminou.set()
        resultado = segunda.result(TEMPO_MAXIMO_SINCRONIA_SEGUNDOS)

    assert resultado == CONTAGENS_FICTICIAS


def test_cargas_de_empresas_diferentes_nao_se_bloqueiam(
    conectar_etl: Callable[[], psycopg.Connection],
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa_a, empresa_b = empresas

    with reter_lock(conectar_etl, empresa_a.empresa_id), conectar_etl() as conexao:
        resultado = executar_com_lock(
            conexao, empresa_b.empresa_id, carregar_vazio, espera_maxima_segundos=0
        )

    assert resultado == CONTAGENS_FICTICIAS


def test_falha_na_carga_desfaz_a_transacao_e_libera_o_lock(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa = empresas[0]

    def carregar_ate_falhar(conexao: psycopg.Connection) -> Contagens:
        conexao.execute(
            "INSERT INTO normalizado.execucao_carga (empresa_id, tipo)"
            " VALUES (%s, 'diaria')",
            (empresa.empresa_id,),
        )
        raise FalhaInjetada

    with conectar_etl() as conexao:
        with pytest.raises(FalhaInjetada):
            executar_com_lock(conexao, empresa.empresa_id, carregar_ate_falhar)
        # Na mesma sessão: um lock de sessão continuaria preso a ela.
        assert listar_advisory_locks(conexao) == []

    with conectar_etl() as conexao:
        resultado = executar_com_lock(
            conexao, empresa.empresa_id, carregar_vazio, espera_maxima_segundos=0
        )

    assert resultado == CONTAGENS_FICTICIAS
    assert contar_execucoes(conexao_operador, empresa.empresa_id) == 0


def listar_advisory_locks(conexao: psycopg.Connection) -> list[tuple]:
    return conexao.execute(
        "SELECT objid FROM pg_locks"
        " WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
    ).fetchall()


def contar_execucoes(conexao: psycopg.Connection, empresa_id: UUID) -> int:
    return conexao.execute(
        "SELECT count(*) FROM normalizado.execucao_carga WHERE empresa_id = %s",
        (empresa_id,),
    ).fetchone()[0]
