"""Prova, contra o banco local e com a API simulada pelas fixtures de
cadastro, a extração e a carga das entidades e dos criativos de ponta a
ponta, pela execução por empresa (RF-01, RF-09, RF-17, RF-43). Exige o banco
local de pé.
"""

from collections.abc import Callable, Iterator
from uuid import UUID

import psycopg
import pytest
import responses
from responses.registries import OrderedRegistry

from etl.cadastro import TarefaCadastro
from etl.cliente_api_meta import ClienteApiMeta
from etl.execucao import StatusExecucao, executar_empresa
from tests.cadastro_exemplo import (
    ID_META_CONTA,
    Fixtures,
    ler_fixtures,
    simular_cadastro,
)
from tests.conftest import LIMPEZA_EMPRESA, EmpresaTeste, criar_empresa

pytestmark = pytest.mark.integracao

NOME_EMPRESA = "Empresa Exemplo Cadastro"
TOKEN = "EAAFicticio0000000000000000000000000000000000ZZ"
TIPO_EXECUCAO = "diaria"
ID_META_CAMPANHA = "995000000000000002"

# As colunas de negócio de cada tabela do cadastro: ficam de fora o
# execucao_id e as colunas *_em, que mudam a cada execução (ADR-0009 §5).
COLUNAS_NEGOCIO_CADASTRO = {
    "conta_anuncio": "id, id_meta, nome, fuso_horario, moeda, situacao",
    "campanha": "id, conta_anuncio_id, id_meta, nome, objetivo, status",
    "conjunto_anuncio": "id, campanha_id, id_meta, nome, meta_otimizacao, status",
    "janela_atribuicao_conjunto": "conjunto_anuncio_id, tipo_evento, janela_dias",
    "pagina": "id, id_meta, nome",
    "criativo": (
        "id, conta_anuncio_id, pagina_id, id_meta, titulo, texto, chamada_acao,"
        " id_publicacao_facebook, link_publicacao_facebook, id_midia_instagram,"
        " link_publicacao_instagram, caminho_miniatura"
    ),
    "anuncio": "id, conjunto_anuncio_id, criativo_id, id_meta, nome, status",
}

# Anúncio sem conjunto, campanha ou criativo válido, ou com criativo de outra
# conta que a da campanha (RF-01).
CONTAR_ANUNCIOS_ORFAOS = """
SELECT count(*)
FROM normalizado.anuncio AS anuncio
LEFT JOIN normalizado.conjunto_anuncio AS conjunto
  ON conjunto.empresa_id = anuncio.empresa_id AND conjunto.id = anuncio.conjunto_anuncio_id
LEFT JOIN normalizado.campanha AS campanha
  ON campanha.empresa_id = conjunto.empresa_id AND campanha.id = conjunto.campanha_id
LEFT JOIN normalizado.criativo AS criativo
  ON criativo.empresa_id = anuncio.empresa_id AND criativo.id = anuncio.criativo_id
WHERE anuncio.empresa_id = %s
  AND (conjunto.id IS NULL OR campanha.id IS NULL OR criativo.id IS NULL
       OR criativo.conta_anuncio_id <> campanha.conta_anuncio_id)
"""


@pytest.fixture
def empresa(conexao_operador: psycopg.Connection) -> Iterator[EmpresaTeste]:
    apagar_empresa_cadastro(conexao_operador)
    criada = criar_empresa(conexao_operador, NOME_EMPRESA, ID_META_CONTA, indice=1)
    try:
        yield criada
    finally:
        apagar_empresa_cadastro(conexao_operador)


def apagar_empresa_cadastro(conexao: psycopg.Connection) -> None:
    for (empresa_id,) in conexao.execute(
        "SELECT id FROM normalizado.empresa WHERE nome = %s", (NOME_EMPRESA,)
    ).fetchall():
        with conexao.transaction():
            for comando in LIMPEZA_EMPRESA:
                conexao.execute(comando, {"empresa_id": empresa_id})


def executar_cadastro(
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    fixtures: Fixtures | None,
) -> StatusExecucao:
    """Uma execução da tarefa de cadastro com a API simulada. Sem fixtures,
    nenhuma chamada à API é aceita."""
    with responses.RequestsMock(registry=OrderedRegistry) as api:
        if fixtures is not None:
            simular_cadastro(api, fixtures)
        tarefa = TarefaCadastro(
            conectar, ClienteApiMeta(TOKEN, dormir=lambda segundos: None)
        )
        return executar_empresa(conectar, empresa_id, TIPO_EXECUCAO, tarefa)


