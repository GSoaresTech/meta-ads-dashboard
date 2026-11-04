"""Prova, contra o banco local, que nenhuma coluna de `normalizado` tem nome
de campo da API (RF-11), comparando as colunas do catálogo do Postgres com os
campos do mapa. Exige o banco local de pé, com as migrations aplicadas.
"""

from collections.abc import Iterator

import psycopg
import pytest

from etl.mapa_campos import MAPA_CAMPOS

pytestmark = pytest.mark.integracao

# O padrão público do Supabase local, exibido por `supabase status`. Fica
# fixo, e não vem do ambiente, para que o teste nunca rode contra produção.
URL_BANCO_LOCAL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"

# Os únicos nomes que a Meta e `normalizado` têm em comum, e por quê:
# - `id`: a chave interna, pela convenção de nomes (CLAUDE.md §10). O ID da
#   Meta vai para `id_meta`;
# - `status`: o termo também é usado em português, e a coluna guarda o
#   domínio fechado da Meta (ADR-0009 §1).
COLUNAS_COM_NOME_DE_CAMPO_DA_API = frozenset({"id", "status"})


@pytest.fixture
def conexao() -> Iterator[psycopg.Connection]:
    with psycopg.connect(URL_BANCO_LOCAL, autocommit=True) as conexao:
        yield conexao


def listar_colunas_normalizado(conexao: psycopg.Connection) -> set[str]:
    linhas = conexao.execute(
        "SELECT DISTINCT column_name FROM information_schema.columns"
        " WHERE table_schema = 'normalizado'"
    ).fetchall()
    return {nome for (nome,) in linhas}


def test_nenhuma_coluna_de_normalizado_tem_nome_de_campo_da_api(
    conexao: psycopg.Connection,
) -> None:
    campos_api = {nome for campos in MAPA_CAMPOS.values() for nome in campos}
    colunas = listar_colunas_normalizado(conexao)

    # Igualdade, e não subconjunto: uma exceção que deixa de existir sai da
    # lista, em vez de liberar o nome para sempre.
    assert colunas & campos_api == COLUNAS_COM_NOME_DE_CAMPO_DA_API
