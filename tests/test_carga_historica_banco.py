"""Prova, contra o banco local e com a API simulada pelas fixtures, a carga
histórica de ponta a ponta: a conta nova detectada pela falta de fatias
(RF-22), uma fatia por mês até 37 meses (RF-07; R-19), a retomada da fatia que
falhou com o estado final igual ao de uma carga sem interrupção, a fatia
idempotente, o prazo da execução (RNF-07) e o lock da empresa (RF-19). Exige o
banco local de pé.
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import partial
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
import pytest
import responses
from responses.registries import OrderedRegistry

from etl import carga_historica
from etl.cadastro import TarefaCadastro
from etl.carga import calcular_chave_lock
from etl.carga_historica import CargaHistorica, executar_carga_historica
from etl.cliente_api_meta import ClienteApiMeta, ErroPermissao
from etl.configuracao import Ambiente
from etl.execucao import (
    CODIGO_SAIDA_FALHA,
    CODIGO_SAIDA_SUCESSO,
    TIPO_COM_RETENCAO,
    StatusExecucao,
    executar_empresa,
)
from etl.extracao import agora_utc
from tests import cadastro_exemplo
from tests.cadastro_exemplo import CONTA, ID_META_CONTA
from tests.carga_historica_exemplo import (
    EXECUCAO,
    MARCO,
    NOVEMBRO,
    OUTUBRO,
    RespostasFatia,
    calcular_intervalo,
    calcular_limite,
    ler_fixture,
    listar_meses,
    montar_respostas,
    simular_historico,
    simular_insights_fatia,
)
from tests.conftest import LIMPEZA_EMPRESA, URL_BANCO_LOCAL, EmpresaTeste, criar_empresa

pytestmark = pytest.mark.integracao

NOME_EMPRESA = "Empresa Exemplo Histórica"
NOME_OUTRA_EMPRESA = "Empresa Exemplo Histórica B"
ID_META_OUTRA_CONTA = "996000000000002"
TOKEN = "EAAFicticio0000000000000000000000000000000000ZZ"
# A conexão do ponto de entrada não passa pelo SET ROLE de conectar_etl.
URL_BANCO_ETL = f"{URL_BANCO_LOCAL}?options=-crole%3Detl_carga"
FUSO_BRASILIA = "America/Sao_Paulo"
ID_META_CAMPANHA_FORA_DA_CONTA = "995000000000000099"
# 38 meses, de outubro de 2023 a novembro de 2026.
MESES = listar_meses()
FATIAS_ATE_SETEMBRO = MESES.index(OUTUBRO)
PRAZO = 1000.0
SEM_PRAZO = float("inf")
ERRO_PERMISSAO = {
    "status": 403,
    "cabecalhos": {},
    "corpo": {"error": {"code": 10, "type": "OAuthException"}},
}

LER_FATIAS = """
SELECT mes_referencia, status FROM normalizado.fatia_historica
WHERE empresa_id = %s ORDER BY mes_referencia
"""

LER_FATIAS_CONTA = """
SELECT mes_referencia, status FROM normalizado.fatia_historica
WHERE conta_anuncio_id = %s ORDER BY mes_referencia
"""

LER_ERRO_EXECUCAO = """
SELECT status, erro FROM normalizado.execucao_carga
WHERE empresa_id = %s AND tipo = 'historica'
"""

LER_EXECUCOES = """
SELECT tipo, status FROM normalizado.execucao_carga
WHERE empresa_id = %s ORDER BY iniciado_em
"""

LER_CONTAGENS_HISTORICA = """
SELECT contagem.tabela, contagem.linhas
FROM normalizado.contagem_linhas_execucao AS contagem
JOIN normalizado.execucao_carga AS execucao
  ON execucao.empresa_id = contagem.empresa_id AND execucao.id = contagem.execucao_id
