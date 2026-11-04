"""Uma carga de exemplo, no formato que as rotinas da E4 vão produzir: a
resposta bruta dos insights, a hierarquia de uma conta (campanha, conjunto,
criativo e anúncio) e as métricas e ações diárias do anúncio, com nomes
fictícios e IDs da Meta inventados. Também lê o estado das tabelas, para
comparar cargas (RF-17).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import psycopg

from etl.carga import (
    Contagens,
    TabelaEntidade,
    gravar_respostas_brutas,
    substituir_metricas_diarias,
    upsert_entidades,
)
from etl.cliente_api_meta import Endpoint

INICIO_PADRAO = date(2026, 10, 1)
DIAS_PADRAO = 6
# (quantidade, valor) por tipo de ação, como actions e action_values.
ACOES_PADRAO: Mapping[str, tuple[int | None, Decimal | None]] = {
    "link_click": (40, None),
    "omni_purchase": (3, Decimal("297.30")),
    "onsite_conversion.messaging_conversation_started_7d": (5, None),
}

# Só as colunas de negócio: o ADR-0009 §5 deixa de fora da comparação o
# execucao_id e as colunas *_em, que mudam a cada execução por definição.
COLUNAS_NEGOCIO: Mapping[str, str] = {
    "campanha": "id, conta_anuncio_id, id_meta, nome, objetivo, status",
    "conjunto_anuncio": "id, campanha_id, id_meta, nome, meta_otimizacao, status",
    "criativo": "id, conta_anuncio_id, id_meta, titulo, texto",
    "anuncio": "id, conjunto_anuncio_id, criativo_id, id_meta, nome, status",
    "metrica_diaria_anuncio": "anuncio_id, data, investimento, impressoes, alcance",
    "acao_diaria_anuncio": "anuncio_id, data, tipo_acao, quantidade, valor",
}


@dataclass(frozen=True)
class DiaExemplo:
    data: date
    investimento: Decimal | None
    impressoes: int | None
    alcance: int | None
    acoes: Mapping[str, tuple[int | None, Decimal | None]]


@dataclass(frozen=True)
class CargaExemplo:
    empresa_id: UUID
    conta_id: UUID
    # Prefixo dos IDs da Meta inventados, único por empresa e conta.
    prefixo_id_meta: str
    inicio: date
    fim: date
    dias: tuple[DiaExemplo, ...]
    nome_campanha: str = "Campanha Exemplo"

    def id_meta(self, nivel: int) -> str:
        return f"{self.prefixo_id_meta}{nivel:02d}0000000"


def montar_dias(
    inicio: date = INICIO_PADRAO,
    quantidade: int = DIAS_PADRAO,
    acoes: Mapping[str, tuple[int | None, Decimal | None]] = ACOES_PADRAO,
) -> tuple[DiaExemplo, ...]:
    return tuple(
        DiaExemplo(
            data=inicio + timedelta(days=deslocamento),
            investimento=Decimal("12.34") + deslocamento,
            impressoes=1000 + deslocamento,
            alcance=800 + deslocamento,
            acoes=acoes,
        )
        for deslocamento in range(quantidade)
    )


def montar_carga(
    empresa_id: UUID,
    conta_id: UUID,
    prefixo_id_meta: str,
    dias: tuple[DiaExemplo, ...] | None = None,
) -> CargaExemplo:
    dias = montar_dias() if dias is None else dias
    return CargaExemplo(
        empresa_id=empresa_id,
        conta_id=conta_id,
        prefixo_id_meta=prefixo_id_meta,
        inicio=dias[0].data,
        fim=dias[-1].data,
        dias=dias,
    )


def trocar_dia(carga: CargaExemplo, indice: int, **campos: object) -> CargaExemplo:
    dias = list(carga.dias)
    dias[indice] = replace(dias[indice], **campos)
    return replace(carga, dias=tuple(dias))


def carregar_exemplo(
    conexao: psycopg.Connection, execucao_id: UUID, carga: CargaExemplo
) -> Contagens:
    """Grava a resposta bruta e carrega a hierarquia e os fatos, na transação
    aberta pelo chamador. A contagem do bruto fica com a execução, que a lê
    do banco."""
    gravar_respostas_brutas(
        conexao,
        carga.empresa_id,
        execucao_id,
        carga.conta_id,
        Endpoint.INSIGHTS,
        {"level": "ad", "time_increment": "1"},
        carga.fim,
        [montar_pagina_insights(carga)],
    )
    contagens: Contagens = {}
    anuncio_id = carregar_hierarquia(conexao, execucao_id, carga, contagens)
    contagens |= substituir_metricas_diarias(
        conexao,
        carga.empresa_id,
        execucao_id,
        carga.conta_id,
        carga.inicio,
        carga.fim,
        montar_metricas(anuncio_id, carga.dias),
        montar_acoes(anuncio_id, carga.dias),
    )
    return contagens


def montar_pagina_insights(carga: CargaExemplo) -> dict[str, object]:
    """A página de insights que a carga transformaria, com os nomes da Meta."""
    return {
        "data": [
            {
                "ad_id": carga.id_meta(4),
                "spend": str(dia.investimento),
                "date_start": dia.data.isoformat(),
                "date_stop": dia.data.isoformat(),
            }
            for dia in carga.dias
        ]
    }


def carregar_hierarquia(
    conexao: psycopg.Connection,
    execucao_id: UUID,
    carga: CargaExemplo,
    contagens: Contagens,
) -> UUID:
    def upsert(tabela: TabelaEntidade, linha: dict[str, object]) -> UUID:
        ids = upsert_entidades(conexao, tabela, carga.empresa_id, execucao_id, [linha])
        contagens[tabela] = len(ids)
        return ids[linha["id_meta"]]

    campanha_id = upsert(
        TabelaEntidade.CAMPANHA,
        {
            "id_meta": carga.id_meta(1),
            "conta_anuncio_id": carga.conta_id,
            "nome": carga.nome_campanha,
            "objetivo": "OUTCOME_SALES",
            "status": "ACTIVE",
        },
    )
    conjunto_id = upsert(
        TabelaEntidade.CONJUNTO_ANUNCIO,
        {
            "id_meta": carga.id_meta(2),
            "campanha_id": campanha_id,
            "nome": "Conjunto Exemplo",
            "meta_otimizacao": "OFFSITE_CONVERSIONS",
            "status": "ACTIVE",
        },
    )
    criativo_id = upsert(
        TabelaEntidade.CRIATIVO,
        {
            "id_meta": carga.id_meta(3),
            "conta_anuncio_id": carga.conta_id,
            "titulo": "Título Exemplo",
            "texto": "Texto Exemplo",
        },
    )
    return upsert(
        TabelaEntidade.ANUNCIO,
        {
            "id_meta": carga.id_meta(4),
            "conjunto_anuncio_id": conjunto_id,
            "criativo_id": criativo_id,
            "nome": "Anúncio Exemplo",
            "status": "ACTIVE",
        },
    )


def montar_metricas(
    anuncio_id: UUID, dias: Sequence[DiaExemplo]
) -> list[dict[str, object]]:
    return [
        {
            "anuncio_id": anuncio_id,
            "data": dia.data,
            "investimento": dia.investimento,
            "impressoes": dia.impressoes,
            "alcance": dia.alcance,
        }
        for dia in dias
    ]


def montar_acoes(
    anuncio_id: UUID, dias: Sequence[DiaExemplo]
) -> list[dict[str, object]]:
    return [
        {
            "anuncio_id": anuncio_id,
            "data": dia.data,
            "tipo_acao": tipo_acao,
            "quantidade": quantidade,
            "valor": valor,
        }
        for dia in dias
        for tipo_acao, (quantidade, valor) in dia.acoes.items()
    ]


def ler_estado(
    conexao: psycopg.Connection, empresa_ids: Sequence[UUID]
) -> dict[str, tuple[int, str]]:
    """Contagem e soma de verificação das colunas de negócio de cada tabela
    da carga, só das empresas dadas (RF-17)."""
    estado = {}
    for tabela, colunas in COLUNAS_NEGOCIO.items():
        estado[tabela] = conexao.execute(
            f"SELECT count(*), md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), ''))"
            f" FROM (SELECT {colunas} FROM normalizado.{tabela}"
            "  WHERE empresa_id = ANY(%s)) AS t",
            (list(empresa_ids),),
        ).fetchone()
    return estado


def ler_tipos_acao(
    conexao: psycopg.Connection, empresa_id: UUID, data: date
) -> set[str]:
    linhas = conexao.execute(
        "SELECT tipo_acao FROM normalizado.acao_diaria_anuncio"
        " WHERE empresa_id = %s AND data = %s",
        (empresa_id, data),
    ).fetchall()
    return {tipo for (tipo,) in linhas}
