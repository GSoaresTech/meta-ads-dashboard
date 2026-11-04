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
    RETENCAO_BRUTO_DIAS,
)
from etl.transformacao import CadastroConta

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
    """Grava o cadastro de uma conta de cima para baixo, porque cada filho
    precisa da chave interna do pai: a conta, as campanhas, os conjuntos com
    as janelas, as Páginas, os criativos e os anúncios (RF-01).

    Roda na transação da empresa. Uma entidade que já não vem da API fica
    como estava: a ETL não apaga entidades (ADR-0009 §2).
    """

    def upsert(tabela: TabelaEntidade, linhas: list[dict[str, object]]) -> dict:
        return upsert_entidades(conexao, tabela, empresa_id, execucao_id, linhas)

    atualizar_conta_anuncio(
        conexao, empresa_id, execucao_id, conta_anuncio_id, cadastro.conta
    )
    campanhas = upsert(
        TabelaEntidade.CAMPANHA,
        [
            {**linha, "conta_anuncio_id": conta_anuncio_id}
            for linha in cadastro.campanhas
        ],
    )
    conjuntos = upsert(
        TabelaEntidade.CONJUNTO_ANUNCIO,
        trocar_referencias(
            cadastro.conjuntos, {"campanha_id": ("id_meta_campanha", campanhas)}
        ),
    )
    janelas = substituir_janelas_atribuicao(
        conexao,
        empresa_id,
        execucao_id,
        list(conjuntos.values()),
        trocar_referencias(
            cadastro.janelas, {"conjunto_anuncio_id": ("id_meta_conjunto", conjuntos)}
        ),
    )
    paginas = upsert_paginas(conexao, empresa_id, execucao_id, cadastro.paginas)
    criativos = upsert(
        TabelaEntidade.CRIATIVO,
        [
            {**linha, "conta_anuncio_id": conta_anuncio_id}
            for linha in trocar_referencias(
                cadastro.criativos, {"pagina_id": ("id_meta_pagina", paginas)}
            )
        ],
    )
    anuncios = upsert(
        TabelaEntidade.ANUNCIO,
        trocar_referencias(
            cadastro.anuncios,
            {
                "conjunto_anuncio_id": ("id_meta_conjunto", conjuntos),
                "criativo_id": ("id_meta_criativo", criativos),
            },
        ),
    )
    return {
        "conta_anuncio": 1,
        "campanha": len(campanhas),
        "conjunto_anuncio": len(conjuntos),
        "janela_atribuicao_conjunto": janelas,
        "pagina": len(paginas),
        "criativo": len(criativos),
        "anuncio": len(anuncios),
    }


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
