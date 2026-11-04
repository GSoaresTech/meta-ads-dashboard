"""Insights diários por anúncio de cada conta ativa da empresa, com as ações,
como tarefa da execução por empresa (RF-02, RF-12; etl.execucao.TarefaCarga).

A extração lê as contas ativas no banco e, fora de transação, os insights de
cada uma no intervalo e, pelo ID, os anúncios deles que ainda não estão no
banco, com o conjunto e a campanha. A carga, já na transação da empresa,
grava as respostas em bruto, transforma, carrega essas entidades e substitui
as métricas e as ações da conta no intervalo, nessa ordem (RF-09, RF-17;
ADR-0009 §5).
"""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import psycopg

from etl.cadastro import listar_contas_ativas
from etl.carga import (
    Contagens,
    carregar_entidades,
    carregar_insights_diarios,
    gravar_respostas_brutas,
    ler_ids_anuncios,
)
from etl.cliente_api_meta import ClienteApiMeta
from etl.extracao import (
    Consulta,
    EntidadesExtraidas,
    extrair_entidades_por_id,
    extrair_insights_diarios,
    listar_anuncios_insights,
)
from etl.transformacao import transformar_entidades, transformar_insights_diarios


@dataclass(frozen=True)
class InsightsContaExtraidos:
    conta_anuncio_id: UUID
    insights: Consulta
    entidades: EntidadesExtraidas


@dataclass(frozen=True)
class TarefaInsightsDiarios:
    """Os insights de inicio a fim, inclusive, nas datas do fuso de cada
    conta, como a API as entrega (R-17)."""

    conectar: Callable[[], psycopg.Connection]
    cliente: ClienteApiMeta
    inicio: date
    fim: date

    def extrair(self, empresa_id: UUID) -> list[InsightsContaExtraidos]:
        # Conexões só para as leituras: a extração pode levar muito tempo, e
        # a conexão parada poderia ser derrubada pelo pooler.
        with self.conectar() as conexao:
            contas = listar_contas_ativas(conexao, empresa_id)
        return [
            self.extrair_conta(empresa_id, conta_anuncio_id, id_meta)
            for conta_anuncio_id, id_meta in contas
        ]

    def extrair_conta(
        self, empresa_id: UUID, conta_anuncio_id: UUID, id_meta_conta: str
    ) -> InsightsContaExtraidos:
        """Os insights da conta e, pelo ID, os anúncios deles que o banco
        ainda não tem."""
        insights = extrair_insights_diarios(
            self.cliente, id_meta_conta, self.inicio, self.fim
        )
        return InsightsContaExtraidos(
            conta_anuncio_id,
            insights,
            extrair_anuncios_ausentes(
                self.conectar,
                self.cliente,
                empresa_id,
                listar_anuncios_insights(insights.paginas),
            ),
        )

    def carregar(
        self,
        conexao: psycopg.Connection,
        empresa_id: UUID,
        execucao_id: UUID,
        dados: Sequence[InsightsContaExtraidos],
    ) -> Contagens:
        contagens: Counter[str] = Counter()
        for conta in dados:
            contagens.update(
                carregar_insights_conta(
                    conexao, empresa_id, execucao_id, self.inicio, self.fim, conta
                )
            )
        return dict(contagens)


def extrair_anuncios_ausentes(
    conectar: Callable[[], psycopg.Connection],
    cliente: ClienteApiMeta,
    empresa_id: UUID,
    ids_meta: Sequence[str],
) -> EntidadesExtraidas:
    """Lê pelo ID os anúncios dados que o banco ainda não tem, com o conjunto
    e a campanha de cada um. Um anúncio carregado entre esta leitura e a
    carga é só atualizado pelo upsert."""
    with conectar() as conexao:
        existentes = ler_ids_anuncios(conexao, empresa_id, ids_meta)
    ausentes = [id_meta for id_meta in ids_meta if id_meta not in existentes]
    return extrair_entidades_por_id(cliente, ausentes)


def carregar_insights_conta(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    inicio: date,
    fim: date,
    conta: InsightsContaExtraidos,
) -> Contagens:
    contagens = carregar_bruto_e_entidades(
        conexao,
        empresa_id,
        execucao_id,
        conta.conta_anuncio_id,
        fim,
        [conta.insights],
        conta.entidades,
    )
    insights = transformar_insights_diarios(conta.insights.paginas)
    return contagens | carregar_insights_diarios(
        conexao,
        empresa_id,
        execucao_id,
        conta.conta_anuncio_id,
        inicio,
        fim,
        insights,
    )


def carregar_bruto_e_entidades(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta_anuncio_id: UUID,
    data_referencia: date,
    consultas: Sequence[Consulta],
    entidades: EntidadesExtraidas,
) -> Contagens:
    """Grava em bruto as consultas de insights e as das entidades lidas pelo
    ID, com o fim do intervalo como data de referência, que a retenção usa
    (RF-21), e carrega essas entidades, das quais os fatos dependem pela FK
    (ADR-0009 §5)."""
    for consulta in (*consultas, *entidades.listar_consultas()):
        gravar_respostas_brutas(
            conexao,
            empresa_id,
            execucao_id,
            conta_anuncio_id,
            consulta.endpoint,
            consulta.parametros,
            data_referencia,
            consulta.paginas,
        )
    linhas = transformar_entidades(
        entidades.campanhas.paginas,
        entidades.conjuntos.paginas,
        entidades.anuncios.paginas,
    )
    return carregar_entidades(
        conexao, empresa_id, execucao_id, conta_anuncio_id, linhas
    )
