"""Carga de bruto e de normalizado: a transação por empresa ou por fatia, com o
lock que põe em série as execuções da mesma empresa, a gravação das respostas
da API como recebidas, o upsert das entidades pela chave natural e a
substituição da janela dos fatos (CLAUDE.md §6; ADR-0009 §5).

A conexão é direta, por psycopg, e em autocommit: cada bloco transaction() é
uma transação real, com BEGIN e COMMIT, e não um savepoint dentro de uma
transação implícita que o psycopg abriria sozinho.
"""

import time
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from enum import StrEnum
from typing import Final
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from etl.cliente_api_meta import Endpoint
from etl.configuracao import (
    ESPERA_MAXIMA_LOCK_SEGUNDOS,
    INTERVALO_TENTATIVA_LOCK_SEGUNDOS,
)

# Linhas gravadas por tabela, para o registro de fim (RF-20).
type Contagens = dict[str, int]
# Uma linha já transformada, com os nomes das colunas de normalizado.
type Linha = Mapping[str, object]

BYTES_CHAVE_LOCK: Final = 8

# Os links de paginação repetem a URL da consulta, com o ID da conta, e
# trariam o access_token se ele fosse na URL; os cursores bastam para
# auditar a sequência das páginas (ADR-0009 §2).
LINKS_PAGINACAO: Final = ("next", "previous")
INSERIR_RESPOSTA_BRUTA: Final = """
INSERT INTO bruto.resposta_api
  (empresa_id, execucao_id, conta_anuncio_id, endpoint, parametros,
   data_referencia, resposta)
VALUES (%(empresa_id)s, %(execucao_id)s, %(conta_anuncio_id)s, %(endpoint)s,
        %(parametros)s, %(data_referencia)s, %(resposta)s)
"""

# Gravadas pela própria carga, e não pela transformação.
COLUNAS_CONTROLE: Final = ("empresa_id", "execucao_id")
COLUNAS_METRICA_DIARIA: Final = (
    "anuncio_id",
    "data",
    "investimento",
    "impressoes",
    "alcance",
)
COLUNAS_ACAO_DIARIA: Final = ("anuncio_id", "data", "tipo_acao", "quantidade", "valor")

# Os fatos não guardam a conta: o DELETE chega a ela pelo anúncio, pelo
# conjunto e pela campanha, e as ações saem junto pelo ON DELETE CASCADE. Uma
# ação que sumiu na revisão da Meta some também do banco (RF-17).
APAGAR_METRICAS_DIARIAS: Final = """
DELETE FROM normalizado.metrica_diaria_anuncio AS metrica
USING normalizado.anuncio AS anuncio,
      normalizado.conjunto_anuncio AS conjunto,
      normalizado.campanha AS campanha
WHERE metrica.empresa_id = %(empresa_id)s
  AND metrica.data BETWEEN %(inicio)s AND %(fim)s
  AND anuncio.empresa_id = metrica.empresa_id
  AND anuncio.id = metrica.anuncio_id
  AND conjunto.empresa_id = anuncio.empresa_id
  AND conjunto.id = anuncio.conjunto_anuncio_id
  AND campanha.empresa_id = conjunto.empresa_id
  AND campanha.id = conjunto.campanha_id
  AND campanha.conta_anuncio_id = %(conta_anuncio_id)s
"""

# Os anúncios do lote que não são da conta pelo mesmo caminho do DELETE.
CONTAR_ANUNCIOS_FORA_DA_CONTA: Final = """
SELECT count(*)
FROM unnest(%(anuncios)s::uuid[]) AS lote (anuncio_id)
WHERE NOT EXISTS (
  SELECT
  FROM normalizado.anuncio AS anuncio
  JOIN normalizado.conjunto_anuncio AS conjunto
    ON conjunto.empresa_id = anuncio.empresa_id
   AND conjunto.id = anuncio.conjunto_anuncio_id
  JOIN normalizado.campanha AS campanha
    ON campanha.empresa_id = conjunto.empresa_id
   AND campanha.id = conjunto.campanha_id
  WHERE anuncio.empresa_id = %(empresa_id)s
    AND anuncio.id = lote.anuncio_id
    AND campanha.conta_anuncio_id = %(conta_anuncio_id)s
)
"""


class TabelaEntidade(StrEnum):
    """As entidades com id_meta único no banco inteiro. A página é única só
    dentro da empresa, e as janelas de atribuição são substituídas."""

    CAMPANHA = "campanha"
    CONJUNTO_ANUNCIO = "conjunto_anuncio"
    CRIATIVO = "criativo"
    ANUNCIO = "anuncio"


class ErroEntidadeDeOutraEmpresa(Exception):
    """Um id_meta da carga já pertence a outra empresa. A carga falha em vez
    de mover a entidade de dono em silêncio (ADR-0009 §5)."""


class ErroLinhaForaDaJanela(ValueError):
    """Um fato com data fora da janela substituída não seria apagado pela
    próxima substituição da mesma janela."""