def ler_ids_meta(conexao: psycopg.Connection, tabela: str, empresa_id: UUID) -> set:
    linhas = conexao.execute(
        f"SELECT id_meta FROM normalizado.{tabela} WHERE empresa_id = %s",
        (empresa_id,),
    ).fetchall()
    return {id_meta for (id_meta,) in linhas}


def ids_meta_anuncios(fixtures: Fixtures) -> set[str]:
    return {
        anuncio["id"]
        for nome in ("cadastro_anuncios_pagina_1", "cadastro_anuncios_pagina_2")
        for anuncio in fixtures[nome]["corpo"]["data"]
    }


def ler_estado_cadastro(
    conexao: psycopg.Connection, empresa_id: UUID
) -> dict[str, list[tuple]]:
    return {
        tabela: conexao.execute(
            f"SELECT {colunas} FROM normalizado.{tabela}"
            f" WHERE empresa_id = %s ORDER BY {colunas}",
            (empresa_id,),
        ).fetchall()
        for tabela, colunas in COLUNAS_NEGOCIO_CADASTRO.items()
    }


def contar(conexao: psycopg.Connection, tabela: str, empresa_id: UUID) -> int:
    return conexao.execute(
        f"SELECT count(*) FROM normalizado.{tabela} WHERE empresa_id = %s",
        (empresa_id,),
    ).fetchone()[0]


