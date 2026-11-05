"""Extração de uma conta de anúncios: o cadastro, com a própria conta, as
campanhas, os conjuntos e os anúncios, com o criativo de cada anúncio expandido
(RF-01, RF-43), os insights diários por anúncio, com as entidades que eles
referenciam lidas pelo ID (RF-02; ADR-0009 §5), e o alcance por período, por
conta, campanha e anúncio (RF-04; ADR-0006). Só faz o I/O de rede, fora de
transação, e devolve as páginas como a Meta as entregou, para a gravação em
bruto antes da transformação (RF-09; CLAUDE.md §3).
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo

from etl.cliente_api_meta import ClienteApiMeta, Endpoint, ErroRespostaInvalida
from etl.configuracao import LIMITE_PAGINA_CADASTRO, LIMITE_PAGINA_INSIGHTS
from etl.mapa_campos import MAPA_CAMPOS, ObjetoApi, TipoCampo

PREFIXO_ID_CONTA: Final = "act_"

# Sem filtro de status, as arestas omitem os objetos ARCHIVED, que os insights
# incluem. A lista é a documentada sem DELETED, que a API recusa no parâmetro;
# com ela, as três arestas devolvem todos os objetos não excluídos (R-38).
STATUS_EFETIVOS_CADASTRO: Final = (
    "ACTIVE",
    "PAUSED",
    "PENDING_REVIEW",
    "DISAPPROVED",
    "PREAPPROVED",
    "PENDING_BILLING_INFO",
    "CAMPAIGN_PAUSED",
    "ARCHIVED",
    "ADSET_PAUSED",
    "IN_PROCESS",
    "WITH_ISSUES",
)

# Campos do mapa que o cadastro não pede. Com a URL da miniatura, a aresta de
# anúncios falha com o código 1 mesmo no LIMITE_PAGINA_CADASTRO (R-42), e a
# URL, que vence em poucos dias, só serve à cópia para o Storage (RF-38;
# R-26).
CAMPOS_FORA_DO_CADASTRO: Final = frozenset({"thumbnail_url"})

# De baixo para cima: o pai de um objeto já existe quando a aresta do pai é
# lida, mesmo que tenha sido criado durante a leitura das outras. Na ordem
# inversa, uma campanha criada depois da leitura das campanhas, com anúncio
# lido em seguida, deixaria o anúncio sem pai e faria a empresa falhar.
ARESTAS_CADASTRO: Final[Mapping[Endpoint, ObjetoApi]] = {
    Endpoint.ANUNCIOS: ObjetoApi.ANUNCIO,
    Endpoint.CONJUNTOS: ObjetoApi.CONJUNTO,
    Endpoint.CAMPANHAS: ObjetoApi.CAMPANHA,
}


# Os campos de AdsInsights do RF-02. Os cliques no link vêm de actions, pelo
# tipo link_click (métrica cliques_link do catálogo), e date_start e date_stop vêm
# em toda linha sem ser pedidos. Sem use_unified_attribution_setting nem
# action_attribution_windows: os resultados ficam na janela padrão da API
# (ADR-0007; R-22).
CAMPOS_INSIGHTS_DIARIOS: Final = (
    "ad_id",
    "spend",
    "impressions",
    "reach",
    "actions",
    "action_values",
)
NIVEL_ANUNCIO: Final = "ad"
INCREMENTO_DIARIO: Final = "1"
# Sem filtro, a lista por anúncio omite os excluídos, cujas métricas entram
# na soma da conta: a soma no banco ficaria abaixo da API (RF-02). Os
# insights aceitam DELETED no filtro, ao contrário das arestas, e com a lista
# completa devolvem as mesmas linhas da consulta sem filtro para os demais
# status (R-38).
FILTRO_STATUS_INSIGHTS: Final = json.dumps(
    [
        {
            "field": "ad.effective_status",
            "operator": "IN",
            "value": [*STATUS_EFETIVOS_CADASTRO, "DELETED"],
        }
    ]
)


class TipoPeriodo(StrEnum):
    """Os tipos de período do CHECK de alcance_periodo."""

    SEMANA = "semana"
    MES = "mes"
    ANO = "ano"


# O time_increment de cada tipo (ADR-0006; R-20). Com o since numa
# segunda-feira, os blocos de 7 dias são as semanas ISO; com o since no dia
# 1, os de monthly são os meses de calendário; o ano é o intervalo inteiro.
INCREMENTOS_PERIODO: Final[Mapping[TipoPeriodo, str]] = {
    TipoPeriodo.SEMANA: "7",
    TipoPeriodo.MES: "monthly",
    TipoPeriodo.ANO: "all_days",
}


class NivelAlcance(StrEnum):
    """Os níveis do alcance por período. O valor é o level da API."""

    CONTA = "account"
    CAMPANHA = "campaign"
    ANUNCIO = "ad"


# No nível de conta, a linha é da própria conta consultada e dispensa o ID.
# date_start e date_stop vêm em toda linha sem ser pedidos.
CAMPOS_ALCANCE_PERIODO: Final[Mapping[NivelAlcance, tuple[str, ...]]] = {
    NivelAlcance.CONTA: ("reach", "impressions"),
    NivelAlcance.CAMPANHA: ("campaign_id", "reach", "impressions"),
    NivelAlcance.ANUNCIO: ("ad_id", "reach", "impressions"),
}


@dataclass(frozen=True)
class PeriodoAlcance:
    """Uma consulta de alcance: o tipo de período, do since ao until."""

    tipo: TipoPeriodo
    inicio: date
    fim: date


@dataclass(frozen=True)
class Consulta:
    """Uma consulta à API e as páginas que ela devolveu, na ordem."""

    endpoint: Endpoint
    parametros: Mapping[str, str]
    paginas: Sequence[dict[str, object]]


@dataclass(frozen=True)
class CadastroExtraido:
    """O cadastro de uma conta como a Meta o entregou.

    data_referencia é a data da extração no fuso da conta, que a retenção de
    bruto usa nas consultas de cadastro (RF-21; ADR-0009 §2).
    """

    id_meta_conta: str
    data_referencia: date
    conta: Consulta
    arestas: Mapping[Endpoint, Consulta]

    def listar_consultas(self) -> tuple[Consulta, ...]:
        return (self.conta, *self.arestas.values())


@dataclass(frozen=True)
class EntidadesExtraidas:
    """Os anúncios lidos pelo ID, com o criativo, e o conjunto e a campanha
    de cada um, uma resposta por objeto."""

    anuncios: Consulta
    conjuntos: Consulta
    campanhas: Consulta

    def listar_consultas(self) -> tuple[Consulta, ...]:
        return (self.anuncios, self.conjuntos, self.campanhas)


def agora_utc() -> datetime:
    return datetime.now(UTC)


def montar_campos(objeto: ObjetoApi) -> str:
    """O parâmetro fields com os campos do objeto no mapa, e só eles, salvo
    os de CAMPOS_FORA_DO_CADASTRO.

    Pedir pelo mapa garante que a transformação encontra cada campo
    recebido no mapa (RF-11). Um objeto aninhado, como o criativo do
    anúncio, é expandido com os campos dele; as listas, como o
    attribution_spec, vêm inteiras pelo nome.
    """
    partes = []
    for nome_api, campo in MAPA_CAMPOS[objeto].items():
        if nome_api in CAMPOS_FORA_DO_CADASTRO:
            continue
        if campo.tipo is TipoCampo.OBJETO and campo.itens is not None:
            partes.append(f"{nome_api}{{{montar_campos(campo.itens)}}}")
        else:
            partes.append(nome_api)
    return ",".join(partes)


def montar_parametros_aresta(objeto: ObjetoApi) -> dict[str, str]:
    return {
        "fields": montar_campos(objeto),
        "effective_status": json.dumps(list(STATUS_EFETIVOS_CADASTRO)),
        "limit": str(LIMITE_PAGINA_CADASTRO),
    }


def extrair_cadastro_conta(
    cliente: ClienteApiMeta,
    id_meta_conta: str,
    relogio: Callable[[], datetime] = agora_utc,
) -> CadastroExtraido:
    """Lê a conta e, paginados, os anúncios, os conjuntos e as campanhas dela.

    A conta vem primeiro porque o fuso dela dá a data de referência. Uma
    falha em qualquer consulta sobe sem devolver nada, e a empresa falha
    sem gravar parte do cadastro.
    """
    objeto_conta = f"{PREFIXO_ID_CONTA}{id_meta_conta}"
    parametros_conta = {"fields": montar_campos(ObjetoApi.CONTA)}
    resposta_conta = cliente.obter(objeto_conta, Endpoint.OBJETO, parametros_conta)
    conta = Consulta(Endpoint.OBJETO, parametros_conta, [resposta_conta])
    arestas = {}
    for endpoint, objeto in ARESTAS_CADASTRO.items():
        parametros = montar_parametros_aresta(objeto)
        paginas = cliente.paginar(objeto_conta, endpoint, parametros)
        arestas[endpoint] = Consulta(endpoint, parametros, paginas)
    return CadastroExtraido(
        id_meta_conta=id_meta_conta,
        data_referencia=calcular_data_referencia(resposta_conta, relogio()),
        conta=conta,
        arestas=arestas,
    )


def calcular_data_referencia(
    resposta_conta: Mapping[str, object], instante: datetime
) -> date:
    """A data do instante no fuso da conta, como a Meta o informa."""
    fuso = resposta_conta.get("timezone_name")
    if not isinstance(fuso, str) or not fuso:
        raise ErroRespostaInvalida()
    return instante.astimezone(ZoneInfo(fuso)).date()


def montar_parametros_insights_diarios(inicio: date, fim: date) -> dict[str, str]:
    return {
        "level": NIVEL_ANUNCIO,
        "time_increment": INCREMENTO_DIARIO,
        "time_range": json.dumps(
            {"since": inicio.isoformat(), "until": fim.isoformat()}
        ),
        "fields": ",".join(CAMPOS_INSIGHTS_DIARIOS),
        "filtering": FILTRO_STATUS_INSIGHTS,
        "limit": str(LIMITE_PAGINA_INSIGHTS),
    }


def extrair_insights_diarios(
    cliente: ClienteApiMeta, id_meta_conta: str, inicio: date, fim: date
) -> Consulta:
    """Uma única consulta paginada da conta no nível de anúncio, com uma
    linha por anúncio e dia de inicio a fim, inclusive, em vez de uma
    consulta por anúncio (ADR-0003). As datas são as do fuso da conta, como
    a API as entrega (R-17)."""
    parametros = montar_parametros_insights_diarios(inicio, fim)
    paginas = cliente.ler_insights(f"{PREFIXO_ID_CONTA}{id_meta_conta}", parametros)
    return Consulta(Endpoint.INSIGHTS, parametros, paginas)


def listar_anuncios_insights(paginas: Sequence[Mapping[str, object]]) -> list[str]:
    """Os IDs dos anúncios das linhas de insights, sem repetição e na ordem,
    para a conferência das entidades ausentes do banco."""
    return listar_ids_insights(paginas, "ad_id")


def listar_ids_insights(
    paginas: Sequence[Mapping[str, object]], campo: str
) -> list[str]:
    """Os IDs do campo em cada linha de insights, sem repetição e na ordem."""
    ids = []
    for pagina in paginas:
        linhas = pagina.get("data")
        if not isinstance(linhas, list):
            raise ErroRespostaInvalida()
        ids.extend(ler_id_referenciado(linha, campo) for linha in linhas)
    return list(dict.fromkeys(ids))


def extrair_entidades_por_id(
    cliente: ClienteApiMeta, ids_anuncios: Sequence[str]
) -> EntidadesExtraidas:
    """Lê pelo ID cada anúncio, com o criativo expandido, depois o conjunto
    de cada um e a campanha de cada conjunto, cada objeto uma vez só.

    Serve aos anúncios dos insights que ainda não estão no banco: criados
    depois do último cadastro ou excluídos, que as arestas não devolvem e
    que continuam legíveis pelo ID (R-38). O conjunto e a campanha são lidos mesmo que já existam, para que
    todo filho tenha o pai na mesma extração.
    """
    anuncios = ler_objetos(cliente, ObjetoApi.ANUNCIO, ids_anuncios)
    conjuntos = ler_objetos(
        cliente, ObjetoApi.CONJUNTO, listar_referencias(anuncios, "adset_id")
    )
    campanhas = ler_objetos(
        cliente, ObjetoApi.CAMPANHA, listar_referencias(conjuntos, "campaign_id")
    )
    return EntidadesExtraidas(anuncios, conjuntos, campanhas)


def ler_objetos(
    cliente: ClienteApiMeta, objeto: ObjetoApi, ids: Sequence[str]
) -> Consulta:
    parametros = {"fields": montar_campos(objeto)}
    return Consulta(
        Endpoint.OBJETO,
        parametros,
        [cliente.obter(id_meta, Endpoint.OBJETO, parametros) for id_meta in ids],
    )


def listar_referencias(consulta: Consulta, campo: str) -> list[str]:
    """Os IDs do pai, sem repetição e na ordem."""
    return list(
        dict.fromkeys(ler_id_referenciado(objeto, campo) for objeto in consulta.paginas)
    )


def ler_id_referenciado(objeto: object, campo: str) -> str:
    """O ID de outra entidade num objeto da API. Sem ele, a entidade não teria
    como ser lida nem ligada ao pai."""
    valor = objeto.get(campo) if isinstance(objeto, Mapping) else None
    if not isinstance(valor, str) or not valor:
        raise ErroRespostaInvalida()
    return valor


def montar_parametros_alcance(
    nivel: NivelAlcance, periodo: PeriodoAlcance
) -> dict[str, str]:
    """Nos níveis de campanha e de anúncio, o filtro dos insights diários,
    porque a lista por nível omite os objetos excluídos (R-38; ADR-0006)."""
    parametros = {
        "level": nivel,
        "time_increment": INCREMENTOS_PERIODO[periodo.tipo],
        "time_range": json.dumps(
            {"since": periodo.inicio.isoformat(), "until": periodo.fim.isoformat()}
        ),
        "fields": ",".join(CAMPOS_ALCANCE_PERIODO[nivel]),
        "limit": str(LIMITE_PAGINA_INSIGHTS),
    }
    if nivel is not NivelAlcance.CONTA:
        parametros["filtering"] = FILTRO_STATUS_INSIGHTS
    return parametros


def extrair_alcance_periodo(
    cliente: ClienteApiMeta, id_meta_conta: str, periodo: PeriodoAlcance
) -> dict[NivelAlcance, Consulta]:
    """O alcance e as impressões do período já agregados pela API, numa
    consulta paginada da conta por nível, com todas as entidades do nível,
    em vez de uma consulta por entidade (R-15; ADR-0006)."""
    objeto_conta = f"{PREFIXO_ID_CONTA}{id_meta_conta}"
    consultas = {}
    for nivel in NivelAlcance:
        parametros = montar_parametros_alcance(nivel, periodo)
        paginas = cliente.ler_insights(objeto_conta, parametros)
        consultas[nivel] = Consulta(Endpoint.INSIGHTS, parametros, paginas)
    return consultas
