from datetime import date
from uuid import UUID, uuid4

import pytest

from etl.carga import (
    COLUNAS_METRICA_DIARIA,
    ErroLinhaForaDaJanela,
    Linha,
    calcular_chave_lock,
    ler_colunas,
    validar_colunas_fato,
    validar_janela,
    validar_linhas_entidade,
)

LIMITE_BIGINT = 2**63


def test_chave_do_lock_e_a_mesma_para_a_mesma_empresa() -> None:
    empresa_id = uuid4()

    assert calcular_chave_lock(empresa_id) == calcular_chave_lock(UUID(str(empresa_id)))


def test_chave_do_lock_cabe_no_bigint_do_postgres() -> None:
    maior = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    menor = UUID("00000000-0000-0000-0000-000000000000")

    for empresa_id in (maior, menor, uuid4()):
        assert -LIMITE_BIGINT <= calcular_chave_lock(empresa_id) < LIMITE_BIGINT


def test_chave_do_lock_difere_entre_empresas() -> None:
    chaves = {calcular_chave_lock(uuid4()) for _ in range(1000)}

    assert len(chaves) == 1000


def test_lote_com_colunas_diferentes_e_recusado() -> None:
    with pytest.raises(ValueError, match="colunas diferentes"):
        ler_colunas([{"id_meta": "1", "nome": "A"}, {"id_meta": "2"}])


@pytest.mark.parametrize(
    ("linhas", "mensagem"),
    [
        ([{"nome": "Campanha Exemplo"}], "sem id_meta"),
        ([{"id_meta": "1", "empresa_id": uuid4()}], "gravados pela carga"),
        ([{"id_meta": "1", "execucao_id": uuid4()}], "gravados pela carga"),
        ([{"id_meta": "1"}, {"id_meta": "1"}], "repetido"),
    ],
)
def test_lote_de_entidades_invalido_e_recusado(
    linhas: list[Linha], mensagem: str
) -> None:
    with pytest.raises(ValueError, match=mensagem):
        validar_linhas_entidade(ler_colunas(linhas), linhas)


def test_fato_com_coluna_a_mais_e_recusado() -> None:
    linha = dict.fromkeys(COLUNAS_METRICA_DIARIA) | {"cliques": 1}

    with pytest.raises(ValueError, match="colunas do fato"):
        validar_colunas_fato([linha], COLUNAS_METRICA_DIARIA)


def test_fato_sem_linhas_dispensa_colunas() -> None:
    validar_colunas_fato([], COLUNAS_METRICA_DIARIA)


def test_janela_invertida_e_recusada() -> None:
    with pytest.raises(ValueError, match="início depois do fim"):
        validar_janela(date(2026, 10, 2), date(2026, 10, 1), [])


@pytest.mark.parametrize("data", [date(2026, 9, 30), date(2026, 10, 8)])
def test_fato_fora_da_janela_e_recusado(data: date) -> None:
    with pytest.raises(ErroLinhaForaDaJanela):
        validar_janela(date(2026, 10, 1), date(2026, 10, 7), [{"data": data}])


def test_fatos_nas_pontas_da_janela_sao_aceitos() -> None:
    inicio, fim = date(2026, 10, 1), date(2026, 10, 7)

    validar_janela(inicio, fim, [{"data": inicio}, {"data": fim}])
