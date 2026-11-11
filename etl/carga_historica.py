"""Carga inicial da conta: o cadastro completo de cada conta ativa que ainda
não o tem e até 37 meses de histórico, uma fatia por mês, e o ponto de
entrada dela, `python -m etl.carga_historica` (RF-01, RF-07, RF-22; R-19;
ADR-0009 §5; ADR-0017).

A conta sem fuso ainda não teve o cadastro completo, que só esta carga lê:
ele roda uma vez por conta, antes das fatias, que dependem do fuso dele. A
execução lê primeiro o cadastro das contas novas de todas as empresas e só
depois as fatias de cada uma, para que a conta nova não espere o histórico de
outra empresa. Cada empresa tem uma execução para os cadastros e outra para as
fatias. O cadastro é extraído fora de transação e carregado numa transação
própria, com o lock da empresa (RF-19).

A conta com fuso e sem nenhuma fatia em fatia_historica é nova, seja qual for
a data do cadastro: a execução planeja uma fatia por mês do calendário, do
limite de 37 meses até ontem, no fuso da conta. Depois, carrega as fatias não
concluídas de cada conta, da mais antiga para a mais recente. A retomada é a
mesma leitura: a execução seguinte lê o cadastro que não entrou e continua da
primeira fatia não concluída.

Cada fatia é extraída fora de transação, com os insights e as quebras do mês
e o alcance dos períodos que começam nele, e carregada numa transação
própria, com o lock da empresa e a marca concluida. A carga substitui o mês
da fatia, e refazê-la com a mesma resposta deixa o mesmo estado (RF-17). A
falha no cadastro ou numa fatia encerra só a conta dela, e a fatia fica
marcada como falha; a execução da empresa segue para as outras contas e fica
registrada como falha, com as linhas das etapas já confirmadas, e as outras
empresas seguem (CLAUDE.md §6). Depois do prazo, nenhuma etapa nova começa
(RNF-07), e a empresa sem cadastro ou sem fatia a carregar não gera execução
dessa etapa.
"""

import logging
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Final
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg

from etl.alcance import conferir_calendario
from etl.cadastro import carregar_cadastro_conta, listar_empresas_ativas
from etl.carga import (
    Contagens,
    conectar_banco,
    contar_respostas_brutas,
    executar_com_lock,
)
from etl.cliente_api_meta import ClienteApiMeta
from etl.configuracao import (
    DURACAO_MAXIMA_HISTORICA_SEGUNDOS,
    ESPERA_MAXIMA_LOCK_SEGUNDOS,
    HISTORICO_MAXIMO_MESES,
    INTERVALO_TENTATIVA_LOCK_SEGUNDOS,
    MARGEM_LIMITE_HISTORICO_DIAS,
    Ambiente,
    ErroConfiguracao,
    carregar_ambiente,
)
from etl.execucao import (
    CODIGO_SAIDA_FALHA,
    TABELA_BRUTO,
    ErroRegistroExecucao,
    ErroRegistroFim,
    StatusExecucao,
    calcular_codigo_saida,
    conferir_rastreio,
    registrar_falha,
    registrar_fim,
    registrar_inicio,
)
from etl.extracao import (
    CadastroExtraido,
    PeriodoAlcance,
    TipoPeriodo,
    agora_utc,
    extrair_cadastro_conta,
)
from etl.janela_conta import (
    JanelaContaExtraida,
    carregar_janela_conta,
    extrair_janela_conta,
)
from etl.log_estruturado import configurar_log, contexto_execucao, registrar_evento

TIPO_HISTORICA: Final = "historica"
MESES_POR_ANO: Final = 12

# A conta ativa que ainda não teve o cadastro completo: só ele grava o fuso,
# e numa transação com as entidades.
LISTAR_CONTAS_SEM_CADASTRO: Final = """
SELECT id, id_meta FROM normalizado.conta_anuncio
WHERE empresa_id = %(empresa_id)s AND situacao = 'ativa' AND fuso_horario IS NULL
ORDER BY id_meta
"""

