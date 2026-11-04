"""Transformação pura do cadastro de uma conta nas linhas de normalizado: a
conta, as campanhas, os conjuntos com as janelas de atribuição, as Páginas,
os criativos e os anúncios (RF-01, RF-11, RF-13). Sem rede, banco nem relógio
(CLAUDE.md §8).

As linhas apontam para o pai pelo ID da Meta (id_meta_<entidade>), porque a
chave interna só existe depois do upsert do pai, na carga. As mensagens de
erro trazem só contagens, nunca IDs nem nomes, porque podem chegar aos logs
públicos (RNF-17).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

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


class ErroCadastro(ValueError):
    """Cadastro da API incoerente, que a carga não pode gravar."""


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
