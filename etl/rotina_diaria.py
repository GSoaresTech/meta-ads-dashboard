"""Rotina diária: o reprocessamento dos 28 dias anteriores e as tarefas pesadas
da cadência diária de cada conta ativa, como uma execução por empresa, e o
ponto de entrada dela, `python -m etl.rotina_diaria` (RF-05; ADR-0005;
ADR-0009 §5; etl.execucao.TarefaCarga).

Só orquestra as extrações e as cargas do cadastro e da janela da conta, com
os insights diários, as quebras e o alcance (etl.janela_conta). A extração de
cada conta começa pelo cadastro, que dá o dia no fuso dela, e a janela sai
desse dia: as contas de uma empresa podem estar em fusos diferentes. Depois
lê a janela e, pelo ID, só o que nem o cadastro nem o banco têm.

A carga roda na transação da empresa, conta a conta: o cadastro, os insights,
as quebras, que resolvem o resultado principal pelo que os insights acabaram
de carregar (ADR-0011), e o alcance. Uma falha em qualquer etapa desfaz a
empresa inteira (RF-18). A retenção de bruto vem da execução, pelo tipo.
"""

import os
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from uuid import UUID

import psycopg

from etl.alcance import ler_periodos_janela
from etl.cadastro import (
    carregar_cadastro_conta,
    listar_contas_ativas,
    listar_empresas_ativas,
)
from etl.carga import Contagens, conectar_banco
from etl.cliente_api_meta import ClienteApiMeta
from etl.configuracao import (
    JANELA_REPROCESSAMENTO_DIAS,
    Ambiente,
    ErroConfiguracao,
    carregar_ambiente,
)
from etl.execucao import CODIGO_SAIDA_FALHA, TIPO_COM_RETENCAO, executar_empresas
from etl.extracao import CadastroExtraido, agora_utc, extrair_cadastro_conta
from etl.janela_conta import (
    JanelaContaExtraida,
    carregar_janela_conta,
    extrair_janela_conta,
)
from etl.log_estruturado import configurar_log


@dataclass(frozen=True)
class RotinaContaExtraida:
    """Tudo o que a rotina leu de uma conta: o cadastro e a janela dele."""

    cadastro: CadastroExtraido
    janela: JanelaContaExtraida


@dataclass(frozen=True)
class TarefaRotinaDiaria:
    conectar: Callable[[], psycopg.Connection]
    cliente: ClienteApiMeta
    relogio: Callable[[], datetime] = field(default=agora_utc)

    def extrair(self, empresa_id: UUID) -> list[RotinaContaExtraida]:
        # Conexões só para as leituras: a extração pode levar muito tempo, e
        # a conexão parada poderia ser derrubada pelo pooler.
        with self.conectar() as conexao:
            contas = listar_contas_ativas(conexao, empresa_id)
        return [
            self.extrair_conta(empresa_id, conta_anuncio_id, id_meta)
            for conta_anuncio_id, id_meta in contas
        ]

    def extrair_conta(
        self, empresa_id: UUID, conta_anuncio_id: UUID, id_meta_conta: str
    ) -> RotinaContaExtraida:
        """O cadastro, que dá a janela da conta, e a janela, que lê pelo ID
        só o que nem o cadastro nem o banco têm."""
        cadastro = extrair_cadastro_conta(self.cliente, id_meta_conta, self.relogio)
        inicio, fim = calcular_janela_reprocessamento(cadastro.data_referencia)
        with self.conectar() as conexao:
            periodos = ler_periodos_janela(conexao, inicio, fim)
        return RotinaContaExtraida(
            cadastro,
            extrair_janela_conta(
                self.conectar,
                self.cliente,
                empresa_id,
                conta_anuncio_id,
                id_meta_conta,
                inicio,
                fim,
                periodos,
                cadastro,
            ),
        )

    def carregar(
        self,
        conexao: psycopg.Connection,
        empresa_id: UUID,
        execucao_id: UUID,
        dados: Sequence[RotinaContaExtraida],
    ) -> Contagens:
        contagens: Counter[str] = Counter()
        for conta in dados:
            contagens.update(
                carregar_rotina_conta(conexao, empresa_id, execucao_id, conta)
            )
        return dict(contagens)


def calcular_janela_reprocessamento(hoje: date) -> tuple[date, date]:
    """Os 28 dias anteriores a hoje, inclusive os dois extremos. Hoje fica de
    fora: é da execução horária, e o dia ainda não fechou (ADR-0005)."""
    return hoje - timedelta(days=JANELA_REPROCESSAMENTO_DIAS), hoje - timedelta(days=1)


def carregar_rotina_conta(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta: RotinaContaExtraida,
) -> Contagens:
    """Carrega o cadastro antes da janela: as entidades vêm antes dos fatos,
    pela FK."""
    contagens = Counter(
        carregar_cadastro_conta(
            conexao,
            empresa_id,
            execucao_id,
            conta.janela.conta_anuncio_id,
            conta.cadastro,
        )
    )
    contagens.update(
        carregar_janela_conta(conexao, empresa_id, execucao_id, conta.janela)
    )
    return dict(contagens)


def executar_rotina(ambiente: Ambiente) -> int:
    """A rotina de cada empresa ativa, em sequência, e o código de saída do
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
