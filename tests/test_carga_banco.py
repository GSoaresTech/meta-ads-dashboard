"""Prova, contra o banco local e com transações reais em paralelo, a
transação por empresa com advisory lock, o upsert das entidades e a
substituição da janela dos fatos (RF-17, RF-18, RF-19; ADR-0009 §5). Exige o
banco local de pé.
"""

import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import UUID

import psycopg
import pytest

from etl.carga import (
    Contagens,
    ErroAnuncioForaDaConta,
    ErroEntidadeDeOutraEmpresa,
    ErroLinhaForaDaJanela,
    executar_com_lock,
    substituir_metricas_diarias,
)
from tests.carga_exemplo import (
    CargaExemplo,
    carregar_exemplo,
    ler_estado,
    ler_tipos_acao,
    montar_carga,
    montar_dias,
    montar_metricas,
    trocar_dia,
)
from tests.conftest import EmpresaTeste

pytestmark = pytest.mark.integracao

# Teto de espera de cada sincronização entre threads, para que um defeito
# trave o teste por segundos, e não para sempre.
TEMPO_MAXIMO_SINCRONIA_SEGUNDOS = 10
ESPERA_CURTA_SEGUNDOS = 0.3
INTERVALO_CURTO_SEGUNDOS = 0.05
CONTAGENS_FICTICIAS: Contagens = {"tabela_ficticia": 1}
PREFIXO_ID_META_A = "99011"
PREFIXO_ID_META_A_CONTA_2 = "99012"
PREFIXO_ID_META_B = "99021"
ID_META_CONTA_2 = "990000000000031"


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


def carregar(
    conectar: Callable[[], psycopg.Connection], carga: CargaExemplo
) -> Contagens | None:
    """Uma execução da carga de exemplo, com o registro da execução que as
    linhas referenciam."""
    with conectar() as conexao:
        execucao_id = criar_execucao(conexao, carga.empresa_id)
        return executar_com_lock(
            conexao,
            carga.empresa_id,
            lambda conexao_carga: carregar_exemplo(conexao_carga, execucao_id, carga),
            espera_maxima_segundos=0,
        )


def criar_execucao(conexao: psycopg.Connection, empresa_id: UUID) -> UUID:
    with conexao.transaction():
        return conexao.execute(
            "INSERT INTO normalizado.execucao_carga (empresa_id, tipo)"
            " VALUES (%s, 'diaria') RETURNING id",
            (empresa_id,),
        ).fetchone()[0]