# A conta ativa, já com o cadastro completo, que ainda tem histórico a
# carregar: sem nenhuma fatia, a conta nova, ou com alguma não concluída.
LISTAR_CONTAS_HISTORICO: Final = """
SELECT conta.id, conta.id_meta, conta.fuso_horario
FROM normalizado.conta_anuncio AS conta
WHERE conta.empresa_id = %(empresa_id)s
  AND conta.situacao = 'ativa'
  AND conta.fuso_horario IS NOT NULL
  AND (
    NOT EXISTS (
      SELECT FROM normalizado.fatia_historica AS fatia
      WHERE fatia.empresa_id = conta.empresa_id AND fatia.conta_anuncio_id = conta.id
    )
    OR EXISTS (
      SELECT FROM normalizado.fatia_historica AS fatia
      WHERE fatia.empresa_id = conta.empresa_id AND fatia.conta_anuncio_id = conta.id
        AND fatia.status <> 'concluida'
    )
  )
ORDER BY conta.id_meta
"""

# Um mês do calendário por fatia, só na conta que ainda não tem nenhuma. O
# ON CONFLICT cobre outra execução que tenha planejado a mesma conta ao mesmo
# tempo.
PLANEJAR_FATIAS: Final = """
INSERT INTO normalizado.fatia_historica
  (empresa_id, conta_anuncio_id, mes_referencia, execucao_id)
SELECT DISTINCT %(empresa_id)s::uuid, %(conta_anuncio_id)s::uuid, dia.inicio_mes,
       %(execucao_id)s::uuid
FROM normalizado.calendario AS dia
WHERE dia.data BETWEEN %(limite)s AND %(ontem)s
  AND NOT EXISTS (
    SELECT FROM normalizado.fatia_historica AS fatia
    WHERE fatia.empresa_id = %(empresa_id)s
      AND fatia.conta_anuncio_id = %(conta_anuncio_id)s
  )
ON CONFLICT (empresa_id, conta_anuncio_id, mes_referencia) DO NOTHING
"""

LISTAR_FATIAS_PENDENTES: Final = """
SELECT mes_referencia FROM normalizado.fatia_historica
WHERE empresa_id = %(empresa_id)s AND conta_anuncio_id = %(conta_anuncio_id)s
  AND status <> 'concluida'
ORDER BY mes_referencia
"""

# Os dias do mês da fatia entre o limite e ontem; nenhum, quando o mês todo
# já saiu do limite desde o planejamento.
LER_INTERVALO_FATIA: Final = """
SELECT min(data), max(data) FROM normalizado.calendario
WHERE inicio_mes = %(mes)s AND data BETWEEN %(limite)s AND %(ontem)s
"""

# Os períodos que começam na fatia, cortados em ontem (ADR-0006; ADR-0009
# §5): as semanas ISO que começam nela, numa consulta; o mês, só quando a
# fatia começa no dia 1; e o ano, só quando começa em 1º de janeiro. O
# período que começa antes do limite de 37 meses fica sem alcance, porque a
# fatia cortada no limite não tem o primeiro dia dele.
LER_PERIODOS_FATIA: Final = """
WITH fatia AS (
  SELECT data, inicio_semana, inicio_mes, mes, ano
  FROM normalizado.calendario
  WHERE data BETWEEN %(inicio)s AND %(fim)s
)
SELECT 'semana' AS tipo, min(dia.inicio_semana) AS inicio, max(dia.data) AS fim,
       1 AS ordem
FROM normalizado.calendario AS dia
WHERE dia.inicio_semana IN (SELECT data FROM fatia) AND dia.data <= %(ontem)s
HAVING count(*) > 0
UNION ALL
SELECT 'mes', min(inicio_mes), max(data), 2
FROM fatia
WHERE inicio_mes = %(inicio)s
HAVING count(*) > 0
UNION ALL
SELECT 'ano', min(dia.data), max(dia.data), 3
FROM normalizado.calendario AS dia
JOIN fatia AS primeiro
  ON primeiro.data = %(inicio)s AND primeiro.inicio_mes = primeiro.data
 AND primeiro.mes = 1
WHERE dia.ano = primeiro.ano AND dia.data <= %(ontem)s
HAVING count(*) > 0
ORDER BY ordem
"""

