"""Transformação pura das respostas da API nas linhas de normalizado: o
cadastro de uma conta, com a conta, as campanhas, os conjuntos com as janelas
de atribuição, as Páginas, os criativos e os anúncios (RF-01), e os insights
diários por anúncio, com as métricas e a tabela longa das ações (RF-02,
RF-12). Os nomes e os tipos vêm do mapa de campos (RF-11, RF-13). Sem rede,
banco nem relógio (CLAUDE.md §8).

As linhas apontam para o pai pelo ID da Meta (id_meta_<entidade>), porque a
chave interna só existe depois do upsert do pai, na carga. As mensagens de
erro trazem só contagens, nunca IDs nem nomes, porque podem chegar aos logs
públicos (RNF-17).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

from etl.mapa_campos import ObjetoApi, RegistroTraduzido, traduzir_registro
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


class ErroCadastro(ValueError):
    """Cadastro da API incoerente, que a carga não pode gravar."""


class ErroInsights(ValueError):
    """Insights da API fora do grão anúncio × dia, que a carga não pode
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
    """Uma métrica por linha de insights e uma ação por tipo da linha.

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
        metricas.append(
            {
                **grao,
                "investimento": linha["investimento"],
                "impressoes": linha["impressoes"],
                "alcance": linha["alcance"],
            }
        )
        acoes.extend({**grao, **acao} for acao in combinar_acoes(linha))
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


def combinar_acoes(linha: RegistroTraduzido) -> list[LinhaCadastro]:
    """Uma linha por tipo de ação, com a quantidade de actions e o valor de
    action_values (RF-12). O tipo que vem só numa das listas fica com a
    outra medida nula."""
    por_tipo: dict[object, LinhaCadastro] = {}
    for lista, medida in MEDIDAS_ACAO:
        itens = linha[lista] or []
        tipos = [item["tipo_acao"] for item in itens]
        if None in tipos or len(set(tipos)) != len(tipos):
            raise ErroInsights(f"tipo de ação ausente ou repetido em {lista}")
        for item in itens:
            acao = por_tipo.setdefault(
                item["tipo_acao"],
                {"tipo_acao": item["tipo_acao"], "quantidade": None, "valor": None},
            )
            acao[medida] = item[medida]
    return list(por_tipo.values())