WHERE contagem.empresa_id = %s AND execucao.tipo = 'historica'
"""

# O estado pelas chaves naturais: as chaves internas mudam quando a empresa é
# recriada, e a comparação é entre duas cargas da mesma conta.
LER_ESTADO_NATURAL: Mapping[str, str] = {
    "metricas": """
        SELECT anuncio.id_meta, metrica.data, metrica.investimento,
               metrica.impressoes, metrica.alcance
        FROM normalizado.metrica_diaria_anuncio AS metrica
        JOIN normalizado.anuncio AS anuncio
          ON anuncio.empresa_id = metrica.empresa_id AND anuncio.id = metrica.anuncio_id
        WHERE metrica.empresa_id = %s
    """,
    "acoes": """
        SELECT anuncio.id_meta, acao.data, acao.tipo_acao, acao.quantidade, acao.valor
        FROM normalizado.acao_diaria_anuncio AS acao
        JOIN normalizado.anuncio AS anuncio
          ON anuncio.empresa_id = acao.empresa_id AND anuncio.id = acao.anuncio_id
        WHERE acao.empresa_id = %s
    """,
    "quebras": """
        SELECT campanha.id_meta, quebra.data, quebra.tipo_quebra, quebra.categoria,
               quebra.subcategoria, quebra.investimento, quebra.impressoes,
               quebra.alcance, acao.tipo_acao, acao.quantidade, acao.valor
        FROM normalizado.quebra_diaria_campanha AS quebra
        JOIN normalizado.campanha AS campanha
          ON campanha.empresa_id = quebra.empresa_id AND campanha.id = quebra.campanha_id
        LEFT JOIN normalizado.acao_quebra_diaria_campanha AS acao
          ON acao.empresa_id = quebra.empresa_id
         AND acao.quebra_diaria_campanha_id = quebra.id
        WHERE quebra.empresa_id = %s
    """,
    "alcance": """
        SELECT coalesce(conta.id_meta, campanha.id_meta, anuncio.id_meta),
               alcance.tipo_periodo, alcance.inicio_periodo, alcance.fim_periodo,
               alcance.alcance, alcance.impressoes
        FROM normalizado.alcance_periodo AS alcance
        LEFT JOIN normalizado.conta_anuncio AS conta ON conta.id = alcance.conta_anuncio_id
        LEFT JOIN normalizado.campanha AS campanha ON campanha.id = alcance.campanha_id
        LEFT JOIN normalizado.anuncio AS anuncio ON anuncio.id = alcance.anuncio_id
        WHERE alcance.empresa_id = %s
    """,
    "anuncios": """
        SELECT id_meta, nome, status FROM normalizado.anuncio WHERE empresa_id = %s
    """,
    "campanhas": """
        SELECT id_meta, nome, objetivo, status FROM normalizado.campanha
        WHERE empresa_id = %s
    """,
}

type Simulacao = Callable[[responses.RequestsMock], None]


def apagar_empresas_historica(conexao: psycopg.Connection) -> None:
    for (empresa_id,) in conexao.execute(
        "SELECT id FROM normalizado.empresa WHERE nome = ANY(%s)",
        ([NOME_EMPRESA, NOME_OUTRA_EMPRESA],),
    ).fetchall():
        with conexao.transaction():
            for comando in LIMPEZA_EMPRESA:
                conexao.execute(comando, {"empresa_id": empresa_id})


def criar_empresa_com_cadastro(
    conectar: Callable[[], psycopg.Connection], conexao: psycopg.Connection
) -> EmpresaTeste:
    """A empresa com a conta das fixtures de cadastro já carregadas, como a
    execução diária as deixa: com fuso, moeda e as entidades não excluídas."""
    criada = criar_empresa(conexao, NOME_EMPRESA, ID_META_CONTA, indice=1)
    with responses.RequestsMock(registry=OrderedRegistry) as api:
        cadastro_exemplo.simular_cadastro(api, cadastro_exemplo.ler_fixtures())
        cliente = ClienteApiMeta(TOKEN, dormir=lambda segundos: None)
        tarefa = TarefaCadastro(conectar, cliente, relogio=lambda: EXECUCAO)
        status = executar_empresa(
            conectar, criada.empresa_id, TIPO_COM_RETENCAO, tarefa
        )
    assert status is StatusExecucao.SUCESSO
    return criada


@pytest.fixture
def empresa(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
) -> Iterator[EmpresaTeste]:
    apagar_empresas_historica(conexao_operador)
    try:
        yield criar_empresa_com_cadastro(conectar_etl, conexao_operador)
    finally:
        apagar_empresas_historica(conexao_operador)


def criar_outra_empresa(conexao: psycopg.Connection) -> EmpresaTeste:
    """Uma empresa cuja conta já teve a primeira extração, sem entidades."""
    outra = criar_empresa(conexao, NOME_OUTRA_EMPRESA, ID_META_OUTRA_CONTA, indice=2)
    definir_fuso(conexao, outra.conta_id)
    return outra


def definir_fuso(conexao: psycopg.Connection, conta_id: UUID) -> None:
    conexao.execute(
        "UPDATE normalizado.conta_anuncio SET fuso_horario = %s, moeda = 'BRL'"
        " WHERE id = %s",
        (FUSO_BRASILIA, conta_id),
    )


def executar_historica(
    conectar: Callable[[], psycopg.Connection],
    empresas: Sequence[UUID],
    simular: Simulacao,
    *,
    cronometro: Callable[[responses.RequestsMock], Callable[[], float]] | None = None,
    espera_maxima_segundos: float = 0,
    instante: datetime = EXECUCAO,
) -> int:
    """Uma execução com a API simulada e, salvo outro instante, o relógio da
    execução de referência. Uma chamada não simulada, ou fora da ordem, falha
    a empresa."""
    with responses.RequestsMock(registry=OrderedRegistry) as api:
        simular(api)
        carga = CargaHistorica(
            conectar,
            ClienteApiMeta(TOKEN, dormir=lambda segundos: None),
            prazo=PRAZO if cronometro else SEM_PRAZO,
            relogio=lambda: instante,
            cronometro=cronometro(api) if cronometro else lambda: 0.0,
            espera_maxima_segundos=espera_maxima_segundos,
            intervalo_segundos=0,
        )
        return carga.executar(empresas)


def simular_tudo(api: responses.RequestsMock) -> None:
    simular_historico(api, MESES, montar_respostas())


def ler_fatias(conexao: psycopg.Connection, empresa_id: UUID) -> list[tuple]:
    return conexao.execute(LER_FATIAS, (empresa_id,)).fetchall()


def ler_execucoes(conexao: psycopg.Connection, empresa_id: UUID) -> list[tuple]:
    return conexao.execute(LER_EXECUCOES, (empresa_id,)).fetchall()


def ler_estado_natural(
    conexao: psycopg.Connection, empresa_id: UUID
) -> dict[str, set[tuple]]:
    return {
        nome: set(conexao.execute(consulta, (empresa_id,)).fetchall())
        for nome, consulta in LER_ESTADO_NATURAL.items()
    }


def montar_metricas_api(paginas: Sequence[dict]) -> set[tuple]:
    """As métricas como a resposta da API as traz, sem passar pela ETL."""
    return {
        (
            linha["ad_id"],
            date.fromisoformat(linha["date_start"]),
            Decimal(linha["spend"]),
            int(linha["impressions"]),
            int(linha["reach"]),
        )
        for pagina in paginas
        for linha in pagina["corpo"]["data"]
    }


def montar_alcance_fora_da_conta() -> dict:
    """O alcance de outubro de uma campanha que não é da conta: a carga da
    fatia falha no alcance, a última etapa, com os insights e as quebras já
    gravados na transação."""
    fixture = ler_fixture("alcance_campanha_marco")
    linha = fixture["corpo"]["data"][0]
    linha |= {
        "campaign_id": ID_META_CAMPANHA_FORA_DA_CONTA,
        "date_start": "2026-10-01",
        "date_stop": "2026-10-31",
    }
    fixture["corpo"]["data"] = [linha]
    return fixture


def test_conta_nova_ganha_uma_fatia_por_mes_e_carrega_o_historico(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # O critério do RF-22: a conta com a primeira extração feita e sem
    # fatias é nova, e a execução seguinte planeja e carrega o histórico
    # dela, do limite de 37 meses até ontem, sem mudança de código (RF-07).
    assert ler_fatias(conexao_operador, empresa.empresa_id) == []

    codigo = executar_historica(conectar_etl, [empresa.empresa_id], simular_tudo)

    assert codigo == CODIGO_SAIDA_SUCESSO
    assert len(MESES) == 38
    assert ler_fatias(conexao_operador, empresa.empresa_id) == [
        (mes, "concluida") for mes in MESES
    ]
    assert ler_execucoes(conexao_operador, empresa.empresa_id) == [
        ("diaria", "sucesso"),
        ("historica", "sucesso"),
    ]
    respostas = montar_respostas()
    estado = ler_estado_natural(conexao_operador, empresa.empresa_id)
    assert estado["metricas"] == montar_metricas_api(
        [*respostas[MARCO].insights, *respostas[OUTUBRO].insights]
    )
    # O alcance de março de cada campanha é o da API para 01/03 a 31/03,
    # sem quebra diária (RF-04).
    assert {linha for linha in estado["alcance"] if linha[1] == "mes"} == {
        (
            linha["campaign_id"],
            "mes",
            MARCO,
            date(2026, 3, 31),
            int(linha["reach"]),
            int(linha["impressions"]),
        )
        for linha in ler_fixture("alcance_campanha_marco")["corpo"]["data"]
    }


def test_execucao_registra_as_linhas_da_carga_historica(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # As linhas de todas as fatias entram no registro de fim (RF-20), e a
    # carga grava em bruto as respostas de cada consulta (RF-09).
    executar_historica(conectar_etl, [empresa.empresa_id], simular_tudo)

    contagens = dict(
        conexao_operador.execute(
            LER_CONTAGENS_HISTORICA, (empresa.empresa_id,)
        ).fetchall()
    )
    respostas = montar_respostas()
    assert contagens["metrica_diaria_anuncio"] == len(
        montar_metricas_api([*respostas[MARCO].insights, *respostas[OUTUBRO].insights])
    )
    assert (
        contagens["resposta_api"]
        == conexao_operador.execute(
            "SELECT count(*) FROM bruto.resposta_api AS resposta"
            " JOIN normalizado.execucao_carga AS execucao"
            "   ON execucao.empresa_id = resposta.empresa_id"
            "  AND execucao.id = resposta.execucao_id"
            " WHERE resposta.empresa_id = %s AND execucao.tipo = 'historica'",
            (empresa.empresa_id,),
        ).fetchone()[0]
    )
    assert contagens["resposta_api"] > len(MESES)
    # O alcance da fatia vai além dela, como o ano da fatia de janeiro, até
    # ontem: a retenção não pode apagar a resposta antes do último dia que ela
    # cobre (RF-21; ADR-0009 §2).
    assert (
        conexao_operador.execute(
            "SELECT count(*) FROM bruto.resposta_api AS resposta"
            " JOIN normalizado.execucao_carga AS execucao"
            "   ON execucao.empresa_id = resposta.empresa_id"
            "  AND execucao.id = resposta.execucao_id"
            " WHERE resposta.empresa_id = %s AND execucao.tipo = 'historica'"
            "   AND resposta.parametros ? 'time_range'"
            "   AND resposta.data_referencia"
            "       < ((resposta.parametros->>'time_range')::jsonb->>'until')::date",
            (empresa.empresa_id,),
        ).fetchone()[0]
        == 0
    )


def test_retomada_continua_da_fatia_que_falhou_e_chega_ao_estado_sem_interrupcao(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # O critério do RF-07. Primeiro, a carga sem interrupção, como referência.
    executar_historica(conectar_etl, [empresa.empresa_id], simular_tudo)
    sem_interrupcao = ler_estado_natural(conexao_operador, empresa.empresa_id)
    assert sem_interrupcao["metricas"]

    # A mesma conta, do zero: a fatia de outubro, do meio da carga, falha
    # depois de gravar os insights e as quebras na transação.
    apagar_empresas_historica(conexao_operador)
    recriada = criar_empresa_com_cadastro(conectar_etl, conexao_operador)
    com_falha = montar_respostas()
    com_falha[OUTUBRO] = RespostasFatia(
        insights=com_falha[OUTUBRO].insights,
        quebras=com_falha[OUTUBRO].quebras,
        alcance={"alcance_campanha_mes": montar_alcance_fora_da_conta()},
        entidades_por_id=True,
    )
    codigo = executar_historica(
        conectar_etl,
        [recriada.empresa_id],
        lambda api: simular_historico(api, MESES[: FATIAS_ATE_SETEMBRO + 1], com_falha),
    )

    assert codigo == CODIGO_SAIDA_FALHA
    assert ler_fatias(conexao_operador, recriada.empresa_id) == [
        *((mes, "concluida") for mes in MESES[:FATIAS_ATE_SETEMBRO]),
        (OUTUBRO, "falha"),
        (NOVEMBRO, "pendente"),
    ]
    interrompida = ler_estado_natural(conexao_operador, recriada.empresa_id)
    # Nada de outubro fica, e março, concluída antes, fica (RF-18).
    assert {linha[1].month for linha in interrompida["metricas"]} == {3}
    assert ler_execucoes(conexao_operador, recriada.empresa_id)[-1] == (
        "historica",
        "falha",
    )
    contagens = dict(
        conexao_operador.execute(
            LER_CONTAGENS_HISTORICA, (recriada.empresa_id,)
        ).fetchall()
    )
    assert contagens["metrica_diaria_anuncio"] == len(
        montar_metricas_api(com_falha[MARCO].insights)
    )

    # A retomada lê só da fatia que falhou em diante: a simulação não
    # responde às fatias concluídas.
    codigo = executar_historica(
        conectar_etl,
        [recriada.empresa_id],
        lambda api: simular_historico(
            api, MESES[FATIAS_ATE_SETEMBRO:], montar_respostas()
        ),
    )

    assert codigo == CODIGO_SAIDA_SUCESSO
    assert ler_fatias(conexao_operador, recriada.empresa_id) == [
        (mes, "concluida") for mes in MESES
    ]
    assert ler_estado_natural(conexao_operador, recriada.empresa_id) == sem_interrupcao


def test_fatia_carregada_de_novo_produz_o_mesmo_estado(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # A fatia é idempotente: refeita com a mesma resposta, substitui o próprio
    # mês e deixa o banco como estava (RF-17).
    executar_historica(conectar_etl, [empresa.empresa_id], simular_tudo)
    antes = ler_estado_natural(conexao_operador, empresa.empresa_id)
    conexao_operador.execute(
        "UPDATE normalizado.fatia_historica SET status = 'pendente'"
        " WHERE empresa_id = %s AND mes_referencia = %s",
        (empresa.empresa_id, MARCO),
    )

    codigo = executar_historica(
        conectar_etl,
        [empresa.empresa_id],
        lambda api: simular_historico(api, [MARCO], montar_respostas()),
    )

    assert codigo == CODIGO_SAIDA_SUCESSO
    assert ler_estado_natural(conexao_operador, empresa.empresa_id) == antes
    assert ler_fatias(conexao_operador, empresa.empresa_id) == [
        (mes, "concluida") for mes in MESES
    ]


def test_conta_com_historico_concluido_nao_gera_execucao(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # Com todas as fatias concluídas, a execução seguinte não chama a API
    # nem registra execução: a rotina diária cuida dos dias novos.
    executar_historica(conectar_etl, [empresa.empresa_id], simular_tudo)
    execucoes = ler_execucoes(conexao_operador, empresa.empresa_id)

    codigo = executar_historica(conectar_etl, [empresa.empresa_id], lambda api: None)

    assert codigo == CODIGO_SAIDA_SUCESSO
    assert ler_execucoes(conexao_operador, empresa.empresa_id) == execucoes


def test_conta_sem_fuso_espera_a_primeira_extracao(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # Sem o fuso, que vem da primeira extração da rotina diária, não há como
    # saber o hoje da conta nem o limite de 37 meses (R-19).
    outra = criar_empresa(
        conexao_operador, NOME_OUTRA_EMPRESA, ID_META_OUTRA_CONTA, indice=2
    )

    codigo = executar_historica(conectar_etl, [outra.empresa_id], lambda api: None)

    assert codigo == CODIGO_SAIDA_SUCESSO
    assert ler_fatias(conexao_operador, outra.empresa_id) == []
    assert ler_execucoes(conexao_operador, outra.empresa_id) == []


def test_conta_inativa_fica_fora_da_carga_historica(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    conexao_operador.execute(
        "UPDATE normalizado.conta_anuncio SET situacao = 'inativa' WHERE id = %s",
        (empresa.conta_id,),
    )

    codigo = executar_historica(conectar_etl, [empresa.empresa_id], lambda api: None)

    assert codigo == CODIGO_SAIDA_SUCESSO
    assert ler_fatias(conexao_operador, empresa.empresa_id) == []


def test_prazo_esgotado_deixa_as_fatias_seguintes_para_a_proxima_execucao(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # O prazo vence durante a terceira fatia da primeira conta: ela termina,
    # e a quarta não começa, para a execução caber no RNF-07. A segunda conta,
    # nova, já tem as fatias planejadas: a carga dela começou nesta execução
    # (RF-22). A execução é um sucesso, e a seguinte continua da quarta.
    with conexao_operador.transaction():
        segunda_conta = conexao_operador.execute(
            "INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)"
            " VALUES (%s, %s) RETURNING id",
            (empresa.empresa_id, ID_META_OUTRA_CONTA),
        ).fetchone()[0]
        definir_fuso(conexao_operador, segunda_conta)

    def simular(api: responses.RequestsMock) -> None:
        simular_historico(api, MESES[:3], montar_respostas())

    def cronometro(api: responses.RequestsMock) -> Callable[[], float]:
        chamadas_tres_fatias = len(api.registered())
        return lambda: PRAZO if len(api.calls) >= chamadas_tres_fatias else 0.0

    codigo = executar_historica(
        conectar_etl, [empresa.empresa_id], simular, cronometro=cronometro
    )

    assert codigo == CODIGO_SAIDA_SUCESSO
    assert conexao_operador.execute(
        LER_FATIAS_CONTA, (empresa.conta_id,)
    ).fetchall() == [
        *((mes, "concluida") for mes in MESES[:3]),
        *((mes, "pendente") for mes in MESES[3:]),
    ]
    assert conexao_operador.execute(LER_FATIAS_CONTA, (segunda_conta,)).fetchall() == [
        (mes, "pendente") for mes in MESES
    ]
    assert ler_execucoes(conexao_operador, empresa.empresa_id)[-1] == (
        "historica",
        "sucesso",
    )

    def simular_restante(api: responses.RequestsMock) -> None:
        simular_historico(api, MESES[3:], montar_respostas())
        simular_historico(api, MESES, {}, conta=f"act_{ID_META_OUTRA_CONTA}")

    codigo = executar_historica(conectar_etl, [empresa.empresa_id], simular_restante)

    assert codigo == CODIGO_SAIDA_SUCESSO
    assert ler_fatias(conexao_operador, empresa.empresa_id) == sorted(
        (mes, "concluida") for mes in [*MESES, *MESES]
    )


def test_lock_ocupado_deixa_a_fatia_pendente_e_a_execucao_ignorada(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # Outra execução da empresa segura o lock: a primeira fatia, já extraída,
    # não é carregada, e a execução termina como ignorada (RF-19).
    with (
        psycopg.connect(URL_BANCO_LOCAL, autocommit=True) as outra_execucao,
        outra_execucao.transaction(),
    ):
        outra_execucao.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (calcular_chave_lock(empresa.empresa_id),),
        )
        codigo = executar_historica(
            conectar_etl,
            [empresa.empresa_id],
            lambda api: simular_historico(api, MESES[:1], {}),
        )

    assert codigo == CODIGO_SAIDA_SUCESSO
    assert ler_fatias(conexao_operador, empresa.empresa_id) == [
        (mes, "pendente") for mes in MESES
    ]
    assert ler_execucoes(conexao_operador, empresa.empresa_id)[-1] == (
        "historica",
        "ignorada",
    )


def test_falha_de_uma_empresa_nao_interrompe_a_outra(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # A primeira fatia da empresa A falha na API; a empresa B carrega o
    # histórico inteiro, e o job sai com falha (RF-50).
    outra = criar_outra_empresa(conexao_operador)

    def simular(api: responses.RequestsMock) -> None:
        simular_insights_fatia(
            api, CONTA, *calcular_intervalo(MESES[0]), [ERRO_PERMISSAO]
        )
        simular_historico(api, MESES, {}, conta=f"act_{ID_META_OUTRA_CONTA}")

    codigo = executar_historica(
        conectar_etl, [empresa.empresa_id, outra.empresa_id], simular
    )

    assert codigo == CODIGO_SAIDA_FALHA
    assert ler_fatias(conexao_operador, empresa.empresa_id) == [
        (MESES[0], "falha"),
        *((mes, "pendente") for mes in MESES[1:]),
    ]
    assert ler_execucoes(conexao_operador, empresa.empresa_id)[-1] == (
        "historica",
        "falha",
    )
    assert ler_fatias(conexao_operador, outra.empresa_id) == [
        (mes, "concluida") for mes in MESES
    ]
    assert ler_execucoes(conexao_operador, outra.empresa_id) == [
        ("historica", "sucesso")
    ]


def test_falha_numa_conta_nao_segura_a_outra_conta_da_empresa(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # A segunda conta da empresa é nova: as fatias dela são planejadas no
    # início da execução, e ela carrega o histórico mesmo com a primeira
    # conta falhando na primeira fatia, como falharia a cada execução um
    # erro que se repete. A execução fica como falha (RF-22; RF-50).
    with conexao_operador.transaction():
        segunda_conta = conexao_operador.execute(
            "INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)"
            " VALUES (%s, %s) RETURNING id",
            (empresa.empresa_id, ID_META_OUTRA_CONTA),
        ).fetchone()[0]
        definir_fuso(conexao_operador, segunda_conta)

    def simular(api: responses.RequestsMock) -> None:
        simular_insights_fatia(
            api, CONTA, *calcular_intervalo(MESES[0]), [ERRO_PERMISSAO]
        )
        simular_historico(api, MESES, {}, conta=f"act_{ID_META_OUTRA_CONTA}")

    codigo = executar_historica(conectar_etl, [empresa.empresa_id], simular)

    assert codigo == CODIGO_SAIDA_FALHA
    assert conexao_operador.execute(
        LER_FATIAS_CONTA, (empresa.conta_id,)
    ).fetchall() == [(MESES[0], "falha"), *((mes, "pendente") for mes in MESES[1:])]
    assert conexao_operador.execute(LER_FATIAS_CONTA, (segunda_conta,)).fetchall() == [
        (mes, "concluida") for mes in MESES
    ]
    status, erro = conexao_operador.execute(
        LER_ERRO_EXECUCAO, (empresa.empresa_id,)
    ).fetchone()
    assert status == "falha"
    assert erro.startswith(ErroPermissao.__name__)


def test_falha_ao_ler_as_contas_de_uma_empresa_nao_interrompe_a_outra(
    monkeypatch: pytest.MonkeyPatch,
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # Uma queda do banco na leitura das contas da empresa A é a falha dela,
    # e a empresa B carrega (CLAUDE.md §6).
    outra = criar_outra_empresa(conexao_operador)
    ler_contas = carga_historica.listar_contas_historico

    def falhar_na_empresa_a(conexao: psycopg.Connection, empresa_id: UUID) -> list:
        if empresa_id == empresa.empresa_id:
            raise psycopg.OperationalError("conexão perdida")
        return ler_contas(conexao, empresa_id)

    monkeypatch.setattr(carga_historica, "listar_contas_historico", falhar_na_empresa_a)

    codigo = executar_historica(
        conectar_etl,
        [empresa.empresa_id, outra.empresa_id],
        lambda api: simular_historico(
            api, MESES, {}, conta=f"act_{ID_META_OUTRA_CONTA}"
        ),
    )

    assert codigo == CODIGO_SAIDA_FALHA
    assert ler_fatias(conexao_operador, outra.empresa_id) == [
        (mes, "concluida") for mes in MESES
    ]


def test_interrupcao_fecha_o_registro_da_execucao_e_deixa_a_fatia_pendente(
    monkeypatch: pytest.MonkeyPatch,
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # O Actions cancela o job que passa do limite de tempo com SIGINT: a
    # execução fica registrada como falha, e não em_andamento (RF-20), e a
    # interrupção segue para o ponto de entrada.
    def interromper(*argumentos: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(CargaHistorica, "extrair_fatia", interromper)

    with pytest.raises(KeyboardInterrupt):
        executar_historica(conectar_etl, [empresa.empresa_id], lambda api: None)

    status, erro = conexao_operador.execute(
        LER_ERRO_EXECUCAO, (empresa.empresa_id,)
    ).fetchone()
    assert (status, erro) == ("falha", "KeyboardInterrupt")
    assert ler_fatias(conexao_operador, empresa.empresa_id) == [
        (mes, "pendente") for mes in MESES
    ]


def test_retomada_depois_que_o_limite_andou_corta_a_primeira_fatia_no_limite_novo(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # As fatias são planejadas em 06/11/2026, e a outra execução da empresa
    # segura o lock. A retomada vem em 07/01/2027, com o limite em
    # 08/12/2023: outubro e novembro de 2023 saíram inteiros do limite e são
    # concluídos sem chamada à API, e dezembro começa no limite novo. As
    # fatias não planejadas, de dezembro de 2026 e janeiro de 2027, ficam com
    # a rotina diária.
    with (
        psycopg.connect(URL_BANCO_LOCAL, autocommit=True) as outra_execucao,
        outra_execucao.transaction(),
    ):
        outra_execucao.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (calcular_chave_lock(empresa.empresa_id),),
        )
        executar_historica(
            conectar_etl,
            [empresa.empresa_id],
            lambda api: simular_historico(api, MESES[:1], {}),
        )
    retomada = EXECUCAO + timedelta(days=62)
    hoje = date(2027, 1, 7)
    assert calcular_limite(hoje) == date(2023, 12, 8)

    codigo = executar_historica(
        conectar_etl,
        [empresa.empresa_id],
        lambda api: simular_historico(api, MESES[2:], montar_respostas(), hoje=hoje),
        instante=retomada,
    )

    assert codigo == CODIGO_SAIDA_SUCESSO
    assert ler_fatias(conexao_operador, empresa.empresa_id) == [
        (mes, "concluida") for mes in MESES
    ]


def test_ponto_de_entrada_carrega_o_historico_ate_ontem_no_fuso_da_conta(
    monkeypatch: pytest.MonkeyPatch,
    conexao_operador: psycopg.Connection,
    empresa: EmpresaTeste,
) -> None:
    # O ponto de entrada, com os privilégios da ETL e o relógio de agora. Só a
    # empresa do teste entra, porque o seed do banco local tem outras, e sem
    # as esperas do cliente, para que uma chamada não simulada falhe na hora.
    monkeypatch.setattr(
        carga_historica,
        "listar_empresas_ativas",
        lambda conexao: [empresa.empresa_id],
    )
    monkeypatch.setattr(
        carga_historica,
        "ClienteApiMeta",
        partial(ClienteApiMeta, dormir=lambda segundos: None),
    )
    hoje = agora_utc().astimezone(ZoneInfo(FUSO_BRASILIA)).date()
    meses = listar_meses(calcular_limite(hoje), hoje - timedelta(days=1))

    with responses.RequestsMock(registry=OrderedRegistry) as api:
        simular_historico(api, meses, {}, hoje=hoje)
        codigo = executar_carga_historica(Ambiente(TOKEN, URL_BANCO_ETL))

    assert codigo == CODIGO_SAIDA_SUCESSO
    assert ler_fatias(conexao_operador, empresa.empresa_id) == [
        (mes, "concluida") for mes in meses
    ]
