"""Carga de bruto e de normalizado: a transação por empresa ou por fatia, com o
lock que põe em série as execuções da mesma empresa, a gravação das respostas
da API como recebidas, o upsert das entidades pela chave natural e a
substituição da janela dos fatos e dos períodos do alcance (CLAUDE.md §6;
ADR-0009 §5).

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
    RETENCAO_BRUTO_DIAS,
)
from etl.transformacao import CadastroConta, EntidadesConta, InsightsDiarios

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
COLUNAS_ALCANCE_PERIODO: Final = (
    "conta_anuncio_id",
    "campanha_id",
    "anuncio_id",
    "tipo_periodo",
    "inicio_periodo",
    "fim_periodo",
    "alcance",
    "impressoes",
)

# A data de referência está no fuso da conta (ADR-0009 §2), e o hoje também.
# A conta sem fuso, que ainda não teve a primeira extração, usa o dia em UTC:
# sem o coalesce, a comparação com nulo nunca apagaria as respostas dela.
APAGAR_RESPOSTAS_VENCIDAS: Final = """
DELETE FROM bruto.resposta_api AS resposta
USING normalizado.conta_anuncio AS conta
WHERE resposta.empresa_id = %(empresa_id)s
  AND conta.empresa_id = resposta.empresa_id
  AND conta.id = resposta.conta_anuncio_id
  AND resposta.data_referencia
      < (now() AT TIME ZONE coalesce(conta.fuso_horario, 'UTC'))::date
        - %(retencao_dias)s::integer
"""

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

# O escopo de uma consulta de alcance: os períodos do tipo que começam de
# inicio a fim, na conta e nas campanhas e anúncios dela, pelo mesmo caminho
# do DELETE das métricas diárias (ADR-0009 §5).
APAGAR_ALCANCE_PERIODO: Final = """
DELETE FROM normalizado.alcance_periodo AS alcance
WHERE alcance.empresa_id = %(empresa_id)s
  AND alcance.tipo_periodo = %(tipo_periodo)s
  AND alcance.inicio_periodo BETWEEN %(inicio)s AND %(fim)s
  AND (
    alcance.conta_anuncio_id = %(conta_anuncio_id)s
    OR alcance.campanha_id IN (
      SELECT campanha.id FROM normalizado.campanha AS campanha
      WHERE campanha.empresa_id = %(empresa_id)s
        AND campanha.conta_anuncio_id = %(conta_anuncio_id)s
    )
    OR alcance.anuncio_id IN (
      SELECT anuncio.id
      FROM normalizado.anuncio AS anuncio
      JOIN normalizado.conjunto_anuncio AS conjunto
        ON conjunto.empresa_id = anuncio.empresa_id
       AND conjunto.id = anuncio.conjunto_anuncio_id
      JOIN normalizado.campanha AS campanha
        ON campanha.empresa_id = conjunto.empresa_id
       AND campanha.id = conjunto.campanha_id
      WHERE anuncio.empresa_id = %(empresa_id)s
        AND campanha.conta_anuncio_id = %(conta_anuncio_id)s
    )
  )
"""

# As campanhas e os anúncios da conta entre os IDs da Meta dados.
LER_IDS_CAMPANHAS_DA_CONTA: Final = """
SELECT id_meta, id FROM normalizado.campanha
WHERE empresa_id = %(empresa_id)s AND conta_anuncio_id = %(conta_anuncio_id)s
  AND id_meta = ANY(%(ids_meta)s)
"""
LER_IDS_ANUNCIOS_DA_CONTA: Final = """
SELECT anuncio.id_meta, anuncio.id
FROM normalizado.anuncio AS anuncio
JOIN normalizado.conjunto_anuncio AS conjunto
  ON conjunto.empresa_id = anuncio.empresa_id
 AND conjunto.id = anuncio.conjunto_anuncio_id
JOIN normalizado.campanha AS campanha
  ON campanha.empresa_id = conjunto.empresa_id
 AND campanha.id = conjunto.campanha_id
WHERE anuncio.empresa_id = %(empresa_id)s
  AND campanha.conta_anuncio_id = %(conta_anuncio_id)s
  AND anuncio.id_meta = ANY(%(ids_meta)s)
