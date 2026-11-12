"""Rotina horária: hoje e ontem de cada conta ativa que já teve a carga
inicial, como uma execução por empresa, e o ponto de entrada dela,
`python -m etl.rotina_horaria` (RF-06; ADR-0017; etl.execucao.TarefaCarga).

É a única carga recorrente que lê o dia corrente. Lê os insights diários por
anúncio com as ações e as quebras por campanha dos dois dias, no fuso que a
carga inicial gravou, e relê pelo ID todos os anúncios com entrega neles, com
o criativo, o conjunto e a campanha de cada um, mesmo os que o banco já tem:
assim, nomes, status e metas de otimização ficam atualizados sem o cadastro
completo. Não lê o cadastro completo nem o alcance por período, que ficam com
a carga inicial e com a revisão diária. A conta ainda sem fuso espera a carga
inicial.

A carga roda na transação da empresa, conta a conta: os insights e, depois
deles, as quebras, que resolvem o resultado principal pelo que os insights
acabaram de carregar (ADR-0011). Uma falha em qualquer etapa desfaz a empresa
inteira (RF-18). A horária não aplica a retenção de bruto, que é da revisão
diária.
"""

import os
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Final
from uuid import UUID

import psycopg

from etl.cadastro import listar_empresas_ativas
from etl.carga import Contagens, conectar_banco
from etl.carga_historica import calcular_dia_conta
from etl.cliente_api_meta import ClienteApiMeta
from etl.configuracao import Ambiente, ErroConfiguracao, carregar_ambiente
from etl.execucao import CODIGO_SAIDA_FALHA, executar_empresas
from etl.extracao import (
    Consulta,
    EntidadesExtraidas,
    TipoQuebra,
    agora_utc,
    extrair_campanhas_por_id,
    extrair_entidades_por_id,
    extrair_insights_diarios,
    extrair_quebras_campanha,
    listar_anuncios_insights,
    listar_ids_insights,
    listar_referencias,
)
from etl.insights import InsightsContaExtraidos, carregar_insights_conta
from etl.log_estruturado import configurar_log
from etl.quebras import QuebrasContaExtraidas, carregar_quebras_conta
from etl.rotina_diaria import listar_contas_revisao

TIPO_HORARIA: Final = "horaria"


@dataclass(frozen=True)
class JanelaHorariaExtraida:
    """O que uma conta teve lido de ontem a hoje, inclusive."""

    conta_anuncio_id: UUID
    inicio: date
    fim: date
    insights: InsightsContaExtraidos
    quebras: QuebrasContaExtraidas


@dataclass(frozen=True)
class TarefaRotinaHoraria:
    conectar: Callable[[], psycopg.Connection]
    cliente: ClienteApiMeta
    relogio: Callable[[], datetime] = field(default=agora_utc)

    def extrair(self, empresa_id: UUID) -> list[JanelaHorariaExtraida]:
        # Conexão só para a leitura das contas: a extração faz o I/O de rede,
        # e a conexão parada poderia ser derrubada pelo pooler.
        with self.conectar() as conexao:
            contas = listar_contas_revisao(conexao, empresa_id)
        return [
            self.extrair_conta(conta_anuncio_id, id_meta, fuso_horario)
            for conta_anuncio_id, id_meta, fuso_horario in contas
        ]

    def extrair_conta(
        self, conta_anuncio_id: UUID, id_meta_conta: str, fuso_horario: str
    ) -> JanelaHorariaExtraida:
        """Os insights e as quebras de ontem e hoje, no fuso da conta, e,
        pelo ID, as entidades com entrega neles."""
        inicio, fim = calcular_janela_horaria(
            calcular_dia_conta(self.relogio(), fuso_horario)
        )
        insights = extrair_insights_diarios(self.cliente, id_meta_conta, inicio, fim)
        quebras = extrair_quebras_campanha(self.cliente, id_meta_conta, inicio, fim)
        entidades = extrair_entidades_por_id(
            self.cliente, listar_anuncios_insights(insights.paginas)
        )
        return JanelaHorariaExtraida(
            conta_anuncio_id,
            inicio,
            fim,
            InsightsContaExtraidos(conta_anuncio_id, insights, entidades),
            QuebrasContaExtraidas(
                conta_anuncio_id,
                quebras,
                extrair_campanhas_por_id(
                    self.cliente, listar_campanhas_sem_anuncio(quebras, entidades)
                ),
            ),
        )

    def carregar(
        self,
        conexao: psycopg.Connection,
        empresa_id: UUID,
        execucao_id: UUID,
        dados: Sequence[JanelaHorariaExtraida],
    ) -> Contagens:
        contagens: Counter[str] = Counter()
        for janela in dados:
            contagens.update(
                carregar_janela_horaria(conexao, empresa_id, execucao_id, janela)
            )
        return dict(contagens)


def calcular_janela_horaria(hoje: date) -> tuple[date, date]:
    """Ontem e hoje, inclusive os dois extremos (RF-06)."""
    return hoje - timedelta(days=1), hoje


def listar_campanhas_sem_anuncio(
    quebras: Mapping[TipoQuebra, Consulta], entidades: EntidadesExtraidas
) -> list[str]:
    """As campanhas das quebras que a releitura dos anúncios não trouxe. Cada
    campanha com entrega costuma vir pelo anúncio dela, e esta lista costuma
    sair vazia; a que só aparece nas quebras é relida também, porque teve
    entrega."""
    lidas = set(listar_referencias(entidades.campanhas, "id"))
    ids_meta = [
        id_meta
        for consulta in quebras.values()
        for id_meta in listar_ids_insights(consulta.paginas, "campaign_id")
    ]
    return [id_meta for id_meta in dict.fromkeys(ids_meta) if id_meta not in lidas]


def carregar_janela_horaria(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    janela: JanelaHorariaExtraida,
) -> Contagens:
    """Carrega a janela na transação de quem chama, com os insights antes das
    quebras (ADR-0011)."""
    contagens = Counter(
        carregar_insights_conta(
            conexao, empresa_id, execucao_id, janela.inicio, janela.fim, janela.insights
        )
    )
    contagens.update(
        carregar_quebras_conta(
            conexao, empresa_id, execucao_id, janela.inicio, janela.fim, janela.quebras
        )
    )
    return dict(contagens)


def executar_rotina(ambiente: Ambiente) -> int:
    """A rotina de cada empresa ativa, em sequência, e o código de saída do
    job (RF-50)."""

    def conectar() -> psycopg.Connection:
        return conectar_banco(ambiente.url_banco)

    with conectar() as conexao:
        empresas = listar_empresas_ativas(conexao)
    tarefa = TarefaRotinaHoraria(conectar, ClienteApiMeta(ambiente.token_sistema_meta))
    return executar_empresas(conectar, empresas, TIPO_HORARIA, tarefa)


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
        print(f"Rotina horária interrompida: {type(erro).__name__}", file=sys.stderr)
    return CODIGO_SAIDA_FALHA


if __name__ == "__main__":
    sys.exit(main())
