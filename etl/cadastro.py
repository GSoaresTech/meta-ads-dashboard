"""Cadastro de entidades e criativos de cada conta ativa da empresa, como
tarefa da execução por empresa (RF-01, RF-43; etl.execucao.TarefaCarga).

A extração lê as contas ativas no banco e o cadastro de cada uma na API,
fora de transação. A carga, já na transação da empresa, grava as respostas
em bruto, transforma e carrega normalizado, nessa ordem (RF-09;
ADR-0009 §5).
"""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final
from uuid import UUID

import psycopg

from etl.carga import Contagens, carregar_cadastro, gravar_respostas_brutas
from etl.cliente_api_meta import ClienteApiMeta, Endpoint
from etl.extracao import CadastroExtraido, agora_utc, extrair_cadastro_conta
from etl.transformacao import transformar_cadastro

LISTAR_EMPRESAS_ATIVAS: Final = """
SELECT id FROM normalizado.empresa WHERE situacao = 'ativa' ORDER BY id
"""

LISTAR_CONTAS_ATIVAS: Final = """
SELECT id, id_meta FROM normalizado.conta_anuncio
WHERE empresa_id = %s AND situacao = 'ativa'
ORDER BY id_meta
"""


@dataclass(frozen=True)
class CadastroContaExtraido:
    conta_anuncio_id: UUID
    extraido: CadastroExtraido


@dataclass(frozen=True)
class TarefaCadastro:
    conectar: Callable[[], psycopg.Connection]
    cliente: ClienteApiMeta
    relogio: Callable[[], datetime] = field(default=agora_utc)

    def extrair(self, empresa_id: UUID) -> list[CadastroContaExtraido]:
        # Conexão só para a leitura: a extração pode levar muito tempo, e a
        # conexão parada poderia ser derrubada pelo pooler.
        with self.conectar() as conexao:
            contas = listar_contas_ativas(conexao, empresa_id)
        return [
            CadastroContaExtraido(
                conta_anuncio_id,
                extrair_cadastro_conta(self.cliente, id_meta, self.relogio),
            )
            for conta_anuncio_id, id_meta in contas
        ]

    def carregar(
        self,
        conexao: psycopg.Connection,
        empresa_id: UUID,
        execucao_id: UUID,
        dados: Sequence[CadastroContaExtraido],
    ) -> Contagens:
        contagens: Counter[str] = Counter()
        for conta in dados:
            contagens.update(
                carregar_cadastro_conta(
                    conexao,
                    empresa_id,
                    execucao_id,
                    conta.conta_anuncio_id,
                    conta.extraido,
                )
            )
        return dict(contagens)


def listar_empresas_ativas(conexao: psycopg.Connection) -> list[UUID]:
    """O id interno de cada empresa ativa. A inativa não entra nas execuções
    (RF-48)."""
    return [
        empresa_id
        for (empresa_id,) in conexao.execute(LISTAR_EMPRESAS_ATIVAS).fetchall()
    ]


def listar_contas_ativas(
    conexao: psycopg.Connection, empresa_id: UUID
) -> list[tuple[UUID, str]]:
    """O id interno e o ID da Meta de cada conta ativa da empresa. A conta
    inativa não é extraída."""
    return conexao.execute(LISTAR_CONTAS_ATIVAS, (empresa_id,)).fetchall()


def carregar_cadastro_conta(
    conexao: psycopg.Connection,
    empresa_id: UUID,
    execucao_id: UUID,
    conta_anuncio_id: UUID,
    extraido: CadastroExtraido,
) -> Contagens:
    for consulta in extraido.listar_consultas():
        gravar_respostas_brutas(
            conexao,
            empresa_id,
            execucao_id,
            conta_anuncio_id,
            consulta.endpoint,
            consulta.parametros,
            extraido.data_referencia,
            consulta.paginas,
        )
    cadastro = transformar_cadastro(
        extraido.id_meta_conta,
        extraido.conta.paginas[0],
        extraido.arestas[Endpoint.CAMPANHAS].paginas,
        extraido.arestas[Endpoint.CONJUNTOS].paginas,
        extraido.arestas[Endpoint.ANUNCIOS].paginas,
    )
    return carregar_cadastro(
        conexao, empresa_id, execucao_id, conta_anuncio_id, cadastro
    )
