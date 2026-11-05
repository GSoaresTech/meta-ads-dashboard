"""Quebras diárias por campanha de cada conta ativa da empresa, nas
combinações idade+gênero, plataforma+posicionamento e região, como tarefa da
execução por empresa (RF-03; ADR-0011; etl.execucao.TarefaCarga).

A extração lê as contas ativas no banco e, fora de transação, as três
quebras de cada uma no intervalo e, pelo ID, as campanhas delas que ainda
não estão no banco. A carga, já na transação da empresa, grava as respostas
em bruto, carrega essas campanhas, resolve o resultado principal de cada
campanha, transforma e substitui as quebras da conta no intervalo, nessa
ordem (RF-09, RF-17; ADR-0009 §5).

Roda depois da tarefa dos insights diários da mesma janela: a resolução do
resultado usa os conjuntos e o investimento que ela carrega. A campanha que
só esta tarefa lê pelo ID entra sem conjuntos e resolve pela regra de
"qualquer" do objetivo até a próxima recarga (ADR-0011).
"""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import psycopg

from etl.cadastro import listar_contas_ativas
from etl.carga import (
    Contagens,
    carregar_quebras_campanha,
    ler_ids_campanhas,
    ler_tipos_acao_resultado,
)
from etl.cliente_api_meta import ClienteApiMeta
from etl.extracao import (
    Consulta,
    EntidadesExtraidas,
    TipoQuebra,
    extrair_campanhas_por_id,
    extrair_quebras_campanha,
    listar_ids_insights,
)
from etl.insights import carregar_bruto_e_entidades
from etl.transformacao import QuebrasCampanha, transformar_quebras_campanha


@dataclass(frozen=True)
class QuebrasContaExtraidas:
    conta_anuncio_id: UUID
    consultas: Mapping[TipoQuebra, Consulta]
    entidades: EntidadesExtraidas


@dataclass(frozen=True)
class TarefaQuebrasCampanha:
    """As quebras de inicio a fim, inclusive, nas datas do fuso de cada
    conta, como a API as entrega (R-17)."""

    conectar: Callable[[], psycopg.Connection]
    cliente: ClienteApiMeta
    inicio: date
    fim: date

    def extrair(self, empresa_id: UUID) -> list[QuebrasContaExtraidas]:
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
    ) -> QuebrasContaExtraidas:
        """As três quebras da conta e, pelo ID, as campanhas delas que o
        banco ainda não tem."""
        consultas = extrair_quebras_campanha(
            self.cliente, id_meta_conta, self.inicio, self.fim
        )
        ids_meta = [
            id_meta
            for consulta in consultas.values()
            for id_meta in listar_ids_insights(consulta.paginas, "campaign_id")
        ]
        return QuebrasContaExtraidas(
            conta_anuncio_id,
            consultas,
            extrair_campanhas_ausentes(
                self.conectar, self.cliente, empresa_id, list(dict.fromkeys(ids_meta))
            ),
        )

    def carregar(
        self,
        conexao: psycopg.Connection,
        empresa_id: UUID,
        execucao_id: UUID,
        dados: Sequence[QuebrasContaExtraidas],
    ) -> Contagens:
        contagens: Counter[str] = Counter()
        for conta in dados:
            contagens.update(
                carregar_quebras_conta(
                    conexao, empresa_id, execucao_id, self.inicio, self.fim, conta
                )
            )
        return dict(contagens)


def extrair_campanhas_ausentes(
    conectar: Callable[[], psycopg.Connection],
    cliente: ClienteApiMeta,
    empresa_id: UUID,
    ids_meta: Sequence[str],
) -> EntidadesExtraidas:
    """Lê pelo ID as campanhas dadas que o banco ainda não tem. Uma campanha
    carregada entre esta leitura e a carga é só atualizada pelo upsert."""
    with conectar() as conexao:
        existentes = ler_ids_campanhas(conexao, empresa_id, ids_meta)
    ausentes = [id_meta for id_meta in ids_meta if id_meta not in existentes]
    return extrair_campanhas_por_id(cliente, ausentes)


def carregar_quebras_conta(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    inicio: date,
    fim: date,
    conta: QuebrasContaExtraidas,
) -> Contagens:
    """Grava as respostas em bruto e carrega as campanhas lidas pelo ID antes
    de resolver o resultado principal, que depende delas; depois, substitui
    as três quebras da conta de uma vez, num só DELETE da janela."""
    contagens = carregar_bruto_e_entidades(
        conexao,
        empresa_id,
        execucao_id,
        conta.conta_anuncio_id,
        fim,
        list(conta.consultas.values()),
        conta.entidades,
    )
    tipos_acao = ler_tipos_acao_resultado(conexao, empresa_id, conta.conta_anuncio_id)
    por_tipo = [
        transformar_quebras_campanha(consulta.paginas, tipo, tipos_acao)
        for tipo, consulta in conta.consultas.items()
    ]
    quebras = QuebrasCampanha(
        quebras=[linha for quebra in por_tipo for linha in quebra.quebras],
        acoes=[acao for quebra in por_tipo for acao in quebra.acoes],
    )
    return contagens | carregar_quebras_campanha(
        conexao,
        empresa_id,
        execucao_id,
        conta.conta_anuncio_id,
        inicio,
        fim,
        quebras,
    )
