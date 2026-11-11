"""Revisão diária leve: o reprocessamento dos 28 dias anteriores de cada conta
ativa que já teve a carga inicial, como uma execução por empresa, e o ponto de
entrada dela, `python -m etl.rotina_diaria` (RF-05; ADR-0009 §5; ADR-0017;
etl.execucao.TarefaCarga).

Só orquestra a extração e a carga da janela de cada conta, com os insights
diários, as quebras e o alcance da semana, do mês e do ano que contêm ontem
(etl.janela_conta). Depois de uma revisão que falhou, o alcance retoma do dia
seguinte ao último já extraído, para que nenhum período encerrado fique
cortado. Não lê o cadastro completo, que é da carga inicial: das entidades,
lê pelo ID só as que os insights e o alcance trazem e o banco não tem. A janela sai do dia no fuso que a carga inicial gravou, porque as contas
de uma empresa podem estar em fusos diferentes; a conta ainda sem fuso espera
a carga inicial.

A carga roda na transação da empresa, conta a conta: os insights, as quebras,
que resolvem o resultado principal pelo que os insights acabaram de carregar
(ADR-0011), e o alcance. Uma falha em qualquer etapa desfaz a empresa inteira
(RF-18). A retenção de bruto vem da execução, pelo tipo.
"""

import os
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Final
from uuid import UUID

import psycopg

from etl.alcance import ler_periodos_janela
from etl.cadastro import listar_empresas_ativas
from etl.carga import Contagens, conectar_banco
from etl.carga_historica import calcular_dia_conta
from etl.cliente_api_meta import ClienteApiMeta
from etl.configuracao import (
    JANELA_REPROCESSAMENTO_DIAS,
    Ambiente,
    ErroConfiguracao,
    carregar_ambiente,
)
from etl.execucao import CODIGO_SAIDA_FALHA, TIPO_COM_RETENCAO, executar_empresas
from etl.extracao import agora_utc
from etl.janela_conta import (
    JanelaContaExtraida,
    carregar_janela_conta,
    extrair_janela_conta,
)
from etl.log_estruturado import configurar_log

# A conta ativa que já teve a carga inicial: o fuso vem do cadastro completo.
LISTAR_CONTAS_REVISAO: Final = """
SELECT id, id_meta, fuso_horario FROM normalizado.conta_anuncio
WHERE empresa_id = %s AND situacao = 'ativa' AND fuso_horario IS NOT NULL
ORDER BY id_meta
"""

# As linhas da própria conta, sem as de campanha e de anúncio, vão até o
# último dia extraído em cada período com entrega (ADR-0006).
LER_ULTIMO_DIA_ALCANCE: Final = """
SELECT max(fim_periodo) FROM normalizado.alcance_periodo
WHERE empresa_id = %s AND conta_anuncio_id = %s
"""


@dataclass(frozen=True)
class TarefaRotinaDiaria:
    conectar: Callable[[], psycopg.Connection]
    cliente: ClienteApiMeta
    relogio: Callable[[], datetime] = field(default=agora_utc)

    def extrair(self, empresa_id: UUID) -> list[JanelaContaExtraida]:
        # Conexões só para as leituras: a extração pode levar muito tempo, e
        # a conexão parada poderia ser derrubada pelo pooler.
        with self.conectar() as conexao:
            contas = listar_contas_revisao(conexao, empresa_id)
        return [
            self.extrair_conta(empresa_id, conta_anuncio_id, id_meta, fuso_horario)
            for conta_anuncio_id, id_meta, fuso_horario in contas
        ]

    def extrair_conta(
        self,
        empresa_id: UUID,
        conta_anuncio_id: UUID,
        id_meta_conta: str,
        fuso_horario: str,
    ) -> JanelaContaExtraida:
        """A janela dos 28 dias anteriores a hoje, no fuso da conta, com o
        alcance dos períodos que contêm os dias de calcular_inicio_alcance
        até ontem, o último dia da janela, cada um a partir do primeiro dia
        (ADR-0006; ADR-0017)."""
        hoje = calcular_dia_conta(self.relogio(), fuso_horario)
        inicio, fim = calcular_janela_reprocessamento(hoje)
        with self.conectar() as conexao:
            ultimo_dia = conexao.execute(
                LER_ULTIMO_DIA_ALCANCE, (empresa_id, conta_anuncio_id)
            ).fetchone()[0]
            periodos = ler_periodos_janela(
                conexao, calcular_inicio_alcance(inicio, fim, ultimo_dia), fim
            )
        return extrair_janela_conta(
            self.conectar,
            self.cliente,
            empresa_id,
            conta_anuncio_id,
            id_meta_conta,
            inicio,
            fim,
            periodos,
        )

    def carregar(
        self,
        conexao: psycopg.Connection,
        empresa_id: UUID,
        execucao_id: UUID,
        dados: Sequence[JanelaContaExtraida],
    ) -> Contagens:
        contagens: Counter[str] = Counter()
        for janela in dados:
            contagens.update(
                carregar_janela_conta(conexao, empresa_id, execucao_id, janela)
            )
        return dict(contagens)


