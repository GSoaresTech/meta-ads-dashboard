"""Transformação pura das respostas da API nas linhas de normalizado: o
cadastro de uma conta, com a conta, as campanhas, os conjuntos com as janelas
de atribuição, as Páginas, os criativos e os anúncios (RF-01), e os insights
diários por anúncio, com as métricas e a tabela longa das ações, inclusive
os resultados que a Meta conta fora de actions (RF-02, RF-12; R-24), as quebras diárias por campanha, com a ação do resultado principal
(RF-03), e o alcance por período (RF-04). Os nomes e os tipos vêm do mapa de
campos (RF-11, RF-13). Sem rede, banco nem relógio (CLAUDE.md §8).

As linhas apontam para o pai pelo ID da Meta (id_meta_<entidade>), porque a
chave interna só existe depois do upsert do pai, na carga. As mensagens de
erro trazem só contagens, nunca IDs nem nomes, porque podem chegar aos logs
públicos (RNF-17).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

from etl.extracao import DIMENSOES_QUEBRA, NivelAlcance, TipoPeriodo, TipoQuebra
from etl.mapa_campos import (
    MAPA_CAMPOS,
    ObjetoApi,
    RegistroTraduzido,
    traduzir_registro,
)
from etl.padronizacao import ErroPadronizacao

type LinhaCadastro = dict[str, object]

# Colunas do criativo em normalizado. A url_miniatura, que o mapa traduz, não
# é guardada: é uma URL temporária do CDN da Meta, que só serve para copiar a
# imagem para o Storage (RF-38; R-26), e o cadastro nem a pede.
COLUNAS_CRIATIVO = (
    "id_meta",
    "id_meta_pagina",
    "titulo",
    "texto",
    "chamada_acao",
    "id_publicacao_facebook",
    "id_midia_instagram",
    "link_publicacao_instagram",
)


# Os pares de lista da API e medida da tabela longa das ações (RF-12): a
# quantidade vem de actions, e o valor, de action_values.
MEDIDAS_ACAO: Final = (("acoes", "quantidade"), ("valores_acoes", "valor"))


@dataclass(frozen=True)
class ResultadoForaDeActions:
    """Um resultado que a Meta conta fora de actions (R-24): o indicator dele
    em results e, quando existe, a lista traduzida e o tipo do item que
    trazem o mesmo valor em todo anúncio, e não só naquele em que ele é o
    resultado."""

    indicador: str
    lista: str | None = None
    tipo_item: str | None = None

    @property
    def tipo_acao(self) -> str:
        """O tipo na tabela longa das ações: o indicator, com ponto no lugar
        dos dois-pontos, que o formato do tipo de ação não aceita (ADR-0009
        §2)."""
        return self.indicador.replace(":", ".")


# Os resultados das regras do catálogo que não vêm em actions (REQUIREMENTS
# §7.2). Os demais tipos de conversions não são resultado de nenhuma regra, e
# os eventos personalizados trazem o nome do evento, fora do formato do tipo
# de ação.
RESULTADOS_FORA_DE_ACTIONS: Final = (
    ResultadoForaDeActions("profile_visit_view"),
    ResultadoForaDeActions(
        "video_thruplay_watched_actions", "visualizacoes_thruplay", "video_view"
    ),
    ResultadoForaDeActions(
        "conversions:contact_website", "conversoes", "contact_website"
    ),
)
# Os indicators lidos de results: os dos resultados que não vêm em outro
# campo.
INDICADORES_LIDOS_DE_RESULTS: Final = frozenset(
    resultado.indicador
    for resultado in RESULTADOS_FORA_DE_ACTIONS
    if resultado.lista is None
)

# A entidade de cada nível do alcance por período, pelo ID da Meta; a linha
# da conta não tem nenhuma, porque é da própria conta consultada.
ENTIDADES_ALCANCE: Final = ("id_meta_campanha", "id_meta_anuncio")
ENTIDADE_POR_NIVEL: Final[Mapping[NivelAlcance, str | None]] = {
    NivelAlcance.CONTA: None,
    NivelAlcance.CAMPANHA: "id_meta_campanha",
    NivelAlcance.ANUNCIO: "id_meta_anuncio",
}


class ErroCadastro(ValueError):
    """Cadastro da API incoerente, que a carga não pode gravar."""


class ErroInsights(ValueError):
    """Insights da API fora do grão anúncio × dia, que a carga não pode
    gravar."""


# O grão de uma linha de quebra, com a campanha pelo ID da Meta.
GRAO_QUEBRA: Final = (
    "id_meta_campanha",
    "data",
    "tipo_quebra",
    "categoria",
    "subcategoria",
)
# As dimensões de cada tipo de quebra com o nome em português, pelo mapa de
# campos (RF-11).
COLUNAS_DIMENSAO: Final[Mapping[TipoQuebra, tuple[str, ...]]] = {
    tipo: tuple(MAPA_CAMPOS[ObjetoApi.INSIGHTS][nome].nome for nome in dimensoes)
    for tipo, dimensoes in DIMENSOES_QUEBRA.items()
}


class ErroQuebra(ValueError):
    """Quebra da API fora do grão campanha × dia × categoria, que a carga não
    pode gravar."""


class ErroAlcance(ValueError):
    """Alcance da API fora do grão entidade × período, que a carga não pode
    gravar."""


@dataclass(frozen=True)
class EntidadesConta:
    """As linhas das entidades e dos criativos de uma conta, prontas para a
    carga."""

    campanhas: list[LinhaCadastro]
    conjuntos: list[LinhaCadastro]
    janelas: list[LinhaCadastro]
    paginas: list[str]
    criativos: list[LinhaCadastro]
    anuncios: list[LinhaCadastro]


@dataclass(frozen=True)
class InsightsDiarios:
    """As métricas de cada anúncio e dia e as ações deles, uma linha por
    tipo, com o anúncio pelo ID da Meta."""

    metricas: list[LinhaCadastro]
    acoes: list[LinhaCadastro]


@dataclass(frozen=True)
class QuebrasCampanha:
    """As linhas de uma quebra e a ação do resultado principal de cada uma,
    com a campanha pelo ID da Meta."""

    quebras: list[LinhaCadastro]
    acoes: list[LinhaCadastro]


@dataclass(frozen=True)
class CadastroConta(EntidadesConta):
    """As entidades de uma conta e o nome, o fuso e a moeda dela."""

    conta: LinhaCadastro


def transformar_cadastro(
    id_meta_conta: str,
    resposta_conta: Mapping[str, object],
    paginas_campanhas: Sequence[Mapping[str, object]],
    paginas_conjuntos: Sequence[Mapping[str, object]],
    paginas_anuncios: Sequence[Mapping[str, object]],
) -> CadastroConta:
    entidades = transformar_entidades(
        ler_registros(paginas_campanhas),
        ler_registros(paginas_conjuntos),
        ler_registros(paginas_anuncios),
    )
    return CadastroConta(
        conta=transformar_conta(id_meta_conta, resposta_conta), **vars(entidades)
    )


def transformar_entidades(
    registros_campanhas: Iterable[object],
    registros_conjuntos: Iterable[object],
    registros_anuncios: Iterable[object],
) -> EntidadesConta:
    """As campanhas, os conjuntos e os anúncios, com os criativos e as
    Páginas, recusando o filho cujo pai não veio junto."""
    campanhas = transformar_campanhas(registros_campanhas)
    conjuntos, janelas = transformar_conjuntos(registros_conjuntos)
    anuncios, criativos = transformar_anuncios(registros_anuncios)
    validar_referencias(conjuntos, "id_meta_campanha", campanhas)
    validar_referencias(anuncios, "id_meta_conjunto", conjuntos)
    return EntidadesConta(
        campanhas=campanhas,
        conjuntos=conjuntos,
        janelas=janelas,
        paginas=listar_paginas(criativos),
        criativos=criativos,
        anuncios=anuncios,
    )


def ler_registros(paginas: Sequence[Mapping[str, object]]) -> list[object]:
    """Os objetos de todas as páginas de uma aresta, na ordem."""
    registros: list[object] = []
    for pagina in paginas:
        dados = pagina.get("data")
        if not isinstance(dados, list):
            raise ErroPadronizacao("Esperada lista em data.")
        registros.extend(dados)
    return registros


def transformar_conta(
    id_meta_conta: str, resposta: Mapping[str, object]
) -> LinhaCadastro:
    """Nome, fuso e moeda da conta, que o cadastro informa só pelo ID
    (RF-43)."""
    conta = traduzir_registro(ObjetoApi.CONTA, resposta)
    if conta["id_meta"] != id_meta_conta:
        raise ErroCadastro("resposta de outra conta")
    return {chave: conta[chave] for chave in ("nome", "fuso_horario", "moeda")}


def transformar_campanhas(registros: Iterable[object]) -> list[LinhaCadastro]:
    return manter_ultima_por_id_meta(
        traduzir_registro(ObjetoApi.CAMPANHA, registro) for registro in registros
    )


def transformar_conjuntos(
    registros: Iterable[object],
) -> tuple[list[LinhaCadastro], list[LinhaCadastro]]:
    """Os conjuntos e, numa lista longa, as janelas de atribuição de cada um
    (ADR-0009 §2). Um conjunto sem attribution_spec fica sem janelas."""
    conjuntos = manter_ultima_por_id_meta(
        traduzir_registro(ObjetoApi.CONJUNTO, registro) for registro in registros
    )
    janelas = [
        {"id_meta_conjunto": conjunto["id_meta"], **janela}
        for conjunto in conjuntos
        for janela in conjunto.pop("janelas_atribuicao") or ()
    ]
    return conjuntos, janelas


def transformar_anuncios(
    registros: Iterable[object],
) -> tuple[list[LinhaCadastro], list[LinhaCadastro]]:
    """Os anúncios e os criativos deles, cada criativo uma vez só, porque um
    criativo serve a vários anúncios (N:1)."""
    anuncios = manter_ultima_por_id_meta(
        traduzir_registro(ObjetoApi.ANUNCIO, registro) for registro in registros
    )
    criativos = [anuncio.pop("criativo") for anuncio in anuncios]
    if any(criativo is None for criativo in criativos):
        raise ErroCadastro("anúncio sem criativo")
    for anuncio, criativo in zip(anuncios, criativos, strict=True):
        anuncio["id_meta_criativo"] = criativo["id_meta"]
    return anuncios, manter_ultima_por_id_meta(
        {coluna: criativo[coluna] for coluna in COLUNAS_CRIATIVO}
        for criativo in criativos
    )


def listar_paginas(criativos: Iterable[LinhaCadastro]) -> list[str]:
    """As Páginas dos criativos, pelo actor_id, sem repetição e na ordem."""
    paginas = (criativo["id_meta_pagina"] for criativo in criativos)
    return list(dict.fromkeys(pagina for pagina in paginas if pagina is not None))


def manter_ultima_por_id_meta(
    linhas: Iterable[RegistroTraduzido | LinhaCadastro],
) -> list[LinhaCadastro]:
    """Uma linha por id_meta, a da última leitura, na ordem da primeira.

    A paginação por cursor pode repetir um objeto alterado durante a
    leitura, e o mesmo criativo vem em cada anúncio que o usa.
    """
    por_id_meta: dict[object, LinhaCadastro] = {}
    for linha in linhas:
        if linha["id_meta"] is None:
            raise ErroCadastro("objeto sem id")
        por_id_meta[linha["id_meta"]] = dict(linha)
    return list(por_id_meta.values())


def validar_referencias(
    filhos: Iterable[LinhaCadastro], chave_pai: str, pais: Iterable[LinhaCadastro]
) -> None:
    """Todo filho aponta para um pai da mesma extração. Sem isso, a carga não
    teria a chave interna do pai para a FK."""
    ids_pais = {pai["id_meta"] for pai in pais}
    ausentes = sum(1 for filho in filhos if filho[chave_pai] not in ids_pais)
    if ausentes:
        raise ErroCadastro(f"{ausentes} objeto(s) com {chave_pai} fora da extração")


def transformar_insights_diarios(
    paginas: Sequence[Mapping[str, object]],
) -> InsightsDiarios:
    """Uma métrica por linha de insights e uma ação por tipo da linha, salvo
    nas linhas sem entrega nem ação (tem_entrega_ou_acao).

    A ausência de um tipo de ação é a ausência da linha, porque a API omite
    os tipos sem ocorrência (CLAUDE.md §5). Um anúncio e dia repetidos são
    recusados: a carga substitui o conjunto completo, e uma das duas linhas
    se perderia.
    """
    metricas: list[LinhaCadastro] = []
    acoes: list[LinhaCadastro] = []
    for registro in ler_registros(paginas):
        linha = traduzir_registro(ObjetoApi.INSIGHTS, registro)
        grao = ler_grao(linha)
        acoes_linha = combinar_acoes(linha)
        if not tem_entrega_ou_acao(linha, acoes_linha):
            continue
        metricas.append(
            {
                **grao,
                "investimento": linha["investimento"],
                "impressoes": linha["impressoes"],
                "alcance": linha["alcance"],
            }
        )
        acoes.extend({**grao, **acao} for acao in acoes_linha)
    repetidos = len(metricas) - len(
        {(m["id_meta_anuncio"], m["data"]) for m in metricas}
    )
    if repetidos:
        raise ErroInsights(f"{repetidos} linha(s) de anúncio e dia repetidas")
    return InsightsDiarios(metricas=metricas, acoes=acoes)


def ler_grao(linha: RegistroTraduzido) -> LinhaCadastro:
    """O anúncio e o dia da linha, que na consulta diária começa e termina na
    mesma data."""
    if linha["id_meta_anuncio"] is None:
        raise ErroInsights("linha de insights sem anúncio")
    inicio = linha["inicio_periodo"]
    if not isinstance(inicio, date) or inicio != linha["fim_periodo"]:
        raise ErroInsights("linha de insights que não é de um dia")
    return {"id_meta_anuncio": linha["id_meta_anuncio"], "data": inicio}


def tem_entrega_ou_acao(
    linha: RegistroTraduzido, acoes: Sequence[LinhaCadastro]
) -> bool:
    """Com results na consulta, a API devolve também anúncios e dias sem
    investimento, impressões nem nenhuma ação, que a consulta sem ele não
    devolve (R-24). Eles não viram linha: a ausência da linha já é a falta de
    entrega. O dia sem entrega com conversão atribuída continua (R-21)."""
    return bool(linha["investimento"] or linha["impressoes"] or acoes)


def combinar_acoes(linha: RegistroTraduzido) -> list[LinhaCadastro]:
    """Uma linha por tipo de ação, com a quantidade de actions e o valor de
    action_values (RF-12), e uma por resultado fora de actions, só com a
    quantidade. O tipo que vem só numa das listas fica com a outra medida
    nula."""
    por_tipo: dict[object, LinhaCadastro] = {}
    for lista, medida in MEDIDAS_ACAO:
        for item in ler_itens_acao(linha, lista):
            acao = por_tipo.setdefault(
                item["tipo_acao"],
                {"tipo_acao": item["tipo_acao"], "quantidade": None, "valor": None},
            )
            acao[medida] = item[medida]
    for acao in ler_resultados_fora_de_actions(linha):
        if acao["tipo_acao"] in por_tipo:
            raise ErroInsights("resultado fora de actions repetido em actions")
        por_tipo[acao["tipo_acao"]] = acao
    return list(por_tipo.values())


def ler_itens_acao(linha: RegistroTraduzido, lista: str) -> list[RegistroTraduzido]:
    """Os itens de uma lista de AdsActionStats, cada tipo uma vez só."""
    itens = linha[lista] or []
    tipos = [item["tipo_acao"] for item in itens]
    if None in tipos or len(set(tipos)) != len(tipos):
        raise ErroInsights(f"tipo de ação ausente ou repetido em {lista}")
    return itens


def ler_resultados_fora_de_actions(linha: RegistroTraduzido) -> list[LinhaCadastro]:
    """Os resultados fora de actions que vieram na linha, com o indicator
    como tipo (RESULTADOS_FORA_DE_ACTIONS). O que não veio fica sem linha,
    como as ações que a API omite."""
    valores = ler_valores_resultados(linha)
    acoes = []
    for resultado in RESULTADOS_FORA_DE_ACTIONS:
        if resultado.lista is None:
            quantidade = valores.get(resultado.indicador)
        else:
            itens = ler_itens_acao(linha, resultado.lista)
            quantidade = next(
                (
                    i["quantidade"]
                    for i in itens
                    if i["tipo_acao"] == resultado.tipo_item
                ),
                None,
            )
        if quantidade is not None:
            acoes.append(
                {
                    "tipo_acao": resultado.tipo_acao,
                    "quantidade": quantidade,
                    "valor": None,
                }
            )
    return acoes


def ler_valores_resultados(linha: RegistroTraduzido) -> dict[str, int | None]:
    """O valor de cada indicator lido de results, no formato verificado:
    uma vez só na linha, com no máximo um valor, o da janela padrão (R-24).
    Somar janelas ou repetições daria um número que a Meta não conta. Os
    demais indicators não são lidos nem conferidos, para que uma variação
    num resultado que vem por outro campo não derrube a carga."""
    valores: dict[str, int | None] = {}
    for item in linha["resultados"] or []:
        indicador, lista = item["indicador"], item["valores"] or []
        if indicador not in INDICADORES_LIDOS_DE_RESULTS:
            continue
        if indicador in valores or len(lista) > 1:
            raise ErroInsights("resultado fora do formato verificado")
        valores[indicador] = lista[0]["quantidade"] if lista else None
    return valores


def transformar_quebras_campanha(
    paginas: Sequence[Mapping[str, object]],
    tipo: TipoQuebra,
    tipos_acao_resultado: Mapping[str, str],
) -> QuebrasCampanha:
    """Uma linha por campanha, dia e categoria da resposta de uma quebra, com
    as métricas-base, e a ação do resultado principal da campanha, se veio
    na linha (RF-03), salvo nas linhas sem entrega nem ação
    (tem_entrega_ou_acao).

    tipos_acao_resultado leva o ID da Meta da campanha ao tipo de ação do
    resultado principal dela; a campanha sem resultado de ação fica fora e
    sem ações (ADR-0011). Um tipo ausente não vira zero: na região, a API
    omite as ações de fora da Meta (R-23). Uma categoria repetida na mesma
    campanha e dia é recusada: a carga substitui o conjunto completo, e uma
    das duas linhas se perderia.
    """
    quebras: list[LinhaCadastro] = []
    acoes: list[LinhaCadastro] = []
    for registro in ler_registros(paginas):
        linha = traduzir_registro(ObjetoApi.INSIGHTS, registro)
        grao = ler_grao_quebra(linha, tipo)
        acoes_linha = combinar_acoes(linha)
        if not tem_entrega_ou_acao(linha, acoes_linha):
            continue
        quebras.append(
            {
                **grao,
                "investimento": linha["investimento"],
                "impressoes": linha["impressoes"],
                "alcance": linha["alcance"],
            }
        )
        tipo_acao = tipos_acao_resultado.get(grao["id_meta_campanha"])
        acoes.extend(
            {**grao, **acao} for acao in acoes_linha if acao["tipo_acao"] == tipo_acao
        )
    repetidas = len(quebras) - len(
        {tuple(quebra[coluna] for coluna in GRAO_QUEBRA) for quebra in quebras}
    )
    if repetidas:
        raise ErroQuebra(f"{repetidas} linha(s) de categoria repetidas")
    return QuebrasCampanha(quebras=quebras, acoes=acoes)


def ler_grao_quebra(linha: RegistroTraduzido, tipo: TipoQuebra) -> LinhaCadastro:
    """A campanha, o dia e a categoria da linha. As dimensões da combinação
    consultada vêm todas, e as das outras combinações, nenhuma: uma dimensão
    a mais ou a menos mudaria o grão."""
    if linha["id_meta_campanha"] is None:
        raise ErroQuebra("linha de quebra sem campanha")
    inicio = linha["inicio_periodo"]
    if not isinstance(inicio, date) or inicio != linha["fim_periodo"]:
        raise ErroQuebra("linha de quebra que não é de um dia")
    colunas = COLUNAS_DIMENSAO[tipo]
    if any(linha[coluna] is None for coluna in colunas):
        raise ErroQuebra("linha de quebra sem categoria")
    outras = {c for por_tipo in COLUNAS_DIMENSAO.values() for c in por_tipo}
    if any(linha[coluna] is not None for coluna in outras - set(colunas)):
        raise ErroQuebra("linha de quebra fora da combinação consultada")
    categoria, *subcategoria = (linha[coluna] for coluna in colunas)
    return {
        "id_meta_campanha": linha["id_meta_campanha"],
        "data": inicio,
        "tipo_quebra": str(tipo),
        "categoria": categoria,
        "subcategoria": subcategoria[0] if subcategoria else None,
    }


def transformar_alcance_periodo(
    paginas: Sequence[Mapping[str, object]], nivel: NivelAlcance, tipo: TipoPeriodo
) -> list[LinhaCadastro]:
    """Uma linha por entidade e período da resposta de um nível, com o
    alcance e as impressões como a API os agregou (RF-04; ADR-0006).

    O período sem entrega não vem na resposta e não gera linha (R-20). Uma
    entidade e período repetidos são recusados: a carga substitui o conjunto
    completo, e uma das duas linhas se perderia.
    """
    linhas = [
        transformar_linha_alcance(registro, nivel, tipo)
        for registro in ler_registros(paginas)
    ]
    repetidos = len(linhas) - len(
        {
            (*(linha[coluna] for coluna in ENTIDADES_ALCANCE), linha["inicio_periodo"])
            for linha in linhas
        }
    )
    if repetidos:
        raise ErroAlcance(f"{repetidos} linha(s) de entidade e período repetidas")
    return linhas


def transformar_linha_alcance(
    registro: object, nivel: NivelAlcance, tipo: TipoPeriodo
) -> LinhaCadastro:
    """A linha traz o ID da entidade do nível consultado, e só ele, e um
    período que não termina antes de começar."""
    linha = traduzir_registro(ObjetoApi.INSIGHTS, registro)
    entidade = ENTIDADE_POR_NIVEL[nivel]
    ids = {coluna: linha[coluna] for coluna in ENTIDADES_ALCANCE}
    if any((ids[coluna] is None) == (coluna == entidade) for coluna in ids):
        raise ErroAlcance("linha de alcance fora do nível consultado")
    inicio, fim = linha["inicio_periodo"], linha["fim_periodo"]
    if not isinstance(inicio, date) or not isinstance(fim, date) or fim < inicio:
        raise ErroAlcance("linha de alcance sem período válido")
    return {
        **ids,
        "tipo_periodo": str(tipo),
        "inicio_periodo": inicio,
        "fim_periodo": fim,
        "alcance": linha["alcance"],
        "impressoes": linha["impressoes"],
    }
