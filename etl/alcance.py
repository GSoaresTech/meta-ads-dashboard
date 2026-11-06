"""Alcance e impressões por semana ISO, mês e ano de cada conta ativa da
empresa, por conta, campanha e anúncio, como tarefa da execução por empresa
(RF-04; ADR-0006; etl.execucao.TarefaCarga).

A extração lê as contas ativas e, no calendário, os períodos que tocam a
janela; depois, fora de transação, o alcance de cada conta em cada período e
nível e, pelo ID, os anúncios dele que ainda não estão no banco. A carga, já
na transação da empresa, grava as respostas em bruto, carrega essas
entidades e substitui o alcance da conta em cada período, nessa ordem
(RF-09, RF-17; ADR-0009 §5).
"""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final
from uuid import UUID

import psycopg

from etl.cadastro import listar_contas_ativas
from etl.carga import Contagens, carregar_alcance_periodo
from etl.cliente_api_meta import ClienteApiMeta
from etl.extracao import (
    Consulta,
    EntidadesExtraidas,
    NivelAlcance,
    PeriodoAlcance,
    TipoPeriodo,
    extrair_alcance_periodo,
    listar_anuncios_insights,
)
from etl.insights import carregar_bruto_e_entidades, extrair_anuncios_ausentes
from etl.transformacao import transformar_alcance_periodo

CONTAR_DIAS_CALENDARIO: Final = """
SELECT count(*) FROM normalizado.calendario WHERE data BETWEEN %(inicio)s AND %(fim)s
"""

# O calendário é a única fonte do agrupamento por semana, mês e ano
# (CLAUDE.md §5): a semana e o mês do primeiro dia da janela e cada ano que
# ela toca, todos cortados no último dia da janela ou do ano (ADR-0006).
LER_PERIODOS_JANELA: Final = """
WITH janela AS (
  SELECT data, inicio_semana, inicio_mes, ano
  FROM normalizado.calendario
  WHERE data BETWEEN %(inicio)s AND %(fim)s
)
SELECT 'semana' AS tipo, min(inicio_semana) AS inicio, max(data) AS fim, 1 AS ordem
FROM janela
UNION ALL
SELECT 'mes', min(inicio_mes), max(data), 2
FROM janela
UNION ALL
SELECT 'ano',
  (SELECT min(dia.data) FROM normalizado.calendario AS dia WHERE dia.ano = janela.ano),
  max(janela.data), 3
FROM janela
GROUP BY janela.ano
ORDER BY ordem, inicio
"""


class ErroCalendario(Exception):
    """A janela tem dias fora do calendário, e os períodos dela não teriam
    de onde vir. Estender o calendário é uma migration nova (ADR-0009)."""


@dataclass(frozen=True)
class AlcanceContaExtraido:
    conta_anuncio_id: UUID
    consultas: Mapping[PeriodoAlcance, Mapping[NivelAlcance, Consulta]]
    entidades: EntidadesExtraidas

    def listar_consultas(self) -> list[Consulta]:
        return [
            consulta
            for por_nivel in self.consultas.values()
            for consulta in por_nivel.values()
        ]