def test_todo_anuncio_da_api_existe_com_campanha_conjunto_e_criativo_validos(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    fixtures = ler_fixtures()

    status = executar_cadastro(conectar_etl, empresa.empresa_id, fixtures)

    assert status is StatusExecucao.SUCESSO
    # Inclui o anúncio arquivado, que a aresta só devolve com o filtro (R-38).
    assert ler_ids_meta(conexao_operador, "anuncio", empresa.empresa_id) == (
        ids_meta_anuncios(fixtures)
    )
    orfaos = conexao_operador.execute(CONTAR_ANUNCIOS_ORFAOS, (empresa.empresa_id,))
    assert orfaos.fetchone()[0] == 0


def test_grava_cada_entidade_com_os_campos_do_rf_01(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    executar_cadastro(conectar_etl, empresa.empresa_id, ler_fixtures())

    contagens = {
        tabela: contar(conexao_operador, tabela, empresa.empresa_id)
        for tabela in (
            "campanha",
            "conjunto_anuncio",
            "janela_atribuicao_conjunto",
            "pagina",
            "criativo",
            "anuncio",
        )
    }
    assert contagens == {
        "campanha": 4,
        "conjunto_anuncio": 4,
        "janela_atribuicao_conjunto": 7,
        "pagina": 1,
        "criativo": 3,
        "anuncio": 4,
    }
    criativo = conexao_operador.execute(
        "SELECT pagina.id_meta, titulo, texto, chamada_acao, id_publicacao_facebook,"
        " id_midia_instagram, link_publicacao_instagram"
        " FROM normalizado.criativo"
        " JOIN normalizado.pagina ON pagina.empresa_id = criativo.empresa_id"
        "  AND pagina.id = criativo.pagina_id"
        " WHERE criativo.empresa_id = %s AND criativo.id_meta = '9950000000000016'",
        (empresa.empresa_id,),
    ).fetchone()
    assert criativo == (
        "995000000000012",
        "Título Exemplo 2",
        "Texto de exemplo do criativo 2.",
        "LEARN_MORE",
        "995000000000012_9950000000000018",
        "99500000000000017",
        "https://www.instagram.com/p/Exemplo0002Ab/",
    )
    conjunto = conexao_operador.execute(
        "SELECT meta_otimizacao, status FROM normalizado.conjunto_anuncio"
        " WHERE empresa_id = %s AND id_meta = '995000000000000009'",
        (empresa.empresa_id,),
    ).fetchone()
    assert conjunto == ("OFFSITE_CONVERSIONS", "ARCHIVED")


def test_conta_recebe_nome_fuso_e_moeda_da_api(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    executar_cadastro(conectar_etl, empresa.empresa_id, ler_fixtures())

    conta = conexao_operador.execute(
        "SELECT nome, fuso_horario, moeda, execucao_id IS NOT NULL"
        " FROM normalizado.conta_anuncio WHERE id = %s",
        (empresa.conta_id,),
    ).fetchone()
    assert conta == ("Conta Exemplo Cadastro", "America/Sao_Paulo", "BRL", True)


def test_campanha_renomeada_na_api_e_atualizada_sem_duplicar(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    def ler_campanha() -> list[tuple]:
        return conexao_operador.execute(
            "SELECT id, nome FROM normalizado.campanha"
            " WHERE empresa_id = %s AND id_meta = %s",
            (empresa.empresa_id, ID_META_CAMPANHA),
        ).fetchall()

    fixtures = ler_fixtures()
    executar_cadastro(conectar_etl, empresa.empresa_id, fixtures)
    [(campanha_id, _)] = ler_campanha()
    fixtures["cadastro_campanhas"]["corpo"]["data"][0]["name"] = "Campanha Renomeada"

    status = executar_cadastro(conectar_etl, empresa.empresa_id, fixtures)

    assert status is StatusExecucao.SUCESSO
    assert ler_campanha() == [(campanha_id, "Campanha Renomeada")]
    assert contar(conexao_operador, "campanha", empresa.empresa_id) == 4


def test_cadastro_repetido_produz_estado_identico(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    executar_cadastro(conectar_etl, empresa.empresa_id, ler_fixtures())
    antes = ler_estado_cadastro(conexao_operador, empresa.empresa_id)

    executar_cadastro(conectar_etl, empresa.empresa_id, ler_fixtures())

    assert ler_estado_cadastro(conexao_operador, empresa.empresa_id) == antes
    assert all(antes.values())


def test_janela_retirada_do_conjunto_sai_do_banco(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    fixtures = ler_fixtures()
    executar_cadastro(conectar_etl, empresa.empresa_id, fixtures)
    conjunto = fixtures["cadastro_conjuntos"]["corpo"]["data"][1]
    conjunto["attribution_spec"] = conjunto["attribution_spec"][:1]

    executar_cadastro(conectar_etl, empresa.empresa_id, fixtures)

    tipos = conexao_operador.execute(
        "SELECT janela.tipo_evento FROM normalizado.janela_atribuicao_conjunto AS janela"
        " JOIN normalizado.conjunto_anuncio AS conjunto"
        "  ON conjunto.empresa_id = janela.empresa_id"
        "  AND conjunto.id = janela.conjunto_anuncio_id"
        " WHERE conjunto.empresa_id = %s AND conjunto.id_meta = %s",
        (empresa.empresa_id, conjunto["id"]),
    ).fetchall()
    assert tipos == [("CLICK_THROUGH",)]


def test_cada_resposta_vai_para_o_bruto_com_a_execucao(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    executar_cadastro(conectar_etl, empresa.empresa_id, ler_fixtures())

    respostas = conexao_operador.execute(
        "SELECT resposta.endpoint, resposta.parametros ? 'effective_status'"
        " FROM bruto.resposta_api AS resposta"
        " JOIN normalizado.campanha AS campanha"
        "  ON campanha.empresa_id = resposta.empresa_id"
        "  AND campanha.execucao_id = resposta.execucao_id"
        " WHERE resposta.empresa_id = %s AND campanha.id_meta = %s"
        " ORDER BY resposta.id",
        (empresa.empresa_id, ID_META_CAMPANHA),
    ).fetchall()
    assert respostas == [
        ("objeto", False),
        ("anuncios", True),
        ("anuncios", True),
        ("conjuntos", True),
        ("campanhas", True),
    ]


def test_conta_inativa_nao_e_extraida(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    conexao_operador.execute(
        "UPDATE normalizado.conta_anuncio SET situacao = 'inativa' WHERE id = %s",
        (empresa.conta_id,),
    )

    status = executar_cadastro(conectar_etl, empresa.empresa_id, fixtures=None)

    assert status is StatusExecucao.SUCESSO
    assert contar(conexao_operador, "campanha", empresa.empresa_id) == 0


def test_objetivo_fora_do_catalogo_gera_aviso_sem_falhar_a_carga(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # RF-15: as outras três campanhas têm objetivo do catálogo e não geram
    # aviso.
    fixtures = ler_fixtures()
    campanha = fixtures["cadastro_campanhas"]["corpo"]["data"][0]
    campanha["objective"] = "OUTCOME_OBJETIVO_FUTURO"

    status = executar_cadastro(conectar_etl, empresa.empresa_id, fixtures)

    assert status is StatusExecucao.SUCESSO
    avisos = conexao_operador.execute(
        "SELECT aviso.tipo, campanha.id_meta, contagem.linhas"
        " FROM normalizado.aviso_execucao AS aviso"
        " JOIN normalizado.campanha AS campanha"
        "  ON campanha.empresa_id = aviso.empresa_id AND campanha.id = aviso.campanha_id"
        " JOIN normalizado.contagem_linhas_execucao AS contagem"
        "  ON contagem.empresa_id = aviso.empresa_id"
        "  AND contagem.execucao_id = aviso.execucao_id"
        "  AND contagem.tabela = 'aviso_execucao'"
        " WHERE aviso.empresa_id = %s",
        (empresa.empresa_id,),
    ).fetchall()
    assert avisos == [("objetivo_nao_classificado", campanha["id"], 1)]
