"""Fixtures dos testes de integração da carga: o banco local e duas empresas
fictícias, cada uma com uma conta de anúncio. Só os testes com o marcador
integracao as usam, e eles exigem o banco local de pé.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from uuid import UUID

import psycopg
import pytest

from etl.carga import conectar_banco

# O padrão público do Supabase local, exibido por `supabase status`. Fica
# fixo, e não vem do ambiente, para que o teste nunca rode contra produção.
URL_BANCO_LOCAL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"

EMPRESAS_FICTICIAS = (
    ("Empresa Exemplo Carga A", "990000000000021"),
    ("Empresa Exemplo Carga B", "990000000000022"),
)

# As FKs são NO ACTION (ADR-0009 §1): a limpeza apaga de baixo para cima.
LIMPEZA_EMPRESA = (
    "DELETE FROM normalizado.alcance_periodo WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.acao_quebra_diaria_campanha WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.quebra_diaria_campanha WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.sobrescrita_resultado_campanha WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.acao_diaria_anuncio WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.metrica_diaria_anuncio WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.anuncio WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.criativo WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.pagina WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.janela_atribuicao_conjunto WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.conjunto_anuncio WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.aviso_execucao WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.campanha WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.contagem_linhas_execucao WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.fatia_historica WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM bruto.resposta_api WHERE empresa_id = %(empresa_id)s",
    "UPDATE normalizado.conta_anuncio SET execucao_id = NULL WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.execucao_carga WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.conta_anuncio WHERE empresa_id = %(empresa_id)s",
    "DELETE FROM normalizado.empresa WHERE id = %(empresa_id)s",
)


@dataclass(frozen=True)
class EmpresaTeste:
    empresa_id: UUID
    conta_id: UUID
    # Distingue os IDs da Meta inventados de cada empresa.
    indice: int


@pytest.fixture
def conexao_operador() -> Iterator[psycopg.Connection]:
    with psycopg.connect(URL_BANCO_LOCAL, autocommit=True) as conexao:
        yield conexao


@pytest.fixture
def conectar_etl() -> Callable[[], psycopg.Connection]:
    """Abre conexões com os privilégios da ETL, como a carga faz em produção."""

    def conectar() -> psycopg.Connection:
        conexao = conectar_banco(URL_BANCO_LOCAL)
        conexao.execute("SET ROLE etl_carga")
        return conexao

    return conectar


@pytest.fixture
def empresas(
    conexao_operador: psycopg.Connection,
) -> Iterator[tuple[EmpresaTeste, EmpresaTeste]]:
    """Duas empresas fictícias com uma conta cada, apagadas no fim."""
    # Uma execução interrompida sem teardown deixaria as empresas, e o id_meta
    # repetido da conta faria todo teste seguinte falhar.
    apagar_empresas_ficticias(conexao_operador)
    criadas = tuple(
        criar_empresa(conexao_operador, nome, id_meta_conta, indice)
        for indice, (nome, id_meta_conta) in enumerate(EMPRESAS_FICTICIAS, start=1)
    )
    try:
        yield criadas
    finally:
        apagar_empresas_ficticias(conexao_operador)


def criar_empresa(
    conexao: psycopg.Connection, nome: str, id_meta_conta: str, indice: int
) -> EmpresaTeste:
    with conexao.transaction():
        empresa_id = conexao.execute(
            "INSERT INTO normalizado.empresa (nome) VALUES (%s) RETURNING id", (nome,)
        ).fetchone()[0]
        conta_id = conexao.execute(
            "INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)"
            " VALUES (%s, %s) RETURNING id",
            (empresa_id, id_meta_conta),
        ).fetchone()[0]
    return EmpresaTeste(empresa_id, conta_id, indice)


def apagar_empresas_ficticias(conexao: psycopg.Connection) -> None:
    nomes = [nome for nome, _ in EMPRESAS_FICTICIAS]
    linhas = conexao.execute(
        "SELECT id FROM normalizado.empresa WHERE nome = ANY(%s)", (nomes,)
    ).fetchall()
    for (empresa_id,) in linhas:
        with conexao.transaction():
            for comando in LIMPEZA_EMPRESA:
                conexao.execute(comando, {"empresa_id": empresa_id})
