"""Mapa único dos campos da Marketing API para os nomes em português (RF-11).

Os nomes da Meta ficam só em `bruto`; a partir da transformação, todo campo
passa por este mapa, que diz o nome em português e o tipo padronizado de cada
um (RF-13). O mapa é organizado por objeto da API porque o mesmo nome muda de
sentido entre objetos: `value` é quantidade em `actions` e dinheiro em
`action_values`.

Cobre os campos das extrações de RF-01 a RF-04, conferidos em 04/11/2026 nas
referências da Meta citadas no ADR-0009 e em
https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights/,
e os dos resultados fora de actions, conferidos na API em 12/11/2026 (R-24).
Um campo novo entra aqui junto com a extração que o usa.

Os nomes em português são os das colunas de `normalizado` quando o campo vira
coluna direta. Os IDs da Meta que apontam para outra entidade viram
`id_meta_<entidade>`, porque a coluna de `normalizado` guarda a chave interna,
resolvida na carga.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Final

from etl.padronizacao import (
    ErroPadronizacao,
    padronizar_data,
    padronizar_dinheiro,
    padronizar_id_conta,
    padronizar_inteiro,
    padronizar_lista_texto,
    padronizar_texto,
)

type ValorTraduzido = (
    str
    | int
    | Decimal
    | date
    | None
    | list[str]
    | RegistroTraduzido
    | list[RegistroTraduzido]
)
type RegistroTraduzido = dict[str, ValorTraduzido]


class ObjetoApi(StrEnum):
    """Objeto da API cujos campos o mapa traduz. O valor é o nome na Meta."""

    CONTA = "AdAccount"
    CAMPANHA = "Campaign"
    CONJUNTO = "AdSet"
    JANELA_ATRIBUICAO = "AttributionSpec"
    ANUNCIO = "Ad"
    CRIATIVO = "AdCreative"
    PAGINA = "Page"
    PUBLICACAO = "PagePost"
    INSIGHTS = "AdsInsights"
    # AdsActionStats aparece em várias listas, e o value muda de tipo entre
    # elas: é quantidade em actions, video_thruplay_watched_actions e
    # conversions, e dinheiro em action_values.
    ACAO = "AdsActionStats em actions"
    VALOR_ACAO = "AdsActionStats em action_values"
    RESULTADO = "AdsInsightsResult"
    VALOR_RESULTADO = "AdsInsightsResult em values"


class TipoCampo(Enum):
    TEXTO = "texto"
    DINHEIRO = "dinheiro"
    INTEIRO = "inteiro"
    DATA = "data"
    ID_CONTA = "id_conta"
    LISTA_TEXTO = "lista_texto"
    # Compostos: os itens são outro objeto do mapa.
    LISTA = "lista"
    OBJETO = "objeto"


@dataclass(frozen=True)
class Campo:
    nome: str
    tipo: TipoCampo
    itens: ObjetoApi | None = None


class ErroCampoNaoMapeado(ValueError):
    """Campo da API sem entrada no mapa."""


PADRONIZADORES: Final[Mapping[TipoCampo, Callable[[object], ValorTraduzido]]] = {
    TipoCampo.TEXTO: padronizar_texto,
    TipoCampo.DINHEIRO: padronizar_dinheiro,
    TipoCampo.INTEIRO: padronizar_inteiro,
    TipoCampo.DATA: padronizar_data,
    TipoCampo.ID_CONTA: padronizar_id_conta,
    TipoCampo.LISTA_TEXTO: padronizar_lista_texto,
}

ID_META: Final = Campo("id_meta", TipoCampo.TEXTO)
NOME: Final = Campo("nome", TipoCampo.TEXTO)
# Domínio fechado da Meta (R-35), guardado como chega; o rótulo vem do
# catálogo (ADR-0009 §1).
STATUS: Final = Campo("status", TipoCampo.TEXTO)

MAPA_CAMPOS: Final[Mapping[ObjetoApi, Mapping[str, Campo]]] = {
    # O id da conta é act_<account_id>, e guardamos só o número (ADR-0009 §1).
    # A Graph API sempre devolve o id, então não pedimos o account_id.
    ObjetoApi.CONTA: {
        "id": Campo("id_meta", TipoCampo.ID_CONTA),
        "name": NOME,
        "timezone_name": Campo("fuso_horario", TipoCampo.TEXTO),
        "currency": Campo("moeda", TipoCampo.TEXTO),
    },
    ObjetoApi.CAMPANHA: {
        "id": ID_META,
        "name": NOME,
        "objective": Campo("objetivo", TipoCampo.TEXTO),
        "status": STATUS,
    },
    ObjetoApi.CONJUNTO: {
        "id": ID_META,
        "name": NOME,
        "optimization_goal": Campo("meta_otimizacao", TipoCampo.TEXTO),
        "status": STATUS,
        "campaign_id": Campo("id_meta_campanha", TipoCampo.TEXTO),
        "attribution_spec": Campo(
            "janelas_atribuicao", TipoCampo.LISTA, ObjetoApi.JANELA_ATRIBUICAO
        ),
    },
    ObjetoApi.JANELA_ATRIBUICAO: {
        "event_type": Campo("tipo_evento", TipoCampo.TEXTO),
        "window_days": Campo("janela_dias", TipoCampo.INTEIRO),
    },
    ObjetoApi.ANUNCIO: {
        "id": ID_META,
        "name": NOME,
        "status": STATUS,
        "adset_id": Campo("id_meta_conjunto", TipoCampo.TEXTO),
        "creative": Campo("criativo", TipoCampo.OBJETO, ObjetoApi.CRIATIVO),
    },
    # Origem dos campos da publicação: ADR-0009 §2 (R-27).
    ObjetoApi.CRIATIVO: {
        "id": ID_META,
        "title": Campo("titulo", TipoCampo.TEXTO),
        "body": Campo("texto", TipoCampo.TEXTO),
        "call_to_action_type": Campo("chamada_acao", TipoCampo.TEXTO),
        # URL temporária do CDN da Meta (R-26): serve só para baixar a imagem
        # para o Storage e não é guardada (RF-38).
        "thumbnail_url": Campo("url_miniatura", TipoCampo.TEXTO),
        "effective_object_story_id": Campo("id_publicacao_facebook", TipoCampo.TEXTO),
        "effective_instagram_media_id": Campo("id_midia_instagram", TipoCampo.TEXTO),
        "instagram_permalink_url": Campo("link_publicacao_instagram", TipoCampo.TEXTO),
        # O actor_id é o ID da Página (R-35).
        "actor_id": Campo("id_meta_pagina", TipoCampo.TEXTO),
    },
    ObjetoApi.PAGINA: {
        "id": ID_META,
        "name": NOME,
    },
    ObjetoApi.PUBLICACAO: {
        "id": Campo("id_publicacao_facebook", TipoCampo.TEXTO),
        "permalink_url": Campo("link_publicacao_facebook", TipoCampo.TEXTO),
    },
    # Uma linha de insights é sempre um período; na consulta diária, de um dia.
    # As quebras saem com o nome da dimensão, e a transformação delas decide a
    # categoria e a subcategoria.
    ObjetoApi.INSIGHTS: {
        # Não é pedido: vem em toda linha do resultado do job assíncrono
        # (R-39), e a transformação não o usa, porque a consulta já é da
        # conta.
        "account_id": Campo("id_meta_conta", TipoCampo.TEXTO),
        "ad_id": Campo("id_meta_anuncio", TipoCampo.TEXTO),
        "campaign_id": Campo("id_meta_campanha", TipoCampo.TEXTO),
        "date_start": Campo("inicio_periodo", TipoCampo.DATA),
        "date_stop": Campo("fim_periodo", TipoCampo.DATA),
        "spend": Campo("investimento", TipoCampo.DINHEIRO),
        "impressions": Campo("impressoes", TipoCampo.INTEIRO),
        "reach": Campo("alcance", TipoCampo.INTEIRO),
        "actions": Campo("acoes", TipoCampo.LISTA, ObjetoApi.ACAO),
        "action_values": Campo("valores_acoes", TipoCampo.LISTA, ObjetoApi.VALOR_ACAO),
        # Os resultados que a Meta conta fora de actions (R-24): a visita ao
        # perfil só vem em results; o ThruPlay e o contato no site, também
        # em listas próprias de AdsActionStats.
        "results": Campo("resultados", TipoCampo.LISTA, ObjetoApi.RESULTADO),
        "video_thruplay_watched_actions": Campo(
            "visualizacoes_thruplay", TipoCampo.LISTA, ObjetoApi.ACAO
        ),
        "conversions": Campo("conversoes", TipoCampo.LISTA, ObjetoApi.ACAO),
        "age": Campo("idade", TipoCampo.TEXTO),
        "gender": Campo("genero", TipoCampo.TEXTO),
        "publisher_platform": Campo("plataforma", TipoCampo.TEXTO),
        "platform_position": Campo("posicionamento", TipoCampo.TEXTO),
        "region": Campo("regiao", TipoCampo.TEXTO),
    },
    ObjetoApi.ACAO: {
        "action_type": Campo("tipo_acao", TipoCampo.TEXTO),
        "value": Campo("quantidade", TipoCampo.INTEIRO),
    },
    ObjetoApi.VALOR_ACAO: {
        "action_type": Campo("tipo_acao", TipoCampo.TEXTO),
        "value": Campo("valor", TipoCampo.DINHEIRO),
    },
    # O indicator é actions:<tipo de ação> ou o nome de outra métrica, e o
    # item sem resultado vem sem values (R-24).
    ObjetoApi.RESULTADO: {
        "indicator": Campo("indicador", TipoCampo.TEXTO),
        "values": Campo("valores", TipoCampo.LISTA, ObjetoApi.VALOR_RESULTADO),
    },
    # Sem janelas pedidas, attribution_windows é ["default"], e o valor da
    # visita ao perfil vem sem ela (R-24).
    ObjetoApi.VALOR_RESULTADO: {
        "value": Campo("quantidade", TipoCampo.INTEIRO),
        "attribution_windows": Campo("janelas_atribuicao", TipoCampo.LISTA_TEXTO),
    },
}

# Campos cujo nome na Meta também é o termo em português. O teste do mapa
# confere que são só estes.
CAMPOS_COM_NOME_IGUAL_EM_PORTUGUES: Final = frozenset({"status"})


def traduzir_registro(objeto: ObjetoApi, registro: object) -> RegistroTraduzido:
    """Traduz um registro da API para os nomes em português, com tipos padronizados.

    Devolve todos os campos do objeto no mapa, com None para o ausente. Um
    campo da API sem entrada no mapa levanta ErroCampoNaoMapeado: a
    transformação nunca lê um campo pelo nome da Meta nem o descarta em
    silêncio.
    """
    if not isinstance(registro, Mapping):
        raise ErroPadronizacao(f"Esperado objeto JSON em {objeto}.")
    campos = MAPA_CAMPOS[objeto]
    nao_mapeados = sorted(set(registro) - set(campos))
    if nao_mapeados:
        # Só os nomes dos campos, nunca os valores (CLAUDE.md §8).
        raise ErroCampoNaoMapeado(
            f"Campos sem entrada no mapa em {objeto}: {', '.join(nao_mapeados)}."
        )
    return {
        campo.nome: padronizar_campo(campo, registro.get(nome_api))
        for nome_api, campo in campos.items()
    }


def padronizar_campo(campo: Campo, valor: object) -> ValorTraduzido:
    if campo.itens is None:
        return PADRONIZADORES[campo.tipo](valor)
    if valor is None:
        return None
    if campo.tipo is TipoCampo.OBJETO:
        return traduzir_registro(campo.itens, valor)
    if not isinstance(valor, list):
        raise ErroPadronizacao(f"Esperada lista em {campo.nome}.")
    return [traduzir_registro(campo.itens, item) for item in valor]
