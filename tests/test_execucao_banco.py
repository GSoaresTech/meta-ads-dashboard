"""Prova, contra o banco local, a execução por empresa de ponta a ponta: o
registro de início e de fim, a falha de uma empresa isolada da outra, a
execução concorrente ignorada, a leitura concorrente sem carga parcial e o
código de saída do job (RF-17 a RF-20, RF-50, RNF-09; CLAUDE.md §6). Exige
o banco local de pé.
"""

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest

from etl.carga import Contagens
from etl.cliente_api_meta import ErroApiMeta, ErroAutenticacao
from etl.configuracao import RETENCAO_BRUTO_DIAS
from etl.execucao import StatusExecucao, executar_empresa, executar_empresas
from etl.log_estruturado import montar_campos
from tests.carga_exemplo import (
    COLUNAS_NEGOCIO,
    CargaExemplo,
    carregar_exemplo,
    carregar_hierarquia,
    ler_estado,
    montar_carga,
    montar_dias,
    trocar_dia,
)
from tests.conftest import EmpresaTeste

pytestmark = pytest.mark.integracao

TEMPO_MAXIMO_SINCRONIA_SEGUNDOS = 10
ESPERA_CURTA_SEGUNDOS = 0.3
INTERVALO_CURTO_SEGUNDOS = 0.05
PREFIXOS_ID_META = ("99031", "99032")
# Revisão da Meta: os valores de todos os dias mudam.
FATOR_REVISAO = Decimal(2)
CODIGO_TOKEN_INVALIDO = 190
CONTAGENS_CARGA_EXEMPLO = {
    "campanha": 1,
    "conjunto_anuncio": 1,
    "criativo": 1,
    "anuncio": 1,
    "metrica_diaria_anuncio": 6,
    "acao_diaria_anuncio": 18,
    "resposta_api": 1,
}


class FalhaInjetada(Exception):
    """Falha no meio da carga."""


@dataclass
class TarefaExemplo:
    """Faz o papel da rotina: extrai, aqui sem rede, a carga de cada empresa
    e a carrega com as funções reais de etl.carga."""

    cargas: Mapping[UUID, CargaExemplo]
    erros_extracao: Mapping[UUID, Exception] = field(default_factory=dict)
    execucoes: dict[UUID, UUID] = field(default_factory=dict)

    def extrair(self, empresa_id: UUID) -> CargaExemplo:
        if empresa_id in self.erros_extracao:
            raise self.erros_extracao[empresa_id]
        return self.cargas[empresa_id]

    def carregar(
        self,
        conexao: psycopg.Connection,
        empresa_id: UUID,
        execucao_id: UUID,
        dados: CargaExemplo,
    ) -> Contagens:
        self.execucoes[empresa_id] = execucao_id
        return carregar_exemplo(conexao, execucao_id, dados)


@dataclass
class TarefaRetida(TarefaExemplo):
    """Carrega tudo e fica dentro da transação, com o lock, até ser liberada;
    então termina ou falha."""

    carregou: threading.Event = field(default_factory=threading.Event)
    liberar: threading.Event = field(default_factory=threading.Event)
    falhar: bool = False

    def carregar(
        self,
        conexao: psycopg.Connection,
        empresa_id: UUID,
        execucao_id: UUID,
        dados: CargaExemplo,
    ) -> Contagens:
        contagens = super().carregar(conexao, empresa_id, execucao_id, dados)
        self.carregou.set()
        if not self.liberar.wait(TEMPO_MAXIMO_SINCRONIA_SEGUNDOS):
            raise TimeoutError("a carga retida não foi liberada")
        if self.falhar:
            raise FalhaInjetada
        return contagens


def montar_cargas(empresas: Sequence[EmpresaTeste]) -> dict[UUID, CargaExemplo]:
    return {
        empresa.empresa_id: montar_carga(empresa.empresa_id, empresa.conta_id, prefixo)
        for empresa, prefixo in zip(empresas, PREFIXOS_ID_META, strict=True)
    }


