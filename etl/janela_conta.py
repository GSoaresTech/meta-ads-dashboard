"""A janela de uma conta: os insights diários, as quebras e o alcance de um
intervalo, com as entidades que eles referenciam lidas pelo ID, extraídos e
carregados juntos (RF-02, RF-03, RF-04; ADR-0009 §5).

A extração faz só o I/O de rede, fora de transação, e lê pelo ID só o que
nem o banco nem o cadastro lido na mesma execução têm: o cadastro ainda não
foi carregado quando as consultas terminam, e numa conta nova a conferência
só com o banco leria pelo ID cada anúncio com entrega no ano. A carga roda na
transação de quem chama, na ordem insights, quebras e alcance: as quebras
resolvem o resultado principal pelo que os insights acabaram de carregar
(ADR-0011).
"""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import psycopg

from etl.alcance import AlcanceContaExtraido, carregar_alcance_conta
from etl.carga import Contagens
from etl.cliente_api_meta import ClienteApiMeta, Endpoint
from etl.extracao import (
    CadastroExtraido,
    Consulta,
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
    cadastro: CadastroExtraido | None = None,
) -> JanelaContaExtraida:
    """Os insights e as quebras de inicio a fim, o alcance de cada período e,
    pelo ID, as entidades delas que o cadastro dado e o banco não têm. Os
    anúncios lidos pelo ID entram com os insights, antes do alcance, que
    também depende deles pela FK."""
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
            extrair_anuncios_ausentes(
                conectar,
                cliente,
                empresa_id,
                retirar_cadastrados(anuncios, cadastro, Endpoint.ANUNCIOS),
            ),
        ),
        QuebrasContaExtraidas(
            conta_anuncio_id,
            quebras,
            extrair_campanhas_ausentes(
                conectar,
                cliente,
                empresa_id,
                retirar_cadastrados(campanhas, cadastro, Endpoint.CAMPANHAS),
            ),
        ),
        AlcanceContaExtraido(
            conta_anuncio_id, alcance, extrair_entidades_por_id(cliente, [])
        ),
    )


def retirar_cadastrados(
    ids_meta: Sequence[str], cadastro: CadastroExtraido | None, endpoint: Endpoint
) -> list[str]:
    """Os IDs dados que a aresta do cadastro não trouxe, na ordem. Sem
    cadastro lido, todos."""
    if cadastro is None:
        return list(ids_meta)
    aresta: Consulta = cadastro.arestas[endpoint]
    cadastrados = set(listar_ids_insights(aresta.paginas, "id"))
    return [id_meta for id_meta in ids_meta if id_meta not in cadastrados]


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
    # referência do bruto é o último dia consultado (ADR-0009 §2). Na rotina
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
