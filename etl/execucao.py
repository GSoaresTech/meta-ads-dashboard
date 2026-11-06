"""Execução de uma rotina da ETL: o laço por empresa, cada uma com o registro
de início e de fim, a extração fora de transação e a carga na transação da
empresa, e o código de saída do job (CLAUDE.md §3 e §6; ADR-0009 §5).
"""

import logging
from collections.abc import Callable, Iterable, Sequence
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID, uuid4

import psycopg

from etl.carga import (
    Contagens,
    apagar_respostas_vencidas,
    contar_respostas_brutas,
    executar_com_lock,
)
from etl.cliente_api_meta import ErroApiMeta
from etl.configuracao import (
    ESPERA_MAXIMA_LOCK_SEGUNDOS,
    INTERVALO_TENTATIVA_LOCK_SEGUNDOS,
)
from etl.log_estruturado import (
    contexto_execucao,
    registrar_evento,
    validar_campo_registro,
)

# Diferente de zero, o código de saída faz o GitHub notificar a falha do
# workflow (RF-50).
CODIGO_SAIDA_SUCESSO: Final = 0
CODIGO_SAIDA_FALHA: Final = 1

# A chave das respostas brutas nas linhas por tabela do registro de fim.
TABELA_BRUTO: Final = "resposta_api"
# Só a execução diária aplica a retenção de bruto (ADR-0005).
TIPO_COM_RETENCAO: Final = "diaria"


class StatusExecucao(StrEnum):
    """Os status de fim do CHECK de execucao_carga."""

    SUCESSO = "sucesso"
    FALHA = "falha"
    IGNORADA = "ignorada"


class ErroRegistroExecucao(Exception):
    """O registro de fim não achou a execução em andamento."""


class ErroRegistroFim(Exception):
    """O registro de fim falhou depois do COMMIT ou da desistência da carga."""


class ErroSemRespostaBruta(Exception):
    """A carga gravou linhas em normalizado sem nenhuma resposta bruta da
    mesma execução, o que as deixaria sem rastro até a API (RF-09)."""


class TarefaCarga[D](Protocol):
    """O que cada rotina faz por empresa. extrair faz todo o I/O de rede, fora
    de transação. carregar roda na transação da empresa, já com o lock, grava
    o bruto, transforma e carrega normalizado, e devolve as linhas gravadas
    em normalizado por tabela; as do bruto, a execução conta."""

    def extrair(self, empresa_id: UUID) -> D: ...

    def carregar(
        self,
        conexao: psycopg.Connection,
        empresa_id: UUID,
        execucao_id: UUID,
        dados: D,
    ) -> Contagens: ...


def executar_empresas[D](
    conectar: Callable[[], psycopg.Connection],
    empresas: Sequence[UUID],
    tipo: str,
    tarefa: TarefaCarga[D],
    *,
    espera_maxima_segundos: float = ESPERA_MAXIMA_LOCK_SEGUNDOS,
    intervalo_segundos: float = INTERVALO_TENTATIVA_LOCK_SEGUNDOS,
) -> int:
    """Executa cada empresa em sequência e devolve o código de saída do job.

    A falha de uma empresa não interrompe nem desfaz as outras.
    """
    status = [
        executar_empresa(
            conectar,
            empresa_id,
            tipo,
            tarefa,
            espera_maxima_segundos=espera_maxima_segundos,
            intervalo_segundos=intervalo_segundos,
        )
        for empresa_id in empresas
    ]
    return calcular_codigo_saida(status)


def calcular_codigo_saida(status: Iterable[StatusExecucao]) -> int:
    """Só a falha notifica (RF-50). A ignorada é outro status no RF-19: a
    próxima execução agendada recarrega os dias dela, e uma carga que segura
    o lock por mais da espera máxima aparece como parada na área do operador
    (RNF-13)."""
    if StatusExecucao.FALHA in status:
        return CODIGO_SAIDA_FALHA
    return CODIGO_SAIDA_SUCESSO


