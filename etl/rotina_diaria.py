"""Rotina diária: o reprocessamento dos 28 dias anteriores e as tarefas pesadas
da cadência diária de cada conta ativa, como uma execução por empresa, e o
ponto de entrada dela, `python -m etl.rotina_diaria` (RF-05; ADR-0005;
ADR-0009 §5; etl.execucao.TarefaCarga).

Só orquestra as extrações e as cargas do cadastro, dos insights diários, das
quebras e do alcance. A extração de cada conta começa pelo cadastro, que dá o
dia no fuso dela, e a janela sai desse dia: as contas de uma empresa podem
estar em fusos diferentes. Depois lê a janela e, pelo ID, só o que nem o
cadastro nem o banco têm. O cadastro lido ainda não foi carregado, e numa conta
nova a conferência só com o banco leria pelo ID cada anúncio com entrega no
ano.

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

from etl.alcance import (
    AlcanceContaExtraido,
    carregar_alcance_conta,
    ler_periodos_janela,
)
from etl.cadastro import (
    carregar_cadastro_conta,
    listar_contas_ativas,
    listar_empresas_ativas,
)
from etl.carga import Contagens, conectar_banco
from etl.cliente_api_meta import ClienteApiMeta, Endpoint
from etl.configuracao import (
    JANELA_REPROCESSAMENTO_DIAS,
    Ambiente,
    ErroConfiguracao,
    carregar_ambiente,
)
from etl.execucao import CODIGO_SAIDA_FALHA, TIPO_COM_RETENCAO, executar_empresas
from etl.extracao import (
    CadastroExtraido,
    Consulta,
    NivelAlcance,
    agora_utc,
    extrair_alcance_periodo,
    extrair_cadastro_conta,
    extrair_entidades_por_id,
    extrair_insights_diarios,
    extrair_quebras_campanha,
    listar_anuncios_insights,
    listar_ids_insights,
)
from etl.insights import (
    InsightsContaExtraidos,
    carregar_insights_conta,
    extrair_anuncios_ausentes,
)
from etl.log_estruturado import configurar_log
from etl.quebras import (
    QuebrasContaExtraidas,
    carregar_quebras_conta,
    extrair_campanhas_ausentes,
)


@dataclass(frozen=True)
class RotinaContaExtraida:
    """Tudo o que a rotina leu de uma conta, com a janela dela."""

    conta_anuncio_id: UUID
    inicio: date
    fim: date
    cadastro: CadastroExtraido
    insights: InsightsContaExtraidos
    quebras: QuebrasContaExtraidas
    alcance: AlcanceContaExtraido


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
        """O cadastro e a janela da conta, a janela de cada consulta e, pelo
        ID, as entidades delas que o cadastro e o banco não têm. Os anúncios
        lidos pelo ID entram com os insights, antes do alcance, que também
        depende deles pela FK."""
        cadastro = extrair_cadastro_conta(self.cliente, id_meta_conta, self.relogio)
        inicio, fim = calcular_janela_reprocessamento(cadastro.data_referencia)
        insights = extrair_insights_diarios(self.cliente, id_meta_conta, inicio, fim)
        quebras = extrair_quebras_campanha(self.cliente, id_meta_conta, inicio, fim)
        with self.conectar() as conexao:
            periodos = ler_periodos_janela(conexao, inicio, fim)
        alcance = {
            periodo: extrair_alcance_periodo(self.cliente, id_meta_conta, periodo)
            for periodo in periodos
        }
        anuncios = listar_anuncios_insights(
            [
                *insights.paginas,
                *(
                    pagina
                    for por_nivel in alcance.values()
                    for pagina in por_nivel[NivelAlcance.ANUNCIO].paginas
                ),
            ]
        )
        campanhas = listar_ids_insights(
            [pagina for consulta in quebras.values() for pagina in consulta.paginas],
            "campaign_id",
        )
        return RotinaContaExtraida(
            conta_anuncio_id,
            inicio,
            fim,
            cadastro,
            InsightsContaExtraidos(
                conta_anuncio_id,
                insights,
                extrair_anuncios_ausentes(
                    self.conectar,
                    self.cliente,
                    empresa_id,
                    retirar_cadastrados(anuncios, cadastro.arestas[Endpoint.ANUNCIOS]),
                ),
            ),
            QuebrasContaExtraidas(
                conta_anuncio_id,
                quebras,
                extrair_campanhas_ausentes(
                    self.conectar,
                    self.cliente,
                    empresa_id,
                    retirar_cadastrados(
                        campanhas, cadastro.arestas[Endpoint.CAMPANHAS]
                    ),
                ),
            ),
            AlcanceContaExtraido(
                conta_anuncio_id, alcance, extrair_entidades_por_id(self.cliente, [])
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


def retirar_cadastrados(ids_meta: Sequence[str], aresta: Consulta) -> list[str]:
    """Os IDs dados que a aresta do cadastro não trouxe, na ordem."""
    cadastrados = set(listar_ids_insights(aresta.paginas, "id"))
    return [id_meta for id_meta in ids_meta if id_meta not in cadastrados]


def carregar_rotina_conta(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta: RotinaContaExtraida,
) -> Contagens:
    """Carrega a conta nas etapas da rotina, na ordem que cada uma exige: as
    entidades antes dos fatos, pela FK, e os insights antes das quebras
    (ADR-0011)."""
    contagens = Counter(
        carregar_cadastro_conta(
            conexao, empresa_id, execucao_id, conta.conta_anuncio_id, conta.cadastro
        )
    )
    contagens.update(
        carregar_insights_conta(
            conexao, empresa_id, execucao_id, conta.inicio, conta.fim, conta.insights
        )
    )
    contagens.update(
        carregar_quebras_conta(
            conexao, empresa_id, execucao_id, conta.inicio, conta.fim, conta.quebras
        )
    )
    contagens.update(
        carregar_alcance_conta(
            conexao, empresa_id, execucao_id, conta.fim, conta.alcance
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