CONCLUIR_FATIA: Final = """
UPDATE normalizado.fatia_historica SET status = 'concluida', execucao_id = %(execucao_id)s
WHERE empresa_id = %(empresa_id)s AND conta_anuncio_id = %(conta_anuncio_id)s
  AND mes_referencia = %(mes)s
"""

# A fatia concluída por outra execução não volta a falha.
MARCAR_FALHA_FATIA: Final = """
UPDATE normalizado.fatia_historica SET status = 'falha', execucao_id = %(execucao_id)s
WHERE empresa_id = %(empresa_id)s AND conta_anuncio_id = %(conta_anuncio_id)s
  AND mes_referencia = %(mes)s AND status <> 'concluida'
"""


# Uma etapa da execução de uma empresa: recebe a empresa, a execução e as
# linhas já gravadas, e devolve o status, ou None sem nada a carregar.
type Processamento = Callable[[UUID, UUID, Counter[str]], StatusExecucao | None]


class ErroFatiaAusente(Exception):
    """A fatia carregada não tem registro em fatia_historica."""


@dataclass(frozen=True)
class ContaHistorica:
    conta_anuncio_id: UUID
    id_meta: str
    fuso_horario: str


@dataclass(frozen=True)
class FatiaExtraida:
    """A fatia de um mês da conta. Sem janela, o mês todo saiu do limite de
    37 meses desde o planejamento, e a fatia é concluída sem dados."""

    conta_anuncio_id: UUID
    mes_referencia: date
    janela: JanelaContaExtraida | None