def montar_cargas(
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> tuple[CargaExemplo, CargaExemplo]:
    empresa_a, empresa_b = empresas
    return (
        montar_carga(empresa_a.empresa_id, empresa_a.conta_id, PREFIXO_ID_META_A),
        montar_carga(empresa_b.empresa_id, empresa_b.conta_id, PREFIXO_ID_META_B),
    )


def ler_investimentos(
    conexao: psycopg.Connection, empresa_id: UUID
) -> dict[tuple[str, date], Decimal]:
    linhas = conexao.execute(
        "SELECT a.id_meta, m.data, m.investimento"
        " FROM normalizado.metrica_diaria_anuncio m"
        " JOIN normalizado.anuncio a ON a.empresa_id = m.empresa_id AND a.id = m.anuncio_id"
        " WHERE m.empresa_id = %s",
        (empresa_id,),
    ).fetchall()
    return {(id_meta, data): investimento for id_meta, data, investimento in linhas}


def test_carga_repetida_produz_estado_identico(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    cargas = montar_cargas(empresas)
    empresa_ids = [empresa.empresa_id for empresa in empresas]
    for carga in cargas:
        carregar(conectar_etl, carga)
    primeiro = ler_estado(conexao_operador, empresa_ids)

    for carga in cargas:
        contagens = carregar(conectar_etl, carga)

    assert ler_estado(conexao_operador, empresa_ids) == primeiro
    assert primeiro["metrica_diaria_anuncio"][0] == 12
    assert primeiro["acao_diaria_anuncio"][0] == 36
    assert contagens == {
        "campanha": 1,
        "conjunto_anuncio": 1,
        "criativo": 1,
        "anuncio": 1,
        "metrica_diaria_anuncio": 6,
        "acao_diaria_anuncio": 18,
    }


def test_upsert_atualiza_a_entidade_sem_duplicar(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    carga, _ = montar_cargas(empresas)
    carregar(conectar_etl, carga)
    antes = ler_campanhas(conexao_operador, carga.empresa_id)

    carregar(conectar_etl, replace(carga, nome_campanha="Campanha Renomeada"))

    depois = ler_campanhas(conexao_operador, carga.empresa_id)
    assert [(id_, nome) for id_, nome in depois] == [
        (antes[0][0], "Campanha Renomeada")
    ]


def ler_campanhas(conexao: psycopg.Connection, empresa_id: UUID) -> list[tuple]:
    return conexao.execute(
        "SELECT id, nome FROM normalizado.campanha WHERE empresa_id = %s",
        (empresa_id,),
    ).fetchall()


def test_tipo_de_acao_que_some_na_revisao_deixa_de_existir(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    carga, _ = montar_cargas(empresas)
    carregar(conectar_etl, carga)
    revisado = carga.dias[2].data

    carregar(conectar_etl, trocar_dia(carga, 2, acoes={"link_click": (40, None)}))

    assert ler_tipos_acao(conexao_operador, carga.empresa_id, revisado) == {
        "link_click"
    }
    assert len(ler_tipos_acao(conexao_operador, carga.empresa_id, carga.inicio)) == 3


def test_substituicao_troca_so_a_janela_da_conta(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    carga_a, carga_b = montar_cargas(empresas)
    conta_2 = criar_conta(conexao_operador, carga_a.empresa_id, ID_META_CONTA_2)
    carga_a_conta_2 = replace(
        carga_a, conta_id=conta_2, prefixo_id_meta=PREFIXO_ID_META_A_CONTA_2
    )
    for carga in (carga_a, carga_a_conta_2, carga_b):
        carregar(conectar_etl, carga)
    antes_a = ler_investimentos(conexao_operador, carga_a.empresa_id)
    antes_b = ler_investimentos(conexao_operador, carga_b.empresa_id)
    # A Meta devolve só o penúltimo dia da janela: o último fica sem entrega.
    penultimo, ultimo = carga_a.dias[-2].data, carga_a.dias[-1].data
    janela = replace(
        carga_a,
        inicio=penultimo,
        fim=ultimo,
        dias=montar_dias(inicio=penultimo, quantidade=1),
    )

    carregar(conectar_etl, janela)

    anuncio = carga_a.id_meta(4)
    esperado_a = dict(antes_a)
    esperado_a[(anuncio, penultimo)] = janela.dias[0].investimento
    del esperado_a[(anuncio, ultimo)]
    assert ler_investimentos(conexao_operador, carga_a.empresa_id) == esperado_a
    assert ler_investimentos(conexao_operador, carga_b.empresa_id) == antes_b


def criar_conta(conexao: psycopg.Connection, empresa_id: UUID, id_meta: str) -> UUID:
    return conexao.execute(
        "INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)"
        " VALUES (%s, %s) RETURNING id",
        (empresa_id, id_meta),
    ).fetchone()[0]


def test_upsert_recusa_entidade_de_outra_empresa(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    carga_a, carga_b = montar_cargas(empresas)
    carregar(conectar_etl, carga_a)
    estado_a = ler_estado(conexao_operador, [carga_a.empresa_id])
    # A empresa B recebe da API os mesmos IDs da Meta da empresa A.
    invasora = replace(carga_b, prefixo_id_meta=PREFIXO_ID_META_A)

    with pytest.raises(ErroEntidadeDeOutraEmpresa):
        carregar(conectar_etl, invasora)

    assert ler_estado(conexao_operador, [carga_a.empresa_id]) == estado_a
    assert ler_estado(conexao_operador, [carga_b.empresa_id])["campanha"][0] == 0


def test_recusa_fato_fora_da_janela_sem_gravar_nada(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    carga, _ = montar_cargas(empresas)
    vazio = ler_estado(conexao_operador, [carga.empresa_id])

    with pytest.raises(ErroLinhaForaDaJanela):
        carregar(conectar_etl, replace(carga, fim=carga.dias[-2].data))

    assert ler_estado(conexao_operador, [carga.empresa_id]) == vazio


def test_substituicao_exige_transacao_aberta(
    conectar_etl: Callable[[], psycopg.Connection],
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa = empresas[0]

    with conectar_etl() as conexao, pytest.raises(RuntimeError):
        substituir_metricas_diarias(
            conexao,
            empresa.empresa_id,
            criar_execucao(conexao, empresa.empresa_id),
            empresa.conta_id,
            date(2026, 10, 1),
            date(2026, 10, 1),
            [],
            [],
        )


def test_recusa_fato_de_anuncio_de_outra_conta_sem_gravar_nada(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    carga_a, _ = montar_cargas(empresas)
    conta_2 = criar_conta(conexao_operador, carga_a.empresa_id, ID_META_CONTA_2)
    carga_a_conta_2 = replace(
        carga_a, conta_id=conta_2, prefixo_id_meta=PREFIXO_ID_META_A_CONTA_2
    )
    for carga in (carga_a, carga_a_conta_2):
        carregar(conectar_etl, carga)
    estado = ler_estado(conexao_operador, [carga_a.empresa_id])
    [(anuncio_conta_2,)] = conexao_operador.execute(
        "SELECT id FROM normalizado.anuncio WHERE id_meta = %s",
        (carga_a_conta_2.id_meta(4),),
    ).fetchall()

    def substituir_com_anuncio_da_conta_2(conexao: psycopg.Connection) -> Contagens:
        return substituir_metricas_diarias(
            conexao,
            carga_a.empresa_id,
            criar_execucao_na_transacao(conexao, carga_a.empresa_id),
            carga_a.conta_id,
            carga_a.inicio,
            carga_a.fim,
            montar_metricas(anuncio_conta_2, carga_a.dias),
            [],
        )

    with conectar_etl() as conexao, pytest.raises(ErroAnuncioForaDaConta):
        executar_com_lock(
            conexao, carga_a.empresa_id, substituir_com_anuncio_da_conta_2
        )

    assert ler_estado(conexao_operador, [carga_a.empresa_id]) == estado


def criar_execucao_na_transacao(conexao: psycopg.Connection, empresa_id: UUID) -> UUID:
    return conexao.execute(
        "INSERT INTO normalizado.execucao_carga (empresa_id, tipo)"
        " VALUES (%s, 'diaria') RETURNING id",
        (empresa_id,),
    ).fetchone()[0]
