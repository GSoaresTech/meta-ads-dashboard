"""Extração do cadastro de uma conta de anúncios: a própria conta, com o fuso
e a moeda, e as campanhas, os conjuntos e os anúncios, com o criativo de cada
anúncio expandido (RF-01, RF-43). Só faz o I/O de rede, fora de transação, e
devolve as páginas como a Meta as entregou, para a gravação em bruto antes da
transformação (RF-09; CLAUDE.md §3).
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final
from zoneinfo import ZoneInfo

from etl.cliente_api_meta import ClienteApiMeta, Endpoint, ErroRespostaInvalida
from etl.configuracao import LIMITE_PAGINA_CADASTRO
from etl.mapa_campos import MAPA_CAMPOS, ObjetoApi, TipoCampo

PREFIXO_ID_CONTA: Final = "act_"

# Sem filtro de status, as arestas omitem os objetos ARCHIVED, que os insights
# incluem. A lista é a documentada sem DELETED, que a API recusa no parâmetro;
# com ela, as três arestas devolvem todos os objetos não excluídos (R-38).
STATUS_EFETIVOS_CADASTRO: Final = (
    "ACTIVE",
    "PAUSED",
    "PENDING_REVIEW",
    "DISAPPROVED",
    "PREAPPROVED",
    "PENDING_BILLING_INFO",
    "CAMPAIGN_PAUSED",
    "ARCHIVED",
    "ADSET_PAUSED",
    "IN_PROCESS",
    "WITH_ISSUES",
)

# Campos do mapa que o cadastro não pede. Com a URL da miniatura, a aresta de
# anúncios falha com o código 1 mesmo no LIMITE_PAGINA_CADASTRO (R-42), e a
# URL, que vence em poucos dias, só serve à cópia para o Storage (RF-38;
# R-26).
CAMPOS_FORA_DO_CADASTRO: Final = frozenset({"thumbnail_url"})

# De baixo para cima: o pai de um objeto já existe quando a aresta do pai é
# lida, mesmo que tenha sido criado durante a leitura das outras. Na ordem
# inversa, uma campanha criada depois da leitura das campanhas, com anúncio
# lido em seguida, deixaria o anúncio sem pai e faria a empresa falhar.
ARESTAS_CADASTRO: Final[Mapping[Endpoint, ObjetoApi]] = {
    Endpoint.ANUNCIOS: ObjetoApi.ANUNCIO,
    Endpoint.CONJUNTOS: ObjetoApi.CONJUNTO,
    Endpoint.CAMPANHAS: ObjetoApi.CAMPANHA,
}


@dataclass(frozen=True)
class Consulta:
    """Uma consulta à API e as páginas que ela devolveu, na ordem."""

    endpoint: Endpoint
    parametros: Mapping[str, str]
    paginas: Sequence[dict[str, object]]


@dataclass(frozen=True)
class CadastroExtraido:
    """O cadastro de uma conta como a Meta o entregou.

    data_referencia é a data da extração no fuso da conta, que a retenção de
    bruto usa nas consultas de cadastro (RF-21; ADR-0009 §2).
    """

    id_meta_conta: str
    data_referencia: date
    conta: Consulta
    arestas: Mapping[Endpoint, Consulta]

    def listar_consultas(self) -> tuple[Consulta, ...]:
        return (self.conta, *self.arestas.values())


def agora_utc() -> datetime:
    return datetime.now(UTC)


def montar_campos(objeto: ObjetoApi) -> str:
    """O parâmetro fields com os campos do objeto no mapa, e só eles, salvo
    os de CAMPOS_FORA_DO_CADASTRO.

    Pedir pelo mapa garante que a transformação encontra cada campo
    recebido no mapa (RF-11). Um objeto aninhado, como o criativo do
    anúncio, é expandido com os campos dele; as listas, como o
    attribution_spec, vêm inteiras pelo nome.
    """
    partes = []
    for nome_api, campo in MAPA_CAMPOS[objeto].items():
        if nome_api in CAMPOS_FORA_DO_CADASTRO:
            continue
        if campo.tipo is TipoCampo.OBJETO and campo.itens is not None:
            partes.append(f"{nome_api}{{{montar_campos(campo.itens)}}}")
        else:
            partes.append(nome_api)
    return ",".join(partes)


def montar_parametros_aresta(objeto: ObjetoApi) -> dict[str, str]:
    return {
        "fields": montar_campos(objeto),
        "effective_status": json.dumps(list(STATUS_EFETIVOS_CADASTRO)),
        "limit": str(LIMITE_PAGINA_CADASTRO),
    }


def extrair_cadastro_conta(
    cliente: ClienteApiMeta,
    id_meta_conta: str,
    relogio: Callable[[], datetime] = agora_utc,
) -> CadastroExtraido:
    """Lê a conta e, paginados, os anúncios, os conjuntos e as campanhas dela.

    A conta vem primeiro porque o fuso dela dá a data de referência. Uma
    falha em qualquer consulta sobe sem devolver nada, e a empresa falha
    sem gravar parte do cadastro.
    """
    objeto_conta = f"{PREFIXO_ID_CONTA}{id_meta_conta}"
    parametros_conta = {"fields": montar_campos(ObjetoApi.CONTA)}
    resposta_conta = cliente.obter(objeto_conta, Endpoint.OBJETO, parametros_conta)
    conta = Consulta(Endpoint.OBJETO, parametros_conta, [resposta_conta])
    arestas = {}
    for endpoint, objeto in ARESTAS_CADASTRO.items():
        parametros = montar_parametros_aresta(objeto)
        paginas = cliente.paginar(objeto_conta, endpoint, parametros)
        arestas[endpoint] = Consulta(endpoint, parametros, paginas)
    return CadastroExtraido(
        id_meta_conta=id_meta_conta,
        data_referencia=calcular_data_referencia(resposta_conta, relogio()),
        conta=conta,
        arestas=arestas,
    )


def calcular_data_referencia(
    resposta_conta: Mapping[str, object], instante: datetime
) -> date:
    """A data do instante no fuso da conta, como a Meta o informa."""
    fuso = resposta_conta.get("timezone_name")
    if not isinstance(fuso, str) or not fuso:
        raise ErroRespostaInvalida()
    return instante.astimezone(ZoneInfo(fuso)).date()