@dataclass(frozen=True)
class CargaHistorica:
    """A carga inicial das empresas dadas. prazo é o instante do cronômetro a
    partir do qual nenhuma etapa nova, cadastro ou fatia, começa."""

    conectar: Callable[[], psycopg.Connection]
    cliente: ClienteApiMeta
    prazo: float
    relogio: Callable[[], datetime] = field(default=agora_utc)
    cronometro: Callable[[], float] = field(default=time.monotonic)
    espera_maxima_segundos: float = ESPERA_MAXIMA_LOCK_SEGUNDOS
    intervalo_segundos: float = INTERVALO_TENTATIVA_LOCK_SEGUNDOS

    def executar(self, empresas: Sequence[UUID]) -> int:
        """O cadastro completo das contas que ainda não o têm, em todas as
        empresas, e depois as fatias de cada empresa, até o prazo; devolve o
        código de saída do job.

        O cadastro de todas vem antes de qualquer fatia: o histórico de uma
        empresa pode ocupar o prazo de várias execuções, e a conta nova de
        outra não pode esperar por ele (RF-22). Cada etapa de cada empresa é
        uma execução, e a falha de uma empresa não interrompe as outras
        (RF-50).
        """
        status = []
        for processar in (self.processar_cadastros, self.processar_historico):
            for empresa_id in empresas:
                if self.esgotou_prazo():
                    break
                resultado = self.executar_empresa(empresa_id, processar)
                if resultado is not None:
                    status.append(resultado)
        return calcular_codigo_saida(status)

    def esgotou_prazo(self) -> bool:
        return self.cronometro() >= self.prazo

    def executar_empresa(
        self, empresa_id: UUID, processar: Processamento
    ) -> StatusExecucao | None:
        """Uma execução histórica da etapa, se a empresa tem o que carregar
        nela; sem isso, None."""
        # O id nasce aqui, e não no banco, para que as linhas de log tenham o
        # execucao_id mesmo quando o registro de início falha.
        execucao_id = uuid4()
        contagens: Counter[str] = Counter()
        with contexto_execucao(execucao_id, empresa_id, TIPO_HISTORICA):
            try:
                return processar(empresa_id, execucao_id, contagens)
            except ErroRegistroFim:
                # As etapas já foram confirmadas: gravar falha diria que os
                # dados não entraram. O registro fica em_andamento.
                registrar_evento("em_andamento", nivel=logging.ERROR)
                return StatusExecucao.FALHA
            # Qualquer erro, da API, da transformação ou do banco, inclusive o
            # da leitura das contas, é a falha desta empresa, registrada com
            # as linhas das etapas confirmadas antes dele; o laço segue para a
            # próxima (CLAUDE.md §6).
            except Exception as erro:  # noqa: BLE001
                registrar_falha(
                    self.conectar,
                    empresa_id,
                    execucao_id,
                    erro,
                    contagens=dict(contagens),
                )
                return StatusExecucao.FALHA
            # O Actions cancela o job que passa do limite de tempo com SIGINT
            # e espera 7,5 s antes do SIGTERM: dá tempo de fechar o registro,
            # que ficaria em_andamento (RF-20). A etapa em andamento é desfeita:
            # a fatia fica pendente, e a conta do cadastro, sem fuso. A
            # interrupção segue para o ponto de entrada.
            except KeyboardInterrupt as interrupcao:
                registrar_falha(
                    self.conectar,
                    empresa_id,
                    execucao_id,
                    interrupcao,
                    contagens=dict(contagens),
                )
                raise

    def processar_cadastros(
        self, empresa_id: UUID, execucao_id: UUID, contagens: Counter[str]
    ) -> StatusExecucao | None:
        """Registra o início, se a empresa tem conta sem cadastro, e carrega o
        cadastro de cada uma."""
        with self.conectar() as conexao:
            contas = listar_contas_sem_cadastro(conexao, empresa_id)
            if not contas:
                return None
            registrar_inicio(conexao, empresa_id, execucao_id, TIPO_HISTORICA)
        status = self.carregar_cadastros(empresa_id, execucao_id, contas, contagens)
        return self.encerrar_execucao(empresa_id, execucao_id, status, contagens)

    def processar_historico(
        self, empresa_id: UUID, execucao_id: UUID, contagens: Counter[str]
    ) -> StatusExecucao | None:
        """Registra o início, planeja as fatias de todas as contas novas, para
        que a carga de cada uma comece nesta execução (RF-22), e carrega as
        fatias não concluídas."""
        # Uma conexão para cada passo: a extração de uma fatia pode levar
        # muito tempo, e uma conexão parada poderia ser derrubada pelo pooler.
        with self.conectar() as conexao:
            contas = listar_contas_historico(conexao, empresa_id)
            if not contas:
                return None
            registrar_inicio(conexao, empresa_id, execucao_id, TIPO_HISTORICA)
            planejar_contas(conexao, empresa_id, execucao_id, contas, self.relogio())
        status = self.carregar_contas(empresa_id, execucao_id, contas, contagens)
        return self.encerrar_execucao(empresa_id, execucao_id, status, contagens)

    def encerrar_execucao(
        self,
        empresa_id: UUID,
        execucao_id: UUID,
        status: StatusExecucao,
        contagens: Counter[str],
    ) -> StatusExecucao:
        """Registra o fim, numa transação própria, com as linhas das etapas
        confirmadas (RF-20)."""
        with self.conectar() as conexao:
            try:
                registrar_fim(
                    conexao, empresa_id, execucao_id, status, contagens=dict(contagens)
                )
            except (psycopg.Error, ErroRegistroExecucao) as erro:
                raise ErroRegistroFim from erro
        registrar_evento(status, linhas=sum(contagens.values()))
        return status

    def carregar_cadastros(
        self,
        empresa_id: UUID,
        execucao_id: UUID,
        contas: Sequence[tuple[UUID, str]],
        contagens: Counter[str],
    ) -> StatusExecucao:
        """O cadastro completo de cada conta dada, cada um numa transação
        própria, até o prazo ou até um cadastro sem o lock, que encerram a
        execução como sucesso ou como ignorada (RF-19). A conta que fica de
        fora continua sem fuso para a execução seguinte.

        A falha no cadastro encerra só a conta dela: uma falha que se repete
        a cada execução, como a de uma conta sem permissão, não pode segurar
        as outras. A execução segue para a próxima conta e, no fim, falha com
        o primeiro erro.
        """
        primeiro_erro: Exception | None = None
        parada: StatusExecucao | None = None
        for conta_anuncio_id, id_meta in contas:
            if self.esgotou_prazo():
                parada = StatusExecucao.SUCESSO
                break
            try:
                carregadas = self.processar_cadastro(
                    empresa_id, execucao_id, conta_anuncio_id, id_meta
                )
            # Guardado e relançado depois das outras contas.
            except Exception as erro:  # noqa: BLE001
                primeiro_erro = primeiro_erro or erro
                continue
            if carregadas is None:
                parada = StatusExecucao.IGNORADA
                break
            contagens.update(carregadas)
        if primeiro_erro is not None:
            raise primeiro_erro
        return parada or StatusExecucao.SUCESSO

    def processar_cadastro(
        self, empresa_id: UUID, execucao_id: UUID, conta_anuncio_id: UUID, id_meta: str
    ) -> Contagens | None:
        """Extrai o cadastro completo da conta fora de transação e o carrega
        com o lock; sem o lock, None."""
        cadastro = extrair_cadastro_conta(self.cliente, id_meta, self.relogio)
        with self.conectar() as conexao:
            contagens = executar_com_lock(
                conexao,
                empresa_id,
                lambda conexao_carga: carregar_cadastro_inicial(
                    conexao_carga, empresa_id, execucao_id, conta_anuncio_id, cadastro
                ),
                espera_maxima_segundos=self.espera_maxima_segundos,
                intervalo_segundos=self.intervalo_segundos,
            )
        if contagens is not None:
            registrar_evento(
                "em_andamento", etapa="carregar", linhas=sum(contagens.values())
            )
        return contagens

    def carregar_contas(
        self,
        empresa_id: UUID,
        execucao_id: UUID,
        contas: Sequence[ContaHistorica],
        contagens: Counter[str],
    ) -> StatusExecucao:
        """As fatias não concluídas de cada conta, até o prazo ou até uma
        fatia sem o lock, que encerram a execução.

        A fatia que falha encerra só a conta dela: uma falha que se repete a
        cada execução não pode segurar as outras contas da empresa. A
        execução segue para a próxima conta e, no fim, falha com o primeiro
        erro.
        """
        primeiro_erro: Exception | None = None
        parada: StatusExecucao | None = None
        for conta in contas:
            try:
                parada = self.carregar_conta(empresa_id, execucao_id, conta, contagens)
            # Guardado e relançado depois das outras contas.
            except Exception as erro:  # noqa: BLE001
                primeiro_erro = primeiro_erro or erro
                continue
            if parada is not None:
                break
        if primeiro_erro is not None:
            raise primeiro_erro
        return parada or StatusExecucao.SUCESSO

    def carregar_conta(
        self,
        empresa_id: UUID,
        execucao_id: UUID,
        conta: ContaHistorica,
        contagens: Counter[str],
    ) -> StatusExecucao | None:
        """As fatias não concluídas da conta, na ordem dos meses. Devolve o
        status que encerra a execução: sucesso no prazo, que deixa as
        restantes para a execução seguinte, ou ignorada na fatia sem o lock,
        que fica pendente (RF-19); None quando a conta termina."""
        with self.conectar() as conexao:
            meses = listar_fatias_pendentes(conexao, empresa_id, conta.conta_anuncio_id)
        for mes in meses:
            if self.esgotou_prazo():
                return StatusExecucao.SUCESSO
            carregadas = self.processar_fatia(empresa_id, execucao_id, conta, mes)
            if carregadas is None:
                return StatusExecucao.IGNORADA
            contagens.update(carregadas)
        return None

    def processar_fatia(
        self, empresa_id: UUID, execucao_id: UUID, conta: ContaHistorica, mes: date
    ) -> Contagens | None:
        """Extrai a fatia fora de transação e a carrega com o lock; sem o
        lock, None. Na falha, marca a fatia, depois do rollback da carga, e
        propaga o erro."""
        try:
            fatia = self.extrair_fatia(empresa_id, conta, mes)
            with self.conectar() as conexao:
                contagens = executar_com_lock(
                    conexao,
                    empresa_id,
                    lambda conexao_carga: carregar_fatia(
                        conexao_carga, empresa_id, execucao_id, fatia
                    ),
                    espera_maxima_segundos=self.espera_maxima_segundos,
                    intervalo_segundos=self.intervalo_segundos,
                )
        except Exception:
            marcar_falha_fatia(
                self.conectar, empresa_id, execucao_id, conta.conta_anuncio_id, mes
            )
            raise
        if contagens is not None:
            registrar_evento(
                "em_andamento", etapa="carregar", linhas=sum(contagens.values())
            )
        return contagens

    def extrair_fatia(
        self, empresa_id: UUID, conta: ContaHistorica, mes: date
    ) -> FatiaExtraida:
        """O mês da fatia cortado no limite de 37 meses e em ontem, no fuso da
        conta, calculados agora: a retomada pode vir dias depois do
        planejamento, com o limite adiante."""
        hoje = calcular_dia_conta(self.relogio(), conta.fuso_horario)
        limite, ontem = calcular_limite_historico(hoje), hoje - timedelta(days=1)
        with self.conectar() as conexao:
            intervalo = ler_intervalo_fatia(conexao, mes, limite, ontem)
            periodos = (
                ler_periodos_fatia(conexao, *intervalo, ontem) if intervalo else []
            )
        if intervalo is None:
            return FatiaExtraida(conta.conta_anuncio_id, mes, None)
        inicio, fim = intervalo
        janela = extrair_janela_conta(
            self.conectar,
            self.cliente,
            empresa_id,
            conta.conta_anuncio_id,
            conta.id_meta,
            inicio,
            fim,
            periodos,
        )
        return FatiaExtraida(conta.conta_anuncio_id, mes, janela)