"""

LER_IDS_ANUNCIOS: Final = """
SELECT id_meta, id FROM normalizado.anuncio
WHERE empresa_id = %(empresa_id)s AND id_meta = ANY(%(ids_meta)s)
"""

ATUALIZAR_CONTA: Final = """
UPDATE normalizado.conta_anuncio
SET nome = %(nome)s, fuso_horario = %(fuso_horario)s, moeda = %(moeda)s,
    execucao_id = %(execucao_id)s, atualizado_em = now()
WHERE empresa_id = %(empresa_id)s AND id = %(conta_anuncio_id)s
"""

# A Página é única só dentro da empresa (ADR-0009 §1), então o conflito é por
# (empresa_id, id_meta), e nunca move a Página de dono. O nome não é tocado:
# a ETL ainda não o lê (R-27).
UPSERT_PAGINA: Final = """
INSERT INTO normalizado.pagina (empresa_id, id_meta, execucao_id)
VALUES (%(empresa_id)s, %(id_meta)s, %(execucao_id)s)
ON CONFLICT (empresa_id, id_meta) DO UPDATE
SET execucao_id = EXCLUDED.execucao_id, atualizado_em = now()
RETURNING id_meta, id
"""

APAGAR_JANELAS: Final = """
DELETE FROM normalizado.janela_atribuicao_conjunto
WHERE empresa_id = %(empresa_id)s AND conjunto_anuncio_id = ANY(%(conjuntos)s)
"""
COLUNAS_JANELA: Final = ("conjunto_anuncio_id", "tipo_evento", "janela_dias")

# As campanhas dadas cujo objetivo cai em "Não classificado", a regra sem
# objetivo do catálogo, pela mesma resolução que o painel usa (RF-15;
# ADR-0009 §4).
REGISTRAR_AVISOS_NAO_CLASSIFICADO: Final = """
INSERT INTO normalizado.aviso_execucao (empresa_id, execucao_id, tipo, campanha_id)
SELECT %(empresa_id)s, %(execucao_id)s, 'objetivo_nao_classificado', resolvido.campanha_id
FROM normalizado.resolver_resultado_campanha(%(empresa_id)s) AS resolvido
JOIN normalizado.resultado_objetivo AS regra ON regra.id = resolvido.resultado_objetivo_id
WHERE regra.objetivo IS NULL
  AND resolvido.campanha_id = ANY(%(campanhas)s)
