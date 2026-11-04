"""Prova, contra o banco local, a gravação das respostas da API em bruto: como
recebidas, sem os links de paginação, só dentro da transação da carga e
desfeita com ela (RF-09, RF-18; ADR-0009 §2 e §5). Prova também a retenção
pela data de referência no fuso de cada conta (RF-21). Exige o banco local
de pé.
"""

import json
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID

import psycopg
import pytest

from etl.carga import (
    apagar_respostas_vencidas,
    executar_com_lock,
    gravar_respostas_brutas,
)
from etl.cliente_api_meta import Endpoint
from etl.configuracao import RETENCAO_BRUTO_DIAS
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
# Fusos nas duas pontas do relógio: a qualquer hora, o dia de pelo menos um
# deles difere do dia em UTC, o que prova que o limite é o do fuso da conta.
FUSO_ADIANTADO = "Pacific/Kiritimati"
FUSO_ATRASADO = "Pacific/Pago_Pago"
ID_META_SEGUNDA_CONTA = "990000000000023"
# Dias antes de hoje: o primeiro sai, os demais ficam.
DESLOCAMENTOS_RETENCAO = (RETENCAO_BRUTO_DIAS + 1, RETENCAO_BRUTO_DIAS, 0)


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


def definir_fuso(conexao: psycopg.Connection, conta_id: UUID, fuso: str) -> None:
    conexao.execute(
        "UPDATE normalizado.conta_anuncio SET fuso_horario = %s, moeda = 'BRL'"
        " WHERE id = %s",
        (fuso, conta_id),
    )


def criar_segunda_conta(conexao: psycopg.Connection, empresa_id: UUID) -> UUID:
    return conexao.execute(
        "INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)"
        " VALUES (%s, %s) RETURNING id",
        (empresa_id, ID_META_SEGUNDA_CONTA),
    ).fetchone()[0]


def ler_hoje(conexao: psycopg.Connection, fuso: str) -> date:
    return conexao.execute("SELECT (now() AT TIME ZONE %s)::date", (fuso,)).fetchone()[
        0
    ]


def inserir_resposta(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta_id: UUID,
    data_referencia: date,
) -> None:
    conexao.execute(
        "INSERT INTO bruto.resposta_api (empresa_id, execucao_id, conta_anuncio_id,"
        " endpoint, parametros, data_referencia, resposta)"
        " VALUES (%s, %s, %s, 'insights', '{}', %s, '{}')",
        (empresa_id, execucao_id, conta_id, data_referencia),
    )


def inserir_respostas_em_volta_do_limite(
    conexao: psycopg.Connection, empresa_id: UUID, conta_id: UUID, fuso: str
) -> list[date]:
    """Uma resposta antes do limite e duas dentro dele; devolve as datas que
    a retenção deve manter."""
    execucao_id = criar_execucao(conexao, empresa_id)
    hoje = ler_hoje(conexao, fuso)
    datas = [hoje - timedelta(days=dias) for dias in DESLOCAMENTOS_RETENCAO]
    for data_referencia in datas:
        inserir_resposta(conexao, empresa_id, execucao_id, conta_id, data_referencia)
    return datas[1:]


def ler_datas_por_conta(
    conexao: psycopg.Connection, empresa_id: UUID
) -> dict[UUID, list[date]]:
    datas: dict[UUID, list[date]] = {}
    for conta_id, data_referencia in conexao.execute(
        "SELECT conta_anuncio_id, data_referencia FROM bruto.resposta_api"
        " WHERE empresa_id = %s ORDER BY data_referencia",
        (empresa_id,),
    ).fetchall():
        datas.setdefault(conta_id, []).append(data_referencia)
    return datas


def reter(
    conectar_etl: Callable[[], psycopg.Connection], empresa_id: UUID
) -> int | None:
    with conectar_etl() as conexao:
        return executar_com_lock(
            conexao,
            empresa_id,
            lambda conexao_carga: apagar_respostas_vencidas(conexao_carga, empresa_id),
        )


def test_retencao_apaga_antes_do_limite_no_fuso_de_cada_conta(
    empresas: tuple[EmpresaTeste, EmpresaTeste],
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
) -> None:
    empresa = empresas[0]
    segunda_conta = criar_segunda_conta(conexao_operador, empresa.empresa_id)
    esperadas = {}
    for conta_id, fuso in (
        (empresa.conta_id, FUSO_ADIANTADO),
        (segunda_conta, FUSO_ATRASADO),
    ):
        definir_fuso(conexao_operador, conta_id, fuso)
        esperadas[conta_id] = inserir_respostas_em_volta_do_limite(
            conexao_operador, empresa.empresa_id, conta_id, fuso
        )

    apagadas = reter(conectar_etl, empresa.empresa_id)

    assert apagadas == 2
    assert ler_datas_por_conta(conexao_operador, empresa.empresa_id) == esperadas


def test_retencao_de_conta_sem_fuso_usa_o_dia_em_utc(
    empresas: tuple[EmpresaTeste, EmpresaTeste],
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
) -> None:
    empresa = empresas[0]
    esperadas = inserir_respostas_em_volta_do_limite(
        conexao_operador, empresa.empresa_id, empresa.conta_id, "UTC"
    )

    apagadas = reter(conectar_etl, empresa.empresa_id)

    assert apagadas == 1
    assert ler_datas_por_conta(conexao_operador, empresa.empresa_id) == {
        empresa.conta_id: esperadas
    }


def test_retencao_nao_apaga_respostas_de_outra_empresa(
    empresas: tuple[EmpresaTeste, EmpresaTeste],
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
) -> None:
    empresa, outra = empresas
    inserir_respostas_em_volta_do_limite(
        conexao_operador, outra.empresa_id, outra.conta_id, "UTC"
    )
    antes = ler_datas_por_conta(conexao_operador, outra.empresa_id)

    apagadas = reter(conectar_etl, empresa.empresa_id)

    assert apagadas == 0
    assert ler_datas_por_conta(conexao_operador, outra.empresa_id) == antes


def test_retencao_exige_transacao_aberta(
    empresas: tuple[EmpresaTeste, EmpresaTeste],
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
) -> None:
    empresa = empresas[0]
    inserir_respostas_em_volta_do_limite(
        conexao_operador, empresa.empresa_id, empresa.conta_id, "UTC"
    )
    antes = ler_datas_por_conta(conexao_operador, empresa.empresa_id)

    with conectar_etl() as conexao, pytest.raises(RuntimeError, match="fora da"):
        apagar_respostas_vencidas(conexao, empresa.empresa_id)

    assert ler_datas_por_conta(conexao_operador, empresa.empresa_id) == antes