def calcular_dia_conta(instante: datetime, fuso_horario: str) -> date:
    """O dia do instante no fuso da conta, em que a Meta entrega os dados
    (R-17)."""
    return instante.astimezone(ZoneInfo(fuso_horario)).date()


def calcular_limite_historico(hoje: date) -> date:
    """O primeiro dia da carga histórica: hoje menos 37 meses, no mesmo dia
    do mês (R-19).

    Não verificamos em que fuso a Meta conta o hoje, que pode já ter virado
    no dela, nem o que ela faz com o dia que não existe no mês do limite.
    Vale o limite mais tardio entre hoje e os dias de margem seguintes, com
    o dia contado a partir do dia 1 do mês do limite, o que leva para o mês
    seguinte o dia que não existe nele: o since nunca fica antes do aceito,
    ao custo de até três dias do mês mais antigo.
    """
    return max(
        recuar_meses(hoje + timedelta(days=dias), HISTORICO_MAXIMO_MESES)
        for dias in range(MARGEM_LIMITE_HISTORICO_DIAS + 1)
    )


def recuar_meses(dia: date, meses: int) -> date:
    """O mesmo dia, meses antes, contado a partir do dia 1 daquele mês."""
    ano, indice_mes = divmod(
        dia.year * MESES_POR_ANO + dia.month - 1 - meses, MESES_POR_ANO
    )
    return date(ano, indice_mes + 1, 1) + timedelta(days=dia.day - 1)


