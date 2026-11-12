"""Prova, contra o banco local, que o tipo de ação que a transformação grava
para cada resultado fora de actions é o que a métrica do catálogo lê
(REQUIREMENTS §7.2; ADR-0007). Sem isso, a regra resolveria para uma métrica
sem linhas, e o painel mostraria zero. Exige o banco local de pé, com as
migrations aplicadas.
"""

import psycopg
import pytest

from etl.transformacao import RESULTADOS_FORA_DE_ACTIONS

pytestmark = pytest.mark.integracao


def test_cada_resultado_fora_de_actions_e_lido_por_uma_metrica_de_resultado(
    conexao_operador: psycopg.Connection,
) -> None:
    linhas = conexao_operador.execute(
        "SELECT DISTINCT metrica.tipo_acao"
        " FROM normalizado.resultado_objetivo AS regra"
        " JOIN normalizado.metrica AS metrica"
        "   ON metrica.codigo = regra.metrica_resultado"
        " WHERE metrica.tipo = 'acao' AND metrica.medida_acao = 'quantidade'"
    ).fetchall()

    tipos_resultado = {tipo for (tipo,) in linhas}
    assert {r.tipo_acao for r in RESULTADOS_FORA_DE_ACTIONS} <= tipos_resultado