def executar_empresa[D](
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    tipo: str,
    tarefa: TarefaCarga[D],
    *,
    espera_maxima_segundos: float = ESPERA_MAXIMA_LOCK_SEGUNDOS,
    intervalo_segundos: float = INTERVALO_TENTATIVA_LOCK_SEGUNDOS,
) -> StatusExecucao:
    # O id nasce aqui, e não no banco, para que as linhas de log tenham o
    # execucao_id mesmo quando o registro de início falha.
    execucao_id = uuid4()
    with contexto_execucao(execucao_id, empresa_id, tipo):
        try:
            return processar_execucao(
                conectar,
                empresa_id,
                execucao_id,
                tipo,
                tarefa,
                espera_maxima_segundos,
                intervalo_segundos,
            )
        except ErroRegistroFim:
            # A carga já foi confirmada, ou desistiu sem escrever: gravar
            # falha diria que os dados não entraram. O registro fica
            # em_andamento, como a linha de log informa, e o código de saída
            # avisa.
            registrar_evento("em_andamento", nivel=logging.ERROR)
            return StatusExecucao.FALHA
        # Qualquer erro, da API, da transformação ou do banco, é a falha
        # desta empresa: fica registrado no banco e no log, e o laço segue
        # para a próxima (CLAUDE.md §6).
        except Exception as erro:  # noqa: BLE001
            registrar_falha(conectar, empresa_id, execucao_id, erro)
            return StatusExecucao.FALHA


def processar_execucao[D](
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    execucao_id: UUID,
    tipo: str,
    tarefa: TarefaCarga[D],
    espera_maxima_segundos: float,
    intervalo_segundos: float,
) -> StatusExecucao:
    # Uma conexão para cada passo: a extração pode levar até uma hora, e uma
    # conexão parada nesse tempo poderia ser derrubada pelo pooler.
    with conectar() as conexao:
        registrar_inicio(conexao, empresa_id, execucao_id, tipo)
    registrar_evento("em_andamento", etapa="extrair")
    dados = tarefa.extrair(empresa_id)
    registrar_evento("em_andamento", etapa="carregar")
    with conectar() as conexao:
        contagens = executar_com_lock(
            conexao,
            empresa_id,
            lambda conexao_carga: carregar_execucao(
                conexao_carga, empresa_id, execucao_id, tipo, tarefa, dados
            ),
            espera_maxima_segundos=espera_maxima_segundos,
            intervalo_segundos=intervalo_segundos,
        )
        status = (
            StatusExecucao.IGNORADA if contagens is None else StatusExecucao.SUCESSO
        )
        try:
            registrar_fim(conexao, empresa_id, execucao_id, status, contagens=contagens)
        except (psycopg.Error, ErroRegistroExecucao) as erro:
            raise ErroRegistroFim from erro
    registrar_evento(status, linhas=sum(contagens.values()) if contagens else None)
    return status


def carregar_execucao[D](
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    tipo: str,
    tarefa: TarefaCarga[D],
    dados: D,
) -> Contagens:
    """Na execução diária, a retenção de bruto da empresa; depois, a carga da
    tarefa com a conferência do bruto, tudo na mesma transação.

    A retenção vem antes para nunca apagar a resposta que a própria execução
    acabou de gravar, mesmo com data de referência fora da retenção: as
    linhas de normalizado da execução ficam com o rastro dela (RF-09).
    """
    if tipo == TIPO_COM_RETENCAO:
        reter_respostas_brutas(conexao, empresa_id)
    return carregar_com_rastreio(conexao, empresa_id, execucao_id, tarefa, dados)


def reter_respostas_brutas(conexao: psycopg.Connection, empresa_id: UUID) -> None:
    """Aplica a retenção e registra no log só quantas respostas saíram
    (RF-21; RNF-17).

    A linha sai antes do COMMIT, com status em_andamento: se a transação
    for desfeita depois, a linha de fim da execução registra a falha, e nada
    foi apagado. As linhas apagadas não entram no registro de fim, cuja
    linha resposta_api conta as respostas gravadas pela execução.
    """
    apagadas = apagar_respostas_vencidas(conexao, empresa_id)
    registrar_evento("em_andamento", etapa="reter", linhas=apagadas)


def carregar_com_rastreio[D](
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    tarefa: TarefaCarga[D],
    dados: D,
) -> Contagens:
    """Roda a carga da tarefa e confere, ainda na transação, que ela gravou
    o bruto da execução; sem ele, a carga é desfeita (RF-09).

    A conferência vale para a execução inteira, pelo execucao_id que as
    linhas de normalizado e as respostas brutas compartilham. A contagem do
    bruto vem do banco, e não da tarefa, que pode chamar a gravação várias
    vezes.
    """
    contagens = tarefa.carregar(conexao, empresa_id, execucao_id, dados)
    respostas = contar_respostas_brutas(conexao, empresa_id, execucao_id)
    conferir_rastreio(contagens, respostas)
    return {**contagens, TABELA_BRUTO: respostas}