def planejar_contas(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    contas: Sequence[ContaHistorica],
    instante: datetime,
) -> None:
    """Planeja, numa transação, as fatias das contas que ainda não têm
    nenhuma, cada uma no dia do próprio fuso."""
    with conexao.transaction():
        for conta in contas:
            planejar_fatias(
                conexao,
                empresa_id,
                execucao_id,
                conta.conta_anuncio_id,
                calcular_dia_conta(instante, conta.fuso_horario),
            )


def listar_contas_sem_cadastro(
    conexao: psycopg.Connection, empresa_id: UUID
) -> list[tuple[UUID, str]]:
    """O id interno e o ID da Meta de cada conta ativa ainda sem o cadastro
    completo, na ordem do ID da Meta."""
    return conexao.execute(
        LISTAR_CONTAS_SEM_CADASTRO, {"empresa_id": empresa_id}
    ).fetchall()


def listar_contas_historico(
    conexao: psycopg.Connection, empresa_id: UUID
) -> list[ContaHistorica]:
    return [
        ContaHistorica(conta_anuncio_id, id_meta, fuso_horario)
        for conta_anuncio_id, id_meta, fuso_horario in conexao.execute(
            LISTAR_CONTAS_HISTORICO, {"empresa_id": empresa_id}
        ).fetchall()
    ]


