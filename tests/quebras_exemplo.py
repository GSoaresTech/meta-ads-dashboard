"""As quebras por campanha e dia de uma conta como a API as devolve, a partir
das fixtures quebra_*_campanha.json, e a simulação das consultas da extração
com essas respostas.

As fixtures seguem a estrutura das respostas de insights, com IDs e valores
inventados (CLAUDE.md §9), nos mesmos dias e campanhas dos insights diários
por anúncio: as campanhas do cadastro e a do anúncio excluído, que só existe
pelo ID. Em cada campanha e dia, o investimento das categorias soma o da
campanha, salvo diferenças de centavos, como nas estimativas da Meta (R-23).
A região não traz as ações de fora da Meta, como cadastros e compras pelo
pixel (R-23).

A simulação só responde à consulta com os parâmetros que a extração deve
mandar: uma combinação, um nível ou um intervalo diferente sai sem resposta,
e o teste falha.
"""

import json
from datetime import date
from pathlib import Path

import responses

from etl.extracao import STATUS_EFETIVOS_CADASTRO, montar_campos
from etl.mapa_campos import ObjetoApi
from tests.cadastro_exemplo import CONTA
from tests.insights_exemplo import FIM, INICIO, simular
from tests.insights_exemplo import ler_fixtures as ler_fixtures_insights

PASTA_FIXTURES = Path(__file__).parent / "fixtures"
ID_META_CAMPANHA_AUSENTE = "995000000000000026"
# Tipo de quebra, parâmetro breakdowns e fixture, na ordem da extração.
QUEBRAS = (
    ("idade_genero", "age,gender", "quebra_idade_genero_campanha"),
    (
        "plataforma_posicionamento",
        "publisher_platform,platform_position",
        "quebra_plataforma_posicionamento_campanha",
    ),
    ("regiao", "region", "quebra_regiao_campanha"),
)
# O tipo de ação do resultado principal de cada campanha das fixtures, pelo
# catálogo: Engajamento (ThruPlay cai na regra de "qualquer"), Cadastros e
# Vendas.
TIPOS_ACAO_RESULTADO = {
    "995000000000000002": "post_engagement",
    "995000000000000003": "lead",
    "995000000000000004": "post_engagement",
    "995000000000000005": "omni_purchase",
    ID_META_CAMPANHA_AUSENTE: "omni_purchase",
}
type Fixtures = dict[str, dict]


def ler_fixtures() -> Fixtures:
    """Uma cópia nova a cada chamada, para o teste alterar à vontade."""
    return {
        nome: json.loads((PASTA_FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))
        for _, _, nome in QUEBRAS
    }


def montar_parametros_quebra(
    quebras: str, inicio: date = INICIO, fim: date = FIM
) -> dict[str, str]:
    return {
        "level": "campaign",
        "time_increment": "1",
        "time_range": json.dumps(
            {"since": inicio.isoformat(), "until": fim.isoformat()}
        ),
        "breakdowns": quebras,
        "fields": "campaign_id,spend,impressions,reach,actions,action_values",
        "filtering": json.dumps(
            [
                {
                    "field": "ad.effective_status",
                    "operator": "IN",
                    "value": [*STATUS_EFETIVOS_CADASTRO, "DELETED"],
                }
            ]
        ),
        "limit": "500",
    }


def listar_linhas(fixtures: Fixtures, tipo: str) -> list[dict]:
    nome = next(nome for t, _, nome in QUEBRAS if t == tipo)
    return fixtures[nome]["corpo"]["data"]


def simular_quebras(
    api: responses.RequestsMock, fixtures: Fixtures, *, com_campanha: bool = True
) -> None:
    """Registra, na ordem da extração, as três consultas da conta e, com
    com_campanha, a leitura pelo ID da campanha ausente do banco."""
    for _, quebras, nome in QUEBRAS:
        simular(
            api, f"{CONTA}/insights", fixtures[nome], montar_parametros_quebra(quebras)
        )
    if com_campanha:
        simular_campanha_ausente(api)


def simular_campanha_ausente(api: responses.RequestsMock) -> None:
    fixture = ler_fixtures_insights()["entidade_campanha_por_id"]
    simular(
        api,
        ID_META_CAMPANHA_AUSENTE,
        fixture,
        {"fields": montar_campos(ObjetoApi.CAMPANHA)},
    )