def revisar(carga: CargaExemplo) -> CargaExemplo:
    for indice, dia in enumerate(carga.dias):
        carga = trocar_dia(carga, indice, investimento=dia.investimento * FATOR_REVISAO)
    return carga


def ler_execucoes(conexao: psycopg.Connection, empresa_id: UUID) -> list[tuple]:
    return conexao.execute(
        "SELECT id, tipo, status, terminado_em IS NOT NULL, erro"
        " FROM normalizado.execucao_carga WHERE empresa_id = %s ORDER BY iniciado_em",
        (empresa_id,),
    ).fetchall()


def ler_contagens(conexao: psycopg.Connection, execucao_id: UUID) -> dict[str, int]:
    return dict(
        conexao.execute(
            "SELECT tabela, linhas FROM normalizado.contagem_linhas_execucao"
            " WHERE execucao_id = %s",
            (execucao_id,),
        ).fetchall()
    )


def contar_linhas_da_execucao(conexao: psycopg.Connection, execucao_id: UUID) -> int:
    """As linhas que a execução gravou em qualquer tabela da carga."""
    return conexao.execute(
        "SELECT (SELECT count(*) FROM normalizado.campanha WHERE execucao_id = %(id)s)"
        " + (SELECT count(*) FROM normalizado.conjunto_anuncio WHERE execucao_id = %(id)s)"
        " + (SELECT count(*) FROM normalizado.criativo WHERE execucao_id = %(id)s)"
        " + (SELECT count(*) FROM normalizado.anuncio WHERE execucao_id = %(id)s)"
        " + (SELECT count(*) FROM normalizado.metrica_diaria_anuncio"
        "    WHERE execucao_id = %(id)s)"
        " + (SELECT count(*) FROM normalizado.acao_diaria_anuncio"
        "    WHERE execucao_id = %(id)s)",
        {"id": execucao_id},
    ).fetchone()[0]