"""


class ErroContaAusente(Exception):
    """A conta do cadastro não existe na empresa."""


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


class ErroAnuncioAusente(Exception):
    """Um anúncio dos insights não existe na empresa: a FK recusaria o fato,
    e a carga falha antes, sem citar o ID (RNF-17)."""


class ErroAnuncioForaDaConta(ValueError):
    """Um fato de anúncio de outra conta não seria apagado pela próxima
    substituição da conta substituída."""


class ErroEntidadeForaDaConta(Exception):
    """Uma campanha ou um anúncio de um fato não existe na conta: a FK
    recusaria a entidade ausente, e a linha de outra conta não seria apagada
    pela próxima substituição desta. A carga falha antes, sem citar o ID
    (RNF-17)."""


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


def apagar_respostas_vencidas(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    *,
    retencao_dias: int = RETENCAO_BRUTO_DIAS,
) -> int:
    """Apaga as respostas brutas da empresa com data de referência anterior a
    hoje menos a retenção, no fuso de cada conta, e devolve quantas apagou
    (RF-21).

    A data de gravação não conta: a resposta da carga histórica, gravada
    hoje com a data de um mês antigo, sai na execução diária seguinte. Roda
    na transação da carga diária da empresa, e uma falha desfaz também a
    carga.
    """
    exigir_transacao(conexao)
    return conexao.execute(
        APAGAR_RESPOSTAS_VENCIDAS,
        {"empresa_id": empresa_id, "retencao_dias": retencao_dias},
    ).rowcount


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


def atualizar_conta_anuncio(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta_anuncio_id: UUID,
    conta: Linha,
) -> int:
    """Grava o nome, o fuso e a moeda lidos da API na conta cadastrada só
    pelo ID (RF-43)."""
    exigir_transacao(conexao)
    linhas = conexao.execute(
        ATUALIZAR_CONTA,
        {
            "nome": conta["nome"],
            "fuso_horario": conta["fuso_horario"],
            "moeda": conta["moeda"],
            "execucao_id": execucao_id,
            "empresa_id": empresa_id,
            "conta_anuncio_id": conta_anuncio_id,
        },
    ).rowcount
    if linhas != 1:
        raise ErroContaAusente("conta do cadastro fora da empresa")
    return linhas


def upsert_paginas(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    ids_meta: Sequence[str],
) -> dict[str, UUID]:
    """Inclui as Páginas que faltam e devolve o id interno de cada uma, pelo
    id_meta, para a FK do criativo."""
    exigir_transacao(conexao)
    if not ids_meta:
        return {}
    if len(set(ids_meta)) != len(ids_meta):
        raise ValueError("id_meta repetido no lote")
    with conexao.cursor() as cursor:
        cursor.executemany(
            UPSERT_PAGINA,
            [
                {
                    "empresa_id": empresa_id,
                    "id_meta": id_meta,
                    "execucao_id": execucao_id,
                }
                for id_meta in ids_meta
            ],
            returning=True,
        )
        return ler_ids_devolvidos(cursor)


def substituir_janelas_atribuicao(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conjuntos: Sequence[UUID],
    janelas: Sequence[Linha],
) -> int:
    """Troca as janelas de atribuição dos conjuntos dados pelas lidas agora,
    para que uma janela retirada do conjunto saia também do banco
    (ADR-0009 §2)."""
    exigir_transacao(conexao)
    validar_colunas_fato(janelas, COLUNAS_JANELA)
    substituidos = set(conjuntos)
    if any(janela["conjunto_anuncio_id"] not in substituidos for janela in janelas):
        raise ValueError("janela de conjunto fora do lote substituído")
    conexao.execute(
        APAGAR_JANELAS, {"empresa_id": empresa_id, "conjuntos": list(conjuntos)}
    )
    controle = {"empresa_id": empresa_id, "execucao_id": execucao_id}
    with conexao.cursor() as cursor:
        cursor.executemany(
            montar_insercao_fato("janela_atribuicao_conjunto", COLUNAS_JANELA),
            [{**janela, **controle} for janela in janelas],
        )
    return len(janelas)


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


def ler_ids_anuncios(
    conexao: psycopg.Connection, empresa_id: UUID, ids_meta: Sequence[str]
) -> dict[str, UUID]:
    """O id interno de cada anúncio da empresa entre os IDs da Meta dados,
    pelo id_meta. O que não existe na empresa fica de fora."""
    return dict(
        conexao.execute(
            LER_IDS_ANUNCIOS, {"empresa_id": empresa_id, "ids_meta": list(ids_meta)}
        ).fetchall()
    )


def carregar_insights_diarios(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta_anuncio_id: UUID,
    inicio: date,
    fim: date,
    insights: InsightsDiarios,
) -> Contagens:
    """Troca as métricas e as ações da conta de inicio a fim pelas dos
    insights, com o anúncio pela chave interna (RF-02, RF-12, RF-17).

    Roda na transação da empresa, depois das entidades: todo anúncio dos
    insights já existe no banco, lido pelo cadastro ou pelo ID (ADR-0009
    §5).
    """
    exigir_transacao(conexao)
    ids_meta = list(dict.fromkeys(m["id_meta_anuncio"] for m in insights.metricas))
    ids = ler_ids_anuncios(conexao, empresa_id, ids_meta)
    if len(ids) != len(ids_meta):
        raise ErroAnuncioAusente(
            f"{len(ids_meta) - len(ids)} anúncio(s) dos insights fora da empresa"
        )
    referencia = {"anuncio_id": ("id_meta_anuncio", ids)}
    return substituir_metricas_diarias(
        conexao,
        empresa_id,
        execucao_id,
        conta_anuncio_id,
        inicio,
        fim,
        trocar_referencias(insights.metricas, referencia),
        trocar_referencias(insights.acoes, referencia),
    )


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


def carregar_cadastro(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta_anuncio_id: UUID,
    cadastro: CadastroConta,
) -> Contagens:
    """Grava o cadastro de uma conta: o nome, o fuso e a moeda da conta e,
    depois, as entidades dela (RF-01, RF-43)."""
    atualizar_conta_anuncio(
        conexao, empresa_id, execucao_id, conta_anuncio_id, cadastro.conta
    )
    return {
        "conta_anuncio": 1,
        **carregar_entidades(
            conexao, empresa_id, execucao_id, conta_anuncio_id, cadastro
        ),
    }


def carregar_entidades(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta_anuncio_id: UUID,
    entidades: EntidadesConta,
) -> Contagens:
    """Grava as entidades de uma conta de cima para baixo, porque cada filho
    precisa da chave interna do pai: as campanhas, os conjuntos com as
    janelas, as Páginas, os criativos e os anúncios (RF-01). Por fim,
    registra o aviso das campanhas gravadas com objetivo fora do catálogo
    (RF-15).

    Roda na transação da empresa. Uma entidade que já não vem da API fica
    como estava: a ETL não apaga entidades (ADR-0009 §2).
    """

    def upsert(tabela: TabelaEntidade, linhas: list[dict[str, object]]) -> dict:
        return upsert_entidades(conexao, tabela, empresa_id, execucao_id, linhas)

    campanhas = upsert(
        TabelaEntidade.CAMPANHA,
        [
            {**linha, "conta_anuncio_id": conta_anuncio_id}
            for linha in entidades.campanhas
        ],
    )
    conjuntos = upsert(
        TabelaEntidade.CONJUNTO_ANUNCIO,
        trocar_referencias(
            entidades.conjuntos, {"campanha_id": ("id_meta_campanha", campanhas)}
        ),
    )
    janelas = substituir_janelas_atribuicao(
        conexao,
        empresa_id,
        execucao_id,
        list(conjuntos.values()),
        trocar_referencias(
            entidades.janelas, {"conjunto_anuncio_id": ("id_meta_conjunto", conjuntos)}
        ),
    )
    paginas = upsert_paginas(conexao, empresa_id, execucao_id, entidades.paginas)
    criativos = upsert(
        TabelaEntidade.CRIATIVO,
        [
            {**linha, "conta_anuncio_id": conta_anuncio_id}
            for linha in trocar_referencias(
                entidades.criativos, {"pagina_id": ("id_meta_pagina", paginas)}
            )
        ],
    )
    anuncios = upsert(
        TabelaEntidade.ANUNCIO,
        trocar_referencias(
            entidades.anuncios,
            {
                "conjunto_anuncio_id": ("id_meta_conjunto", conjuntos),
                "criativo_id": ("id_meta_criativo", criativos),
            },
        ),
    )
    return {
        "campanha": len(campanhas),
        "conjunto_anuncio": len(conjuntos),
        "janela_atribuicao_conjunto": janelas,
        "pagina": len(paginas),
        "criativo": len(criativos),
        "anuncio": len(anuncios),
        "aviso_execucao": registrar_avisos_nao_classificado(
            conexao, empresa_id, execucao_id, list(campanhas.values())
        ),
    }


def registrar_avisos_nao_classificado(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    campanhas: Sequence[UUID],
) -> int:
    """Grava um aviso por campanha dada que fica "Não classificado", e
    devolve quantos gravou. O objetivo desconhecido não falha a carga: a
    campanha entra, e o aviso aponta para ela pelo id interno (RF-15).

    Só as campanhas desta carga, e não todas as da empresa, para que cada
    conta da execução avise apenas das próprias. O aviso entra na transação
    da carga, porque o de uma carga desfeita não vale (ADR-0009 §5)."""
    exigir_transacao(conexao)
    return conexao.execute(
        REGISTRAR_AVISOS_NAO_CLASSIFICADO,
        {"empresa_id": empresa_id, "execucao_id": execucao_id, "campanhas": campanhas},
    ).rowcount


def trocar_referencias(
    linhas: Sequence[Mapping[str, object]],
    referencias: Mapping[str, tuple[str, Mapping[str, UUID]]],
) -> list[dict[str, object]]:
    """Troca, em cada linha, o ID da Meta do pai pela chave interna dele:
    referencias leva a coluna de destino ao campo de origem e aos ids
    devolvidos pelo upsert do pai. Um pai nulo continua nulo, como a Página
    opcional do criativo."""
    trocadas = []
    for linha in linhas:
        trocada = dict(linha)
        for coluna, (origem, ids) in referencias.items():
            id_meta = trocada.pop(origem)
            trocada[coluna] = None if id_meta is None else ids[id_meta]
        trocadas.append(trocada)
    return trocadas


def carregar_alcance_periodo(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta_anuncio_id: UUID,
    tipo_periodo: str,
    inicio: date,
    fim: date,
    linhas: Sequence[Linha],
) -> Contagens:
    """Troca o alcance da conta nos períodos do tipo que começam de inicio a
    fim pelo das linhas, com a campanha e o anúncio pela chave interna
    (RF-04, RF-17; ADR-0006).

    Roda na transação da empresa, depois das entidades lidas pelo ID: toda
    campanha e todo anúncio das linhas já existem na conta (ADR-0009 §5). A
    linha sem campanha nem anúncio é da própria conta.
    """
    exigir_transacao(conexao)
    escopo = {"empresa_id": empresa_id, "conta_anuncio_id": conta_anuncio_id}
    referencias = {
        coluna: (origem, ler_ids_da_conta(conexao, consulta, escopo, linhas, origem))
        for coluna, origem, consulta in (
            ("campanha_id", "id_meta_campanha", LER_IDS_CAMPANHAS_DA_CONTA),
            ("anuncio_id", "id_meta_anuncio", LER_IDS_ANUNCIOS_DA_CONTA),
        )
    }
    trocadas = trocar_referencias(linhas, referencias)
    for linha in trocadas:
        sem_entidade = linha["campanha_id"] is None and linha["anuncio_id"] is None
        linha["conta_anuncio_id"] = conta_anuncio_id if sem_entidade else None
    return substituir_alcance_periodo(
        conexao,
        empresa_id,
        execucao_id,
        conta_anuncio_id,
        tipo_periodo,
        inicio,
        fim,
        trocadas,
    )


def ler_ids_da_conta(
    conexao: psycopg.Connection,
    consulta: str,
    escopo: Mapping[str, object],
    linhas: Sequence[Linha],
    origem: str,
) -> dict[str, UUID]:
    """O id interno de cada entidade das linhas pelo ID da Meta em origem,
    que precisa existir na conta do escopo."""
    ids_meta = list({linha[origem] for linha in linhas} - {None})
    ids = dict(conexao.execute(consulta, {**escopo, "ids_meta": ids_meta}).fetchall())
    if len(ids) != len(ids_meta):
        raise ErroEntidadeForaDaConta(
            f"{len(ids_meta) - len(ids)} entidade(s) fora da conta"
        )
    return ids


def substituir_alcance_periodo(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta_anuncio_id: UUID,
    tipo_periodo: str,
    inicio: date,
    fim: date,
    linhas: Sequence[Linha],
) -> Contagens:
    """Apaga o alcance da conta nos períodos do tipo que começam de inicio a
    fim e inclui o conjunto completo devolvido pela API. O período sem linha
    na resposta, sem entrega, fica sem linha no banco (R-20).

    O leitor vê o conjunto anterior ou o novo, nunca o vazio entre o DELETE
    e o INSERT (RNF-09).
    """
    exigir_transacao(conexao)
    validar_colunas_fato(linhas, COLUNAS_ALCANCE_PERIODO)
    if inicio > fim:
        raise ValueError("janela com início depois do fim")
    if any(
        linha["tipo_periodo"] != tipo_periodo
        or not inicio <= linha["inicio_periodo"] <= fim
        or linha["fim_periodo"] > fim
        for linha in linhas
    ):
        raise ErroLinhaForaDaJanela("alcance fora dos períodos substituídos")
    conexao.execute(
        APAGAR_ALCANCE_PERIODO,
        {
            "empresa_id": empresa_id,
            "conta_anuncio_id": conta_anuncio_id,
            "tipo_periodo": tipo_periodo,
            "inicio": inicio,
            "fim": fim,
        },
    )
    controle = {"empresa_id": empresa_id, "execucao_id": execucao_id}
    with conexao.cursor() as cursor:
        cursor.executemany(
            montar_insercao_fato("alcance_periodo", COLUNAS_ALCANCE_PERIODO),
            [{**linha, **controle} for linha in linhas],
        )
    return {"alcance_periodo": len(linhas)}