@dataclass(frozen=True)
class TarefaAlcancePeriodo:
    """O alcance dos períodos que tocam a janela de inicio a fim, inclusive,
    nas datas do fuso de cada conta, como a API as entrega (R-17)."""

    conectar: Callable[[], psycopg.Connection]
    cliente: ClienteApiMeta
    inicio: date
    fim: date

    def extrair(self, empresa_id: UUID) -> list[AlcanceContaExtraido]:
        # Conexão só para as leituras: a extração pode levar muito tempo, e a
        # conexão parada poderia ser derrubada pelo pooler.
        with self.conectar() as conexao:
            contas = listar_contas_ativas(conexao, empresa_id)
            periodos = ler_periodos_janela(conexao, self.inicio, self.fim)
        return [
            self.extrair_conta(empresa_id, conta_anuncio_id, id_meta, periodos)
            for conta_anuncio_id, id_meta in contas
        ]

    def extrair_conta(
        self,
        empresa_id: UUID,
        conta_anuncio_id: UUID,
        id_meta_conta: str,
        periodos: Sequence[PeriodoAlcance],
    ) -> AlcanceContaExtraido:
        """O alcance da conta em cada período e, pelo ID, os anúncios dele
        que o banco ainda não tem, com a campanha de cada um. A campanha com
        alcance tem anúncio com alcance no mesmo período."""
        consultas = {
            periodo: extrair_alcance_periodo(self.cliente, id_meta_conta, periodo)
            for periodo in periodos
        }
        ids_meta = [
            id_meta
            for por_nivel in consultas.values()
            for id_meta in listar_anuncios_insights(
                por_nivel[NivelAlcance.ANUNCIO].paginas
            )
        ]
        return AlcanceContaExtraido(
            conta_anuncio_id,
            consultas,
            extrair_anuncios_ausentes(
                self.conectar, self.cliente, empresa_id, list(dict.fromkeys(ids_meta))
            ),
        )

    def carregar(
        self,
        conexao: psycopg.Connection,
        empresa_id: UUID,
        execucao_id: UUID,
        dados: Sequence[AlcanceContaExtraido],
    ) -> Contagens:
        contagens: Counter[str] = Counter()
        for conta in dados:
            contagens.update(
                carregar_alcance_conta(
                    conexao, empresa_id, execucao_id, self.fim, conta
                )
            )
        return dict(contagens)


def ler_periodos_janela(
    conexao: psycopg.Connection, inicio: date, fim: date
) -> list[PeriodoAlcance]:
    """As consultas de alcance da janela, na ordem: a semana, o mês e cada
    ano, cada uma do since ao until (ADR-0006)."""
    conferir_calendario(conexao, inicio, fim)
    parametros = {"inicio": inicio, "fim": fim}
    return [
        PeriodoAlcance(TipoPeriodo(tipo), inicio_periodo, fim_periodo)
        for tipo, inicio_periodo, fim_periodo, _ in conexao.execute(
            LER_PERIODOS_JANELA, parametros
        ).fetchall()
    ]


def conferir_calendario(conexao: psycopg.Connection, inicio: date, fim: date) -> None:
    """Falha se algum dia de inicio a fim falta no calendário, a única fonte
    do agrupamento por semana, mês e ano (CLAUDE.md §5)."""
    if inicio > fim:
        raise ValueError("janela com início depois do fim")
    parametros = {"inicio": inicio, "fim": fim}
    dias = conexao.execute(CONTAR_DIAS_CALENDARIO, parametros).fetchone()[0]
    if dias != (fim - inicio).days + 1:
        raise ErroCalendario("janela com dias fora do calendário")


def carregar_alcance_conta(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    fim: date,
    conta: AlcanceContaExtraido,
) -> Contagens:
    """Grava as respostas em bruto com o fim da janela como data de
    referência e carrega as entidades lidas pelo ID antes do alcance, que
    depende delas pela FK; depois, substitui cada período com as linhas dos
    três níveis."""
    contagens = Counter(
        carregar_bruto_e_entidades(
            conexao,
            empresa_id,
            execucao_id,
            conta.conta_anuncio_id,
            fim,
            conta.listar_consultas(),
            conta.entidades,
        )
    )
    for periodo, por_nivel in conta.consultas.items():
        linhas = [
            linha
            for nivel, consulta in por_nivel.items()
            for linha in transformar_alcance_periodo(
                consulta.paginas, nivel, periodo.tipo
            )
        ]
        contagens.update(
            carregar_alcance_periodo(
                conexao,
                empresa_id,
                execucao_id,
                conta.conta_anuncio_id,
                periodo.tipo,
                periodo.inicio,
                periodo.fim,
                linhas,
            )
        )
    return dict(contagens)