def test_execucoes_com_sucesso_ficam_registradas_e_saem_com_zero(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    tarefa = TarefaExemplo(montar_cargas(empresas))
    empresa_ids = [empresa.empresa_id for empresa in empresas]

    codigo = executar_empresas(conectar_etl, empresa_ids, "horaria", tarefa)

    assert codigo == 0
    for empresa_id in empresa_ids:
        [(execucao_id, tipo, status, terminou, erro)] = ler_execucoes(
            conexao_operador, empresa_id
        )
        assert execucao_id == tarefa.execucoes[empresa_id]
        assert (tipo, status, terminou, erro) == ("horaria", "sucesso", True, None)
        assert ler_contagens(conexao_operador, execucao_id) == CONTAGENS_CARGA_EXEMPLO


def test_falha_no_meio_da_carga_nao_deixa_linha_e_nao_afeta_a_outra_empresa(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa_a, empresa_b = (empresa.empresa_id for empresa in empresas)
    cargas = montar_cargas(empresas)
    executar_empresas(
        conectar_etl, [empresa_a, empresa_b], "diaria", TarefaExemplo(cargas)
    )
    estado_a = ler_estado(conexao_operador, [empresa_a])
    estado_b = ler_estado(conexao_operador, [empresa_b])
    # Na revisão, o quarto dos seis dias de A viola o CHECK de investimento:
    # a carga de A falha depois de gravar a hierarquia e metade das métricas.
    revisadas = {
        empresa_a: trocar_dia(revisar(cargas[empresa_a]), 3, investimento=Decimal(-1)),
        empresa_b: revisar(cargas[empresa_b]),
    }
    tarefa = TarefaExemplo(revisadas)

    codigo = executar_empresas(conectar_etl, [empresa_a, empresa_b], "diaria", tarefa)

    assert codigo == 1
    assert ler_estado(conexao_operador, [empresa_a]) == estado_a
    assert contar_linhas_da_execucao(conexao_operador, tarefa.execucoes[empresa_a]) == 0
    assert ler_estado(conexao_operador, [empresa_b]) != estado_b
    assert (
        contar_linhas_da_execucao(conexao_operador, tarefa.execucoes[empresa_b]) == 28
    )
    [_, (id_a, _, status_a, terminou_a, erro_a)] = ler_execucoes(
        conexao_operador, empresa_a
    )
    assert (status_a, terminou_a) == ("falha", True)
    assert erro_a.startswith("CheckViolation: ")
    assert ler_contagens(conexao_operador, id_a) == {}
    [_, (_, _, status_b, _, _)] = ler_execucoes(conexao_operador, empresa_b)
    assert status_b == "sucesso"


def test_falha_na_extracao_fica_registrada_e_a_outra_empresa_carrega(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
    caplog: pytest.LogCaptureFixture,
) -> None:
    empresa_a, empresa_b = (empresa.empresa_id for empresa in empresas)
    erro = ErroAutenticacao(codigo=CODIGO_TOKEN_INVALIDO)
    tarefa = TarefaExemplo(montar_cargas(empresas), erros_extracao={empresa_a: erro})

    codigo = executar_empresas(conectar_etl, [empresa_a, empresa_b], "horaria", tarefa)

    assert codigo == 1
    [(_, _, status_a, terminou_a, erro_a)] = ler_execucoes(conexao_operador, empresa_a)
    assert (status_a, terminou_a, erro_a) == (
        "falha",
        True,
        f"ErroAutenticacao: {erro}",
    )
    [(_, _, status_b, _, _)] = ler_execucoes(conexao_operador, empresa_b)
    assert status_b == "sucesso"
    falhas = [r for r in caplog.records if getattr(r, "status", None) == "falha"]
    assert [r.codigo_erro for r in falhas] == [CODIGO_TOKEN_INVALIDO]


def test_execucao_concorrente_da_mesma_empresa_fica_ignorada_sem_escrever(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa_id = empresas[0].empresa_id
    carga = montar_cargas(empresas)[empresa_id]
    primeira = TarefaRetida({empresa_id: carga})
    segunda = TarefaExemplo({empresa_id: replace(carga, nome_campanha="Outra")})

    with ThreadPoolExecutor(max_workers=1) as executor:
        futuro = executor.submit(
            executar_empresa, conectar_etl, empresa_id, "diaria", primeira
        )
        assert primeira.carregou.wait(TEMPO_MAXIMO_SINCRONIA_SEGUNDOS)
        try:
            codigo = executar_empresas(
                conectar_etl,
                [empresa_id],
                "horaria",
                segunda,
                espera_maxima_segundos=ESPERA_CURTA_SEGUNDOS,
                intervalo_segundos=INTERVALO_CURTO_SEGUNDOS,
            )
        finally:
            primeira.liberar.set()
        status_primeira = futuro.result(TEMPO_MAXIMO_SINCRONIA_SEGUNDOS)

    assert status_primeira == StatusExecucao.SUCESSO
    assert codigo == 0
    assert segunda.execucoes == {}
    execucoes = {
        tipo: (id_, status, terminou, erro)
        for id_, tipo, status, terminou, erro in ler_execucoes(
            conexao_operador, empresa_id
        )
    }
    id_ignorada, status, terminou, erro = execucoes["horaria"]
    assert (status, terminou, erro) == ("ignorada", True, None)
    assert contar_linhas_da_execucao(conexao_operador, id_ignorada) == 0
    assert ler_contagens(conexao_operador, id_ignorada) == {}
    assert execucoes["diaria"][1] == "sucesso"


def test_leitura_concorrente_nao_ve_a_carga_que_falha(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa_id = empresas[0].empresa_id
    carga = montar_cargas(empresas)[empresa_id]
    executar_empresas(
        conectar_etl, [empresa_id], "diaria", TarefaExemplo({empresa_id: carga})
    )
    estado = ler_estado(conexao_operador, [empresa_id])
    tarefa = TarefaRetida({empresa_id: revisar(carga)}, falhar=True)

    with ThreadPoolExecutor(max_workers=1) as executor:
        futuro = executor.submit(
            executar_empresa, conectar_etl, empresa_id, "diaria", tarefa
        )
        assert tarefa.carregou.wait(TEMPO_MAXIMO_SINCRONIA_SEGUNDOS)
        try:
            # A carga já apagou e regravou a janela, sem confirmar.
            durante = ler_estado(conexao_operador, [empresa_id])
            linhas_durante = contar_linhas_da_execucao(
                conexao_operador, tarefa.execucoes[empresa_id]
            )
        finally:
            tarefa.liberar.set()
        status = futuro.result(TEMPO_MAXIMO_SINCRONIA_SEGUNDOS)

    assert status == StatusExecucao.FALHA
    assert (durante, linhas_durante) == (estado, 0)
    assert ler_estado(conexao_operador, [empresa_id]) == estado
    assert (
        contar_linhas_da_execucao(conexao_operador, tarefa.execucoes[empresa_id]) == 0
    )


def test_log_da_execucao_nao_traz_a_mensagem_do_erro(
    conectar_etl: Callable[[], psycopg.Connection],
    empresas: tuple[EmpresaTeste, EmpresaTeste],
    caplog: pytest.LogCaptureFixture,
) -> None:
    empresa_id = empresas[0].empresa_id
    carga = montar_cargas(empresas)[empresa_id]
    tarefa = TarefaExemplo({empresa_id: trocar_dia(carga, 0, investimento=Decimal(-1))})

    with caplog.at_level(logging.INFO):
        executar_empresas(conectar_etl, [empresa_id], "diaria", tarefa)

    # A mensagem do psycopg traz os valores da linha recusada, que não podem
    # ir ao log público (RNF-17). O registro leva só os campos permitidos.
    assert {
        r.getMessage() for r in caplog.records if r.name == "etl.log_estruturado"
    } == {"evento"}
    # Extrair, carregar e, na diária, reter, que roda antes da carga falhar.
    assert [r.status for r in caplog.records if r.name == "etl.log_estruturado"] == [
        "em_andamento",
        "em_andamento",
        "em_andamento",
        "falha",
    ]


def test_falha_sem_registro_de_inicio_nao_interrompe_as_outras_empresas(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    # Uma empresa que não existe: a FK recusa o registro de início, e o de
    # fim não acha a execução.
    inexistente = uuid4()
    empresa_b = empresas[1].empresa_id
    tarefa = TarefaExemplo(montar_cargas(empresas))

    codigo = executar_empresas(
        conectar_etl, [inexistente, empresa_b], "horaria", tarefa
    )

    assert codigo == 1
    [(_, _, status_b, _, _)] = ler_execucoes(conexao_operador, empresa_b)
    assert status_b == "sucesso"


def test_falha_sem_banco_para_registrar_o_fim_nao_interrompe_o_laco(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa_a, empresa_b = (empresa.empresa_id for empresa in empresas)
    banco_fora = threading.Event()

    def conectar() -> psycopg.Connection:
        if banco_fora.is_set():
            raise psycopg.OperationalError("banco fora do ar")
        return conectar_etl()

    class TarefaQueDerrubaOBanco(TarefaExemplo):
        def extrair(self, empresa_id: UUID) -> CargaExemplo:
            if empresa_id == empresa_a:
                banco_fora.set()
                raise FalhaInjetada
            return super().extrair(empresa_id)

    status = executar_empresa(
        conectar, empresa_a, "horaria", TarefaQueDerrubaOBanco(montar_cargas(empresas))
    )
    banco_fora.clear()
    codigo = executar_empresas(
        conectar, [empresa_b], "horaria", TarefaExemplo(montar_cargas(empresas))
    )

    assert (status, codigo) == (StatusExecucao.FALHA, 0)
    # Sem banco para o registro de fim, a execução fica em andamento, e a
    # área do operador a destaca como carga parada (RNF-13).
    [(_, _, status_a, terminou_a, _)] = ler_execucoes(conexao_operador, empresa_a)
    assert (status_a, terminou_a) == ("em_andamento", False)


@pytest.mark.parametrize(
    "erro",
    [
        # Código da Meta fora do domínio do logger: não pode derrubar o laço.
        ErroApiMeta(codigo=-1),
        # NUL na mensagem, que o Postgres recusa em texto.
        ValueError("valor\x00cru"),
    ],
)
def test_falha_com_erro_atipico_fica_registrada_e_o_laco_segue(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
    erro: Exception,
) -> None:
    empresa_a, empresa_b = (empresa.empresa_id for empresa in empresas)
    tarefa = TarefaExemplo(montar_cargas(empresas), erros_extracao={empresa_a: erro})

    codigo = executar_empresas(conectar_etl, [empresa_a, empresa_b], "horaria", tarefa)

    assert codigo == 1
    [(_, _, status_a, terminou_a, erro_a)] = ler_execucoes(conexao_operador, empresa_a)
    assert (status_a, terminou_a) == ("falha", True)
    assert erro_a.startswith(type(erro).__name__)
    [(_, _, status_b, _, _)] = ler_execucoes(conexao_operador, empresa_b)
    assert status_b == "sucesso"


def test_falha_no_registro_de_fim_nao_marca_falha_na_carga_confirmada(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa_id = empresas[0].empresa_id

    class TarefaComContagemInvalida(TarefaExemplo):
        def carregar(
            self,
            conexao: psycopg.Connection,
            empresa_id: UUID,
            execucao_id: UUID,
            dados: CargaExemplo,
        ) -> Contagens:
            contagens = super().carregar(conexao, empresa_id, execucao_id, dados)
            # O CHECK de contagem_linhas_execucao recusa a tabela vazia, e o
            # registro de fim falha depois do COMMIT da carga.
            return contagens | {"": 1}

    tarefa = TarefaComContagemInvalida(montar_cargas(empresas))

    codigo = executar_empresas(conectar_etl, [empresa_id], "diaria", tarefa)

    assert codigo == 1
    [(execucao_id, _, status, terminou, erro)] = ler_execucoes(
        conexao_operador, empresa_id
    )
    assert (status, terminou, erro) == ("em_andamento", False, None)
    assert contar_linhas_da_execucao(conexao_operador, execucao_id) == 28


def contar_linhas_sem_bruto(conexao: psycopg.Connection, empresa_id: UUID) -> int:
    """As linhas de normalizado da empresa cuja execução não gravou nenhuma
    resposta bruta (RF-09)."""
    return sum(
        conexao.execute(
            f"SELECT count(*) FROM normalizado.{tabela} AS linha"
            " WHERE linha.empresa_id = %s AND NOT EXISTS ("
            "  SELECT FROM bruto.resposta_api AS resposta"
            "  WHERE resposta.empresa_id = linha.empresa_id"
            "    AND resposta.execucao_id = linha.execucao_id)",
            (empresa_id,),
        ).fetchone()[0]
        for tabela in COLUNAS_NEGOCIO
    )


def test_toda_linha_carregada_tem_resposta_bruta_da_mesma_execucao(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa_ids = [empresa.empresa_id for empresa in empresas]
    cargas = montar_cargas(empresas)
    executar_empresas(conectar_etl, empresa_ids, "diaria", TarefaExemplo(cargas))
    # A revisão regrava os fatos com a segunda execução, e as entidades
    # passam a apontar para ela.
    revisadas = {empresa_id: revisar(carga) for empresa_id, carga in cargas.items()}

    codigo = executar_empresas(
        conectar_etl, empresa_ids, "horaria", TarefaExemplo(revisadas)
    )

    assert codigo == 0
    for empresa_id in empresa_ids:
        assert ler_estado(conexao_operador, [empresa_id])["campanha"][0] == 1
        assert contar_linhas_sem_bruto(conexao_operador, empresa_id) == 0


def test_carga_sem_resposta_bruta_falha_sem_gravar_nada(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa_a, empresa_b = (empresa.empresa_id for empresa in empresas)

    class TarefaSemBruto(TarefaExemplo):
        def carregar(
            self,
            conexao: psycopg.Connection,
            empresa_id: UUID,
            execucao_id: UUID,
            dados: CargaExemplo,
        ) -> Contagens:
            self.execucoes[empresa_id] = execucao_id
            contagens: Contagens = {}
            carregar_hierarquia(conexao, execucao_id, dados, contagens)
            return contagens

    cargas = montar_cargas(empresas)
    tarefa = TarefaSemBruto({empresa_a: cargas[empresa_a]})
    estado_a = ler_estado(conexao_operador, [empresa_a])

    codigo = executar_empresas(conectar_etl, [empresa_a], "diaria", tarefa)
    codigo_b = executar_empresas(
        conectar_etl, [empresa_b], "diaria", TarefaExemplo(cargas)
    )

    assert (codigo, codigo_b) == (1, 0)
    assert ler_estado(conexao_operador, [empresa_a]) == estado_a
    assert contar_linhas_da_execucao(conexao_operador, tarefa.execucoes[empresa_a]) == 0
    [(_, _, status, terminou, erro)] = ler_execucoes(conexao_operador, empresa_a)
    assert (status, terminou) == ("falha", True)
    assert erro.startswith("ErroSemRespostaBruta")


def inserir_resposta_antiga(
    conexao: psycopg.Connection, empresa: EmpresaTeste, dias_atras: int
) -> None:
    """Uma resposta de uma execução passada, com a data de referência a
    tantos dias de hoje em UTC, o dia da conta sem fuso."""
    with conexao.transaction():
        execucao_id = conexao.execute(
            "INSERT INTO normalizado.execucao_carga (empresa_id, tipo)"
            " VALUES (%s, 'diaria') RETURNING id",
            (empresa.empresa_id,),
        ).fetchone()[0]
        conexao.execute(
            "INSERT INTO bruto.resposta_api (empresa_id, execucao_id,"
            " conta_anuncio_id, endpoint, parametros, data_referencia, resposta)"
            " VALUES (%s, %s, %s, 'insights', '{}',"
            " (now() AT TIME ZONE 'UTC')::date - %s::integer, '{}')",
            (empresa.empresa_id, execucao_id, empresa.conta_id, dias_atras),
        )


def ler_hoje_utc(conexao: psycopg.Connection) -> date:
    return conexao.execute("SELECT (now() AT TIME ZONE 'UTC')::date").fetchone()[0]


def contar_respostas_vencidas(conexao: psycopg.Connection, empresa_id: UUID) -> int:
    """O critério do RF-21: respostas anteriores a hoje menos a retenção."""
    limite = ler_hoje_utc(conexao) - timedelta(days=RETENCAO_BRUTO_DIAS)
    return conexao.execute(
        "SELECT count(*) FROM bruto.resposta_api"
        " WHERE empresa_id = %s AND data_referencia < %s",
        (empresa_id, limite),
    ).fetchone()[0]


def contar_respostas(conexao: psycopg.Connection, empresa_id: UUID) -> int:
    return conexao.execute(
        "SELECT count(*) FROM bruto.resposta_api WHERE empresa_id = %s",
        (empresa_id,),
    ).fetchone()[0]


def test_execucao_diaria_apaga_o_bruto_vencido_e_registra_so_a_contagem(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
    caplog: pytest.LogCaptureFixture,
) -> None:
    for empresa in empresas:
        for dias_atras in (RETENCAO_BRUTO_DIAS + 30, RETENCAO_BRUTO_DIAS + 1):
            inserir_resposta_antiga(conexao_operador, empresa, dias_atras)
        inserir_resposta_antiga(conexao_operador, empresa, RETENCAO_BRUTO_DIAS)
    empresa_ids = [empresa.empresa_id for empresa in empresas]
    # Dias recentes, para que a resposta da própria execução fique dentro da
    # retenção em qualquer data em que o teste rodar.
    dias = montar_dias(inicio=ler_hoje_utc(conexao_operador) - timedelta(days=5))
    tarefa = TarefaExemplo(
        {
            empresa.empresa_id: montar_carga(
                empresa.empresa_id, empresa.conta_id, prefixo, dias
            )
            for empresa, prefixo in zip(empresas, PREFIXOS_ID_META, strict=True)
        }
    )

    with caplog.at_level(logging.INFO):
        codigo = executar_empresas(conectar_etl, empresa_ids, "diaria", tarefa)

    assert codigo == 0
    for empresa_id in empresa_ids:
        assert contar_respostas_vencidas(conexao_operador, empresa_id) == 0
        # A do limite e a da própria execução ficam.
        assert contar_respostas(conexao_operador, empresa_id) == 2
        assert (
            ler_contagens(conexao_operador, tarefa.execucoes[empresa_id])
            == CONTAGENS_CARGA_EXEMPLO
        )
    retencoes = [
        r
        for r in caplog.records
        if r.name == "etl.log_estruturado" and getattr(r, "etapa", None) == "reter"
    ]
    assert [montar_campos(r, None) for r in retencoes] == [
        {
            "instante": montar_campos(r, None)["instante"],
            "nivel": "INFO",
            "etapa": "reter",
            "status": "em_andamento",
            "linhas": 2,
        }
        for r in retencoes
    ]
    assert len(retencoes) == len(empresa_ids)


def test_execucao_horaria_nao_aplica_a_retencao(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa = empresas[0]
    inserir_resposta_antiga(conexao_operador, empresa, RETENCAO_BRUTO_DIAS + 1)
    # Dias recentes, para que a resposta da própria execução fique dentro da
    # retenção em qualquer data em que o teste rodar e só a antiga conte.
    dias = montar_dias(inicio=ler_hoje_utc(conexao_operador) - timedelta(days=5))
    tarefa = TarefaExemplo(
        {
            empresa.empresa_id: montar_carga(
                empresa.empresa_id, empresa.conta_id, PREFIXOS_ID_META[0], dias
            )
        }
    )

    codigo = executar_empresas(conectar_etl, [empresa.empresa_id], "horaria", tarefa)

    assert codigo == 0
    assert contar_respostas_vencidas(conexao_operador, empresa.empresa_id) == 1


def test_falha_na_retencao_desfaz_a_carga_da_execucao_diaria(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa = empresas[0]
    inserir_resposta_antiga(conexao_operador, empresa, RETENCAO_BRUTO_DIAS + 1)
    estado = ler_estado(conexao_operador, [empresa.empresa_id])
    # Sem o DELETE em bruto, a retenção falha depois de toda a carga.
    conexao_operador.execute("REVOKE DELETE ON bruto.resposta_api FROM etl_carga")
    try:
        tarefa = TarefaExemplo(montar_cargas(empresas))
        codigo = executar_empresas(conectar_etl, [empresa.empresa_id], "diaria", tarefa)
    finally:
        conexao_operador.execute("GRANT DELETE ON bruto.resposta_api TO etl_carga")

    assert codigo == 1
    assert ler_estado(conexao_operador, [empresa.empresa_id]) == estado
    assert contar_respostas(conexao_operador, empresa.empresa_id) == 1
    [_, (_, _, status, _, erro)] = ler_execucoes(conexao_operador, empresa.empresa_id)
    assert status == "falha"
    assert erro.startswith("InsufficientPrivilege")


def test_retencao_nao_apaga_o_bruto_da_propria_execucao_diaria(
    conectar_etl: Callable[[], psycopg.Connection],
    conexao_operador: psycopg.Connection,
    empresas: tuple[EmpresaTeste, EmpresaTeste],
) -> None:
    empresa = empresas[0]
    # A janela da carga termina antes do limite da retenção.
    antiga = ler_hoje_utc(conexao_operador) - timedelta(days=RETENCAO_BRUTO_DIAS + 30)
    carga = montar_carga(
        empresa.empresa_id,
        empresa.conta_id,
        PREFIXOS_ID_META[0],
        montar_dias(inicio=antiga),
    )
    tarefa = TarefaExemplo({empresa.empresa_id: carga})

    codigo = executar_empresas(conectar_etl, [empresa.empresa_id], "diaria", tarefa)

    assert codigo == 0
    assert contar_respostas(conexao_operador, empresa.empresa_id) == 1
    assert contar_linhas_sem_bruto(conexao_operador, empresa.empresa_id) == 0