def calcular_inicio_alcance(inicio: date, fim: date, ultimo_dia: date | None) -> date:
    """O primeiro dia cujos períodos a revisão relê: o seguinte ao último dia
    de alcance já extraído, limitado à janela de inicio a fim (ADR-0017).

    No dia normal, a revisão anterior extraiu até anteontem, e o resultado é
    ontem: só a semana, o mês e o ano dele. Depois de uma revisão que falhou,
    ele fica para trás, e a seguinte relê também os períodos dos dias
    perdidos, como o mês que terminou no dia da falha. Sem alcance extraído,
    como na conta sem entrega, vale o início da janela.
    """
    if ultimo_dia is None:
        return inicio
    return min(fim, max(inicio, ultimo_dia + timedelta(days=1)))


def listar_contas_revisao(
    conexao: psycopg.Connection, empresa_id: UUID
) -> list[tuple[UUID, str, str]]:
    """O id interno, o ID da Meta e o fuso de cada conta ativa que já teve a
    carga inicial."""
    return conexao.execute(LISTAR_CONTAS_REVISAO, (empresa_id,)).fetchall()


def calcular_janela_reprocessamento(hoje: date) -> tuple[date, date]:
    """Os 28 dias anteriores a hoje, inclusive os dois extremos. Hoje fica de
    fora: é da execução horária, e o dia ainda não fechou (ADR-0005)."""
    return hoje - timedelta(days=JANELA_REPROCESSAMENTO_DIAS), hoje - timedelta(days=1)


def executar_rotina(ambiente: Ambiente) -> int:
    """A revisão de cada empresa ativa, em sequência, e o código de saída do
    job (RF-50)."""

    def conectar() -> psycopg.Connection:
        return conectar_banco(ambiente.url_banco)

    with conectar() as conexao:
        empresas = listar_empresas_ativas(conexao)
    tarefa = TarefaRotinaDiaria(conectar, ClienteApiMeta(ambiente.token_sistema_meta))
    return executar_empresas(conectar, empresas, TIPO_COM_RETENCAO, tarefa)


def main() -> int:
    configurar_log()
    try:
        return executar_rotina(carregar_ambiente(os.environ))
    except ErroConfiguracao as erro:
        # A mensagem cita só o nome das variáveis.
        print(erro, file=sys.stderr)
    # O erro fora do laço por empresa não tem execução nem empresa, então não
    # cabe no log estruturado. O traceback traria a mensagem do erro, que numa
    # falha de conexão cita o host e o usuário, ao log público (RNF-17). A
    # interrupção (SIGINT) entra junto: o traceback dela traria o erro que
    # estava sendo tratado quando ela chegou.
    except (Exception, KeyboardInterrupt) as erro:  # noqa: BLE001
        print(f"Rotina diária interrompida: {type(erro).__name__}", file=sys.stderr)
    return CODIGO_SAIDA_FALHA


if __name__ == "__main__":
    sys.exit(main())