def planejar_fatias(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta_anuncio_id: UUID,
    hoje: date,
) -> int:
    """Na conta que ainda não tem fatias, uma pendente por mês do limite de
    37 meses até ontem (RF-22), e quantas entraram. Os meses vêm do
    calendário, a única fonte do agrupamento (CLAUDE.md §5)."""
    limite, ontem = calcular_limite_historico(hoje), hoje - timedelta(days=1)
    conferir_calendario(conexao, limite, ontem)
    return conexao.execute(
        PLANEJAR_FATIAS,
        {
            "empresa_id": empresa_id,
            "conta_anuncio_id": conta_anuncio_id,
            "execucao_id": execucao_id,
            "limite": limite,
            "ontem": ontem,
        },
    ).rowcount


def listar_fatias_pendentes(
    conexao: psycopg.Connection, empresa_id: UUID, conta_anuncio_id: UUID
) -> list[date]:
    return [
        mes
        for (mes,) in conexao.execute(
            LISTAR_FATIAS_PENDENTES,
            {"empresa_id": empresa_id, "conta_anuncio_id": conta_anuncio_id},
        ).fetchall()
    ]


def ler_intervalo_fatia(
    conexao: psycopg.Connection, mes: date, limite: date, ontem: date
) -> tuple[date, date] | None:
    inicio, fim = conexao.execute(
        LER_INTERVALO_FATIA, {"mes": mes, "limite": limite, "ontem": ontem}
    ).fetchone()
    return None if inicio is None else (inicio, fim)


def ler_periodos_fatia(
    conexao: psycopg.Connection, inicio: date, fim: date, ontem: date
) -> list[PeriodoAlcance]:
    """As consultas de alcance da fatia, na ordem: as semanas, o mês e o
    ano, cada uma do since ao until."""
    return [
        PeriodoAlcance(TipoPeriodo(tipo), inicio_periodo, fim_periodo)
        for tipo, inicio_periodo, fim_periodo, _ in conexao.execute(
            LER_PERIODOS_FATIA, {"inicio": inicio, "fim": fim, "ontem": ontem}
        ).fetchall()
    ]


def carregar_fatia(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    fatia: FatiaExtraida,
) -> Contagens:
    """Na transação com o lock: a janela do mês, a conferência de que as
    linhas da fatia têm resposta bruta (RF-09) e a marca concluida, juntas,
    para que a fatia interrompida nunca apareça como concluída (ADR-0009 §5).
    """
    janela = fatia.janela
    contagens = carregar_com_rastreio_etapa(
        conexao,
        empresa_id,
        execucao_id,
        lambda: (
            carregar_janela_conta(conexao, empresa_id, execucao_id, janela)
            if janela is not None
            else {}
        ),
    )
    parametros = {
        "empresa_id": empresa_id,
        "conta_anuncio_id": fatia.conta_anuncio_id,
        "mes": fatia.mes_referencia,
        "execucao_id": execucao_id,
    }
    if conexao.execute(CONCLUIR_FATIA, parametros).rowcount != 1:
        raise ErroFatiaAusente("fatia sem registro em fatia_historica")
    return contagens