class ErroAnuncioForaDaConta(ValueError):
    """Um fato de anúncio de outra conta não seria apagado pela próxima
    substituição da conta substituída."""


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


def gravar_respostas_brutas(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta_anuncio_id: UUID,
    endpoint: Endpoint,
    parametros: Mapping[str, str],
    data_referencia: date,
    paginas: Sequence[Mapping[str, object]],
) -> int:
    """Grava cada página de uma consulta como a Meta a devolveu, sem os
    links de paginação, e devolve as linhas gravadas (RF-09).

    Roda na transação da empresa, antes da transformação: uma falha em
    qualquer passo seguinte desfaz também o bruto (RF-18). data_referencia é
    a última data coberta pela consulta de insights ou, nas de cadastro, a
    data da extração no fuso da conta, que a retenção usa (RF-21).
    """
    exigir_transacao(conexao)
    comum = {
        "empresa_id": empresa_id,
        "execucao_id": execucao_id,
        "conta_anuncio_id": conta_anuncio_id,
        # O valor de OBJETO é a aresta vazia, que o CHECK de endpoint recusa.
        "endpoint": endpoint.name.lower(),
        "parametros": Jsonb(dict(parametros)),
        "data_referencia": data_referencia,
    }
    with conexao.cursor() as cursor:
        cursor.executemany(
            INSERIR_RESPOSTA_BRUTA,
            [
                {**comum, "resposta": Jsonb(retirar_links_paginacao(pagina))}
                for pagina in paginas
            ],
        )
    return len(paginas)


def contar_respostas_brutas(
    conexao: psycopg.Connection, empresa_id: UUID, execucao_id: UUID
) -> int:
    """As respostas que a execução gravou em bruto, inclusive as ainda não
    confirmadas da transação aberta."""
    return conexao.execute(
        "SELECT count(*) FROM bruto.resposta_api"
        " WHERE empresa_id = %s AND execucao_id = %s",
        (empresa_id, execucao_id),
    ).fetchone()[0]


def retirar_links_paginacao(pagina: Mapping[str, object]) -> dict[str, object]:
    """Uma cópia da página sem paging.next e paging.previous; o resto fica
    como recebido."""
    copia = dict(pagina)
    paginacao = copia.get("paging")
    if isinstance(paginacao, dict):
        copia["paging"] = {
            chave: valor
            for chave, valor in paginacao.items()
            if chave not in LINKS_PAGINACAO
        }
    return copia


def upsert_entidades(
    conexao: psycopg.Connection,
    tabela: TabelaEntidade,
    empresa_id: UUID,
    execucao_id: UUID,
    linhas: Sequence[Linha],
) -> dict[str, UUID]:
    """Inclui ou atualiza as entidades pelo id_meta e devolve o id interno de
    cada uma, pelo id_meta, para as FKs dos filhos.

    O UPDATE só vale para a linha da mesma empresa. Se algum id_meta já é de
    outra empresa, a linha não volta no RETURNING, e a carga falha. A
    mensagem não cita o ID, que pode chegar aos logs públicos (RNF-17).
    """
    exigir_transacao(conexao)
    if not linhas:
        return {}
    colunas = ler_colunas(linhas)
    validar_linhas_entidade(colunas, linhas)
    parametros = [
        {**linha, "empresa_id": empresa_id, "execucao_id": execucao_id}
        for linha in linhas
    ]
    with conexao.cursor() as cursor:
        cursor.executemany(
            montar_upsert_entidade(tabela, colunas), parametros, returning=True
        )
        ids = ler_ids_devolvidos(cursor)
    if len(ids) != len(linhas):
        raise ErroEntidadeDeOutraEmpresa(
            f"{tabela}: {len(linhas) - len(ids)} entidade(s) de outra empresa"
        )
    return ids


def validar_linhas_entidade(colunas: Sequence[str], linhas: Sequence[Linha]) -> None:
    if "id_meta" not in colunas:
        raise ValueError("entidade sem id_meta")
    if set(colunas) & set(COLUNAS_CONTROLE):
        raise ValueError("empresa_id e execucao_id são gravados pela carga")
    # Um id_meta repetido seria atualizado duas vezes no mesmo lote, e a
    # contagem do RETURNING o confundiria com uma entidade de outra empresa.
    if len({linha["id_meta"] for linha in linhas}) != len(linhas):
        raise ValueError("id_meta repetido no lote")


def montar_upsert_entidade(
    tabela: TabelaEntidade, colunas: Sequence[str]
) -> sql.Composed:
    inseridas = (*colunas, *COLUNAS_CONTROLE)
    atualizadas = [c for c in inseridas if c not in ("id_meta", "empresa_id")]
    return sql.SQL(
        "INSERT INTO {tabela} AS destino ({colunas}) VALUES ({valores})"
        " ON CONFLICT (id_meta) DO UPDATE SET {atribuicoes}, atualizado_em = now()"
        " WHERE destino.empresa_id = EXCLUDED.empresa_id"
        " RETURNING id_meta, id"
    ).format(
        tabela=sql.Identifier("normalizado", tabela),
        colunas=sql.SQL(", ").join(map(sql.Identifier, inseridas)),
        valores=sql.SQL(", ").join(map(sql.Placeholder, inseridas)),
        atribuicoes=sql.SQL(", ").join(
            sql.SQL("{coluna} = EXCLUDED.{coluna}").format(coluna=sql.Identifier(c))
            for c in atualizadas
        ),
    )


