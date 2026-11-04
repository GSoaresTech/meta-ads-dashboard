"""Prova, contra o banco local, a gravação das respostas da API em bruto: como
recebidas, sem os links de paginação, só dentro da transação da carga e
desfeita com ela (RF-09, RF-18; ADR-0009 §2 e §5). Exige o banco local de
pé.
"""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from uuid import UUID

import psycopg
import pytest

from etl.carga import executar_com_lock, gravar_respostas_brutas
from etl.cliente_api_meta import Endpoint
from tests.conftest import EmpresaTeste

pytestmark = pytest.mark.integracao

PASTA_FIXTURES = Path(__file__).parent / "fixtures"
PARAMETROS_INSIGHTS = {
    "level": "ad",
    "time_increment": "1",
    "time_range": '{"since":"2026-10-01","until":"2026-10-01"}',
    "limit": "2",
}
DATA_REFERENCIA = date(2026, 10, 1)
# Um token fictício nos links, como a Meta os devolve quando o token vai na
# URL: nenhum deles pode chegar ao banco.
TOKEN_FICTICIO = "access_token=EAAFicticio0000"


class FalhaInjetada(Exception):
    """Falha depois da gravação do bruto, ainda na transação da carga."""


def ler_paginas_com_token() -> list[dict[str, object]]:
    paginas = []
    for nome in ("insights_anuncio_dia_pagina_1", "insights_anuncio_dia_pagina_2"):
        fixture = json.loads((PASTA_FIXTURES / f"{nome}.json").read_text("utf-8"))
        pagina = fixture["corpo"]
        for link in ("next", "previous"):
            if link in pagina["paging"]:
                pagina["paging"][link] += f"&{TOKEN_FICTICIO}"
        paginas.append(pagina)
    return paginas


def criar_execucao(conexao: psycopg.Connection, empresa_id: UUID) -> UUID:
    with conexao.transaction():
        return conexao.execute(
            "INSERT INTO normalizado.execucao_carga (empresa_id, tipo)"
            " VALUES (%s, 'diaria') RETURNING id",
            (empresa_id,),
        ).fetchone()[0]


def gravar(
    conexao: psycopg.Connection,
    empresa: EmpresaTeste,
    execucao_id: UUID,
    paginas: list[dict[str, object]],
    conta_anuncio_id: UUID | None = None,
) -> int:
    return gravar_respostas_brutas(
        conexao,
        empresa.empresa_id,
        execucao_id,
        conta_anuncio_id or empresa.conta_id,
        Endpoint.INSIGHTS,
        PARAMETROS_INSIGHTS,
        DATA_REFERENCIA,
        paginas,
    )


def ler_respostas(conexao: psycopg.Connection, empresa_id: UUID) -> list[tuple]:
    return conexao.execute(
        "SELECT execucao_id, conta_anuncio_id, endpoint, parametros,"
        " data_referencia, resposta"
        " FROM bruto.resposta_api WHERE empresa_id = %s ORDER BY id",
        (empresa_id,),
    ).fetchall()


def test_respostas_sao_gravadas_como_recebidas_sem_links_de_paginacao(
    empresas: tuple[EmpresaTeste, EmpresaTeste],
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
) -> None:
    empresa = empresas[0]
    paginas = ler_paginas_com_token()
    with conectar_etl() as conexao:
        execucao_id = criar_execucao(conexao, empresa.empresa_id)
        gravadas = executar_com_lock(
            conexao,
            empresa.empresa_id,
            lambda conexao_carga: {
                "resposta_api": gravar(conexao_carga, empresa, execucao_id, paginas)
            },
        )

    assert gravadas == {"resposta_api": 2}
    respostas = ler_respostas(conexao_operador, empresa.empresa_id)
    assert [resposta for *_, resposta in respostas] == [
        {"data": pagina["data"], "paging": {"cursors": pagina["paging"]["cursors"]}}
        for pagina in paginas
    ]
    assert [tuple(linha[:5]) for linha in respostas] == [
        (
            execucao_id,
            empresa.conta_id,
            "insights",
            PARAMETROS_INSIGHTS,
            DATA_REFERENCIA,
        )
    ] * len(paginas)


def test_nenhuma_resposta_gravada_contem_access_token(
    empresas: tuple[EmpresaTeste, EmpresaTeste],
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
) -> None:
    empresa = empresas[0]
    with conectar_etl() as conexao:
        execucao_id = criar_execucao(conexao, empresa.empresa_id)
        executar_com_lock(
            conexao,
            empresa.empresa_id,
            lambda conexao_carga: {
                "resposta_api": gravar(
                    conexao_carga, empresa, execucao_id, ler_paginas_com_token()
                )
            },
        )

    com_token = conexao_operador.execute(
        "SELECT count(*) FROM bruto.resposta_api"
        " WHERE empresa_id = %s"
        " AND (resposta::text LIKE '%%access_token%%'"
        "  OR parametros::text LIKE '%%access_token%%')",
        (empresa.empresa_id,),
    ).fetchone()[0]
    assert com_token == 0
    assert len(ler_respostas(conexao_operador, empresa.empresa_id)) == 2


def test_falha_depois_da_gravacao_desfaz_o_bruto(
    empresas: tuple[EmpresaTeste, EmpresaTeste],
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
) -> None:
    empresa = empresas[0]

    def gravar_e_falhar(conexao_carga: psycopg.Connection) -> dict[str, int]:
        gravar(conexao_carga, empresa, execucao_id, ler_paginas_com_token())
        raise FalhaInjetada

    with conectar_etl() as conexao, pytest.raises(FalhaInjetada):
        execucao_id = criar_execucao(conexao, empresa.empresa_id)
        executar_com_lock(conexao, empresa.empresa_id, gravar_e_falhar)

    assert ler_respostas(conexao_operador, empresa.empresa_id) == []


def test_gravacao_exige_transacao_aberta(
    empresas: tuple[EmpresaTeste, EmpresaTeste],
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
) -> None:
    empresa = empresas[0]
    with conectar_etl() as conexao:
        execucao_id = criar_execucao(conexao, empresa.empresa_id)
        with pytest.raises(RuntimeError, match="fora da transação"):
            gravar(conexao, empresa, execucao_id, ler_paginas_com_token())

    assert ler_respostas(conexao_operador, empresa.empresa_id) == []


def test_gravacao_recusa_conta_de_outra_empresa(
    empresas: tuple[EmpresaTeste, EmpresaTeste],
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
) -> None:
    empresa, outra = empresas
    with conectar_etl() as conexao, pytest.raises(psycopg.errors.ForeignKeyViolation):
        execucao_id = criar_execucao(conexao, empresa.empresa_id)
        executar_com_lock(
            conexao,
            empresa.empresa_id,
            lambda conexao_carga: {
                "resposta_api": gravar(
                    conexao_carga,
                    empresa,
                    execucao_id,
                    ler_paginas_com_token(),
                    conta_anuncio_id=outra.conta_id,
                )
            },
        )

    assert ler_respostas(conexao_operador, empresa.empresa_id) == []