def carregar_cadastro_inicial(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta_anuncio_id: UUID,
    cadastro: CadastroExtraido,
) -> Contagens:
    """Na transação com o lock: o cadastro completo da conta, com o fuso, e a
    conferência de que as linhas dele têm resposta bruta (RF-09). O cadastro
    interrompido não deixa nada, e a conta continua sem fuso."""
    return carregar_com_rastreio_etapa(
        conexao,
        empresa_id,
        execucao_id,
        lambda: carregar_cadastro_conta(
            conexao, empresa_id, execucao_id, conta_anuncio_id, cadastro
        ),
    )


def carregar_com_rastreio_etapa(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    carregar: Callable[[], Contagens],
) -> Contagens:
    """Roda uma etapa da execução na transação dela e confere que as linhas
    da etapa têm resposta bruta (RF-09). A contagem do bruto é a da etapa, e
    não a da execução inteira, que já tem as etapas confirmadas antes."""
    antes = contar_respostas_brutas(conexao, empresa_id, execucao_id)
    contagens = carregar()
    respostas = contar_respostas_brutas(conexao, empresa_id, execucao_id) - antes
    conferir_rastreio(contagens, respostas)
    return {**contagens, TABELA_BRUTO: respostas}


def marcar_falha_fatia(
    conectar: Callable[[], psycopg.Connection],
    empresa_id: UUID,
    execucao_id: UUID,
    conta_anuncio_id: UUID,
    mes: date,
) -> None:
    """Marca a fatia como falha numa transação própria, com conexão nova,
    porque a da carga pode ter caído com o erro. Sem a marca, a fatia segue
    pendente, e a retomada é a mesma; a linha de log registra o problema."""
    parametros = {
        "empresa_id": empresa_id,
        "conta_anuncio_id": conta_anuncio_id,
        "mes": mes,
        "execucao_id": execucao_id,
    }
    try:
        with conectar() as conexao, conexao.transaction():
            conexao.execute(MARCAR_FALHA_FATIA, parametros)
    except psycopg.Error:
        registrar_evento("em_andamento", nivel=logging.ERROR)


def executar_carga_historica(ambiente: Ambiente) -> int:
    """A carga histórica de cada empresa ativa, em sequência, até o prazo da
    execução, e o código de saída do job (RF-50)."""
    prazo = time.monotonic() + DURACAO_MAXIMA_HISTORICA_SEGUNDOS

    def conectar() -> psycopg.Connection:
        return conectar_banco(ambiente.url_banco)

    with conectar() as conexao:
        empresas = listar_empresas_ativas(conexao)
    carga = CargaHistorica(
        conectar, ClienteApiMeta(ambiente.token_sistema_meta), prazo=prazo
    )
    return carga.executar(empresas)


def main() -> int:
    configurar_log()
    try:
        return executar_carga_historica(carregar_ambiente(os.environ))
    except ErroConfiguracao as erro:
        # A mensagem cita só o nome das variáveis.
        print(erro, file=sys.stderr)
    # O erro fora do laço por empresa não tem execução nem empresa, então não
    # cabe no log estruturado. O traceback traria a mensagem do erro, que numa
    # falha de conexão cita o host e o usuário, ao log público (RNF-17). A
    # interrupção (SIGINT) entra junto: o traceback dela traria o erro que
    # estava sendo tratado quando ela chegou.
    except (Exception, KeyboardInterrupt) as erro:  # noqa: BLE001
        print(f"Carga histórica interrompida: {type(erro).__name__}", file=sys.stderr)
    return CODIGO_SAIDA_FALHA


if __name__ == "__main__":
    sys.exit(main())
