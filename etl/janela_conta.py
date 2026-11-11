"""A janela de uma conta: os insights diários, as quebras e o alcance de um
intervalo, com as entidades que eles referenciam lidas pelo ID, extraídos e
carregados juntos (RF-02, RF-03, RF-04; ADR-0009 §5).

A extração faz só o I/O de rede, fora de transação, e lê pelo ID só o que o
banco não tem: o cadastro completo da conta já entrou na carga inicial, antes
de qualquer janela (ADR-0017). A carga roda na transação de quem chama, na
ordem insights, quebras e alcance: as quebras resolvem o resultado principal
pelo que os insights acabaram de carregar (ADR-0011).
"""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import psycopg

from etl.alcance import AlcanceContaExtraido, carregar_alcance_conta
from etl.carga import Contagens
from etl.cliente_api_meta import ClienteApiMeta
from etl.extracao import (
    NivelAlcance,
    PeriodoAlcance,
    extrair_alcance_periodo,
    extrair_entidades_por_id,
    extrair_insights_diarios,
    extrair_quebras_campanha,
    listar_anuncios_insights,
    listar_ids_insights,
)
from etl.insights import (
    InsightsContaExtraidos,
    carregar_insights_conta,
    extrair_anuncios_ausentes,
)
from etl.quebras import (
    QuebrasContaExtraidas,
    carregar_quebras_conta,
    extrair_campanhas_ausentes,
)


@dataclass(frozen=True)
class JanelaContaExtraida:
    """O que uma conta teve lido de inicio a fim, inclusive, com o alcance dos
    períodos pedidos."""

    conta_anuncio_id: UUID
    inicio: date
    fim: date
    insights: InsightsContaExtraidos
    quebras: QuebrasContaExtraidas
    alcance: AlcanceContaExtraido


def extrair_janela_conta(
    conectar: Callable[[], psycopg.Connection],
    cliente: ClienteApiMeta,
    empresa_id: UUID,
    conta_anuncio_id: UUID,
    id_meta_conta: str,
    inicio: date,
    fim: date,
    periodos: Sequence[PeriodoAlcance],
) -> JanelaContaExtraida:
    """Os insights e as quebras de inicio a fim, o alcance de cada período e,
    pelo ID, as entidades delas que o banco não tem. Os anúncios lidos pelo
    ID entram com os insights, antes do alcance, que também depende deles
    pela FK."""
    insights = extrair_insights_diarios(cliente, id_meta_conta, inicio, fim)
    quebras = extrair_quebras_campanha(cliente, id_meta_conta, inicio, fim)
    alcance = {
        periodo: extrair_alcance_periodo(cliente, id_meta_conta, periodo)
        for periodo in periodos
    }
    anuncios = listar_anuncios_insights(
        [
            *insights.paginas,
            *(
                pagina
                for por_nivel in alcance.values()
                for pagina in por_nivel[NivelAlcance.ANUNCIO].paginas
            ),
        ]
    )
    campanhas = listar_ids_insights(
        [pagina for consulta in quebras.values() for pagina in consulta.paginas],
        "campaign_id",
    )
    return JanelaContaExtraida(
        conta_anuncio_id,
        inicio,
        fim,
        InsightsContaExtraidos(
            conta_anuncio_id,
            insights,
            extrair_anuncios_ausentes(conectar, cliente, empresa_id, anuncios),
        ),
        QuebrasContaExtraidas(
            conta_anuncio_id,
            quebras,
            extrair_campanhas_ausentes(conectar, cliente, empresa_id, campanhas),
        ),
        AlcanceContaExtraido(
            conta_anuncio_id, alcance, extrair_entidades_por_id(cliente, [])
        ),
    )


def carregar_janela_conta(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    janela: JanelaContaExtraida,
) -> Contagens:
    """Carrega a janela na transação de quem chama, com os insights antes das
    quebras (ADR-0011) e o alcance por último."""
    contagens = Counter(
        carregar_insights_conta(
            conexao,
            empresa_id,
            execucao_id,
            janela.inicio,
            janela.fim,
            janela.insights,
        )
    )
    contagens.update(
        carregar_quebras_conta(
            conexao, empresa_id, execucao_id, janela.inicio, janela.fim, janela.quebras
        )
    )
    # O alcance de uma fatia histórica vai além dela, como a semana que
    # termina no mês seguinte e o ano da fatia de janeiro: a data de
    # referência do bruto é o último dia consultado (ADR-0009 §2). Na revisão
    # diária, os períodos terminam no fim da janela.
    referencia_alcance = max(
        [janela.fim, *(periodo.fim for periodo in janela.alcance.consultas)]
    )
    contagens.update(
        carregar_alcance_conta(
            conexao, empresa_id, execucao_id, referencia_alcance, janela.alcance
        )
    )
    return dict(contagens)