def conferir_rastreio(contagens: Contagens, respostas: int) -> None:
    """Falha se a carga gravou linhas em normalizado sem nenhuma resposta
    bruta, o que desfaz a transação em vez de deixá-las sem rastro (RF-09)."""
    normalizadas = sum(
        linhas for tabela, linhas in contagens.items() if tabela != TABELA_BRUTO
    )
    if normalizadas and not respostas:
        raise ErroSemRespostaBruta("linhas em normalizado sem resposta bruta")


def registrar_inicio(
    conexao: psycopg.Connection, empresa_id: UUID, execucao_id: UUID, tipo: str
) -> None:
    """Confirmado antes da carga, para sobreviver ao rollback dela (RF-20)."""
    with conexao.transaction():
        conexao.execute(
            "INSERT INTO normalizado.execucao_carga (id, empresa_id, tipo)"
            " VALUES (%s, %s, %s)",
            (execucao_id, empresa_id, tipo),
        )


def registrar_fim(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    status: StatusExecucao,
    *,
    contagens: Contagens | None = None,
    erro: str | None = None,
) -> None:
    """Fecha a execução e grava as linhas por tabela numa transação própria,
    depois do COMMIT ou do ROLLBACK da carga (RF-20; ADR-0009 §5)."""
    with conexao.transaction():
        cursor = conexao.execute(
            "UPDATE normalizado.execucao_carga"
            " SET status = %s, terminado_em = now(), erro = %s"
            " WHERE empresa_id = %s AND id = %s AND status = 'em_andamento'",
            (status, erro, empresa_id, execucao_id),
        )
        if cursor.rowcount != 1:
            raise ErroRegistroExecucao("execução sem registro de início em andamento")
        with conexao.cursor() as cursor_contagens:
            cursor_contagens.executemany(
                "INSERT INTO normalizado.contagem_linhas_execucao"
                " (empresa_id, execucao_id, tabela, linhas) VALUES (%s, %s, %s, %s)",
                [
                    (empresa_id, execucao_id, tabela, linhas)
                    for tabela, linhas in (contagens or {}).items()
                ],
            )


def registrar_falha(
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    execucao_id: UUID,
    erro: Exception,
) -> None:
    """Registra a falha no log, só com os códigos da Meta, e no banco, com a
    descrição do erro.

    A descrição vai só para o banco, que é privado: a mensagem de um erro do
    banco ou da transformação pode trazer valores da linha recusada, que não
    vão ao log público (RNF-17).
    """
    registrar_evento(
        StatusExecucao.FALHA, nivel=logging.ERROR, **ler_codigos_erro(erro)
    )
    try:
        # Conexão nova: a da carga pode ter caído com o erro.
        with conectar() as conexao:
            registrar_fim(
                conexao,
                empresa_id,
                execucao_id,
                StatusExecucao.FALHA,
                erro=descrever_erro(erro),
            )
    except (psycopg.Error, ErroRegistroExecucao):
        # O registro fica em_andamento no banco, e a área do operador o
        # destaca como carga parada (RNF-13). A linha de log diz isso, e o
        # código de saída já sinaliza a falha.
        registrar_evento("em_andamento", nivel=logging.ERROR)


def ler_codigos_erro(erro: Exception) -> dict[str, int]:
    """Os códigos da Meta que cabem no log. Eles vêm do JSON da API: um valor
    fora do domínio do logger é descartado, em vez de levantar erro dentro do
    tratamento da falha, o que derrubaria o laço das outras empresas."""
    if not isinstance(erro, ErroApiMeta):
        return {}
    codigos = {"codigo_erro": erro.codigo, "subcodigo_erro": erro.subcodigo}
    return {
        campo: valor
        for campo, valor in codigos.items()
        if valor is not None and validar_campo_registro(campo, valor) is None
    }


def descrever_erro(erro: Exception) -> str:
    """O tipo e a mensagem, sem espaço nas pontas, como o CHECK de
    execucao_carga.erro exige; sem mensagem, só o tipo. O NUL, que o
    Postgres recusa em texto, vira o caractere de substituição."""
    mensagem = str(erro).replace("\x00", "\ufffd").strip()
    nome = type(erro).__name__
    return f"{nome}: {mensagem}" if mensagem else nome