def ler_ids_devolvidos(cursor: psycopg.Cursor) -> dict[str, UUID]:
    """Junta o RETURNING de cada comando do executemany."""
    ids: dict[str, UUID] = {}
    while True:
        ids.update(cursor.fetchall())
        if not cursor.nextset():
            return ids


def substituir_metricas_diarias(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta_anuncio_id: UUID,
    inicio: date,
    fim: date,
    metricas: Sequence[Linha],
    acoes: Sequence[Linha],
) -> Contagens:
    """Troca as métricas e ações diárias da conta de inicio a fim, inclusive,
    pelo conjunto completo devolvido pela API (RF-17).

    Roda dentro da transação da empresa: o leitor vê o conjunto anterior ou
    o novo, nunca o intervalo vazio entre o DELETE e o INSERT (RNF-09). Um
    dia sem linha na resposta fica sem linha no banco.
    """
    exigir_transacao(conexao)
    validar_colunas_fato(metricas, COLUNAS_METRICA_DIARIA)
    validar_colunas_fato(acoes, COLUNAS_ACAO_DIARIA)
    validar_janela(inicio, fim, [*metricas, *acoes])
    escopo = {
        "empresa_id": empresa_id,
        "inicio": inicio,
        "fim": fim,
        "conta_anuncio_id": conta_anuncio_id,
    }
    validar_anuncios_da_conta(conexao, escopo, [*metricas, *acoes])
    conexao.execute(APAGAR_METRICAS_DIARIAS, escopo)
    controle = {"empresa_id": empresa_id, "execucao_id": execucao_id}
    for tabela, colunas, linhas in (
        ("metrica_diaria_anuncio", COLUNAS_METRICA_DIARIA, metricas),
        ("acao_diaria_anuncio", COLUNAS_ACAO_DIARIA, acoes),
    ):
        with conexao.cursor() as cursor:
            cursor.executemany(
                montar_insercao_fato(tabela, colunas),
                [{**linha, **controle} for linha in linhas],
            )
    return {"metrica_diaria_anuncio": len(metricas), "acao_diaria_anuncio": len(acoes)}


def validar_colunas_fato(linhas: Sequence[Linha], esperadas: Sequence[str]) -> None:
    # Uma coluna a mais seria descartada em silêncio pelo INSERT.
    if linhas and set(ler_colunas(linhas)) != set(esperadas):
        raise ValueError("colunas do fato diferentes das da tabela")


def validar_janela(inicio: date, fim: date, linhas: Sequence[Linha]) -> None:
    if inicio > fim:
        raise ValueError("janela com início depois do fim")
    if any(not inicio <= linha["data"] <= fim for linha in linhas):
        raise ErroLinhaForaDaJanela("fato com data fora da janela substituída")


def validar_anuncios_da_conta(
    conexao: psycopg.Connection, escopo: Mapping[str, object], linhas: Sequence[Linha]
) -> None:
    anuncios = list({linha["anuncio_id"] for linha in linhas})
    fora = conexao.execute(
        CONTAR_ANUNCIOS_FORA_DA_CONTA, {**escopo, "anuncios": anuncios}
    ).fetchone()[0]
    if fora:
        raise ErroAnuncioForaDaConta("fato de anúncio fora da conta substituída")


def montar_insercao_fato(tabela: str, colunas: Sequence[str]) -> sql.Composed:
    inseridas = (*colunas, *COLUNAS_CONTROLE)
    return sql.SQL("INSERT INTO {tabela} ({colunas}) VALUES ({valores})").format(
        tabela=sql.Identifier("normalizado", tabela),
        colunas=sql.SQL(", ").join(map(sql.Identifier, inseridas)),
        valores=sql.SQL(", ").join(map(sql.Placeholder, inseridas)),
    )


def ler_colunas(linhas: Sequence[Linha]) -> tuple[str, ...]:
    """As colunas do lote, que precisam ser as mesmas em toda linha."""
    colunas = tuple(linhas[0])
    if any(set(linha) != set(colunas) for linha in linhas):
        raise ValueError("linhas do lote com colunas diferentes")
    return colunas


def exigir_transacao(conexao: psycopg.Connection) -> None:
    """A carga só escreve dentro da transação da empresa (RF-18): em
    autocommit, cada comando seria confirmado sozinho."""
    if conexao.info.transaction_status != TransactionStatus.INTRANS:
        raise RuntimeError("carga fora da transação da empresa")
