from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from etl.padronizacao import (
    ErroPadronizacao,
    padronizar_data,
    padronizar_dinheiro,
    padronizar_id_conta,
    padronizar_inteiro,
    padronizar_texto,
)


def test_dinheiro_vira_decimal_exato() -> None:
    valor = padronizar_dinheiro("12.34")

    assert isinstance(valor, Decimal)
    assert valor == Decimal("12.34")
    assert str(valor) == "12.34"


def test_dinheiro_preserva_casas_que_o_float_perderia() -> None:
    # Como float, 0.1 + 0.2 não dá 0.3; como Decimal da string, dá.
    assert padronizar_dinheiro("0.1") + padronizar_dinheiro("0.2") == Decimal("0.3")
    assert padronizar_dinheiro("1234567890123.4567") == Decimal("1234567890123.4567")


@pytest.mark.parametrize("valor", [12.34, 12, True])
def test_dinheiro_recusa_numero_que_nao_veio_em_texto(valor: object) -> None:
    with pytest.raises(ErroPadronizacao):
        padronizar_dinheiro(valor)


@pytest.mark.parametrize(
    "valor", ["", " 12.34", "-1.00", "1e3", "NaN", "Infinity", "12,34", "12."]
)
def test_dinheiro_recusa_texto_fora_do_formato(valor: str) -> None:
    with pytest.raises(ErroPadronizacao):
        padronizar_dinheiro(valor)


def test_erro_nao_expoe_o_valor() -> None:
    # Os logs do Actions são públicos (CLAUDE.md §8).
    with pytest.raises(ErroPadronizacao) as erro:
        padronizar_dinheiro("-98765.43")

    assert "98765" not in str(erro.value)


@pytest.mark.parametrize(
    "funcao",
    [
        padronizar_texto,
        padronizar_dinheiro,
        padronizar_inteiro,
        padronizar_data,
        padronizar_id_conta,
    ],
)
def test_ausencia_vira_none_nunca_zero(funcao: Callable[[object], object]) -> None:
    assert funcao(None) is None


def test_texto_e_aparado() -> None:
    assert padronizar_texto("  Nome ") == "Nome"
    assert padronizar_texto("\tCampanha de Natal\n") == "Campanha de Natal"


@pytest.mark.parametrize("valor", ["", "   ", "\n\t"])
def test_texto_vazio_vira_none(valor: str) -> None:
    assert padronizar_texto(valor) is None


def test_texto_recusa_valor_que_nao_e_texto() -> None:
    # Um ID da Meta como número perderia dígitos no JavaScript (CLAUDE.md §5).
    with pytest.raises(ErroPadronizacao):
        padronizar_texto(990000000000301)


def test_inteiro_aceita_texto_numerico_e_numero_json() -> None:
    # A Meta manda contagens de insights em texto e window_days como número.
    assert padronizar_inteiro("1520") == 1520
    assert padronizar_inteiro(7) == 7
    assert padronizar_inteiro("0") == 0


@pytest.mark.parametrize("valor", ["", "1.5", "-3", "1e3", " 7", 1.0, True, -1])
def test_inteiro_recusa_fora_do_formato(valor: object) -> None:
    with pytest.raises(ErroPadronizacao):
        padronizar_inteiro(valor)


def test_data_fica_como_a_api_entrega_sem_converter_fuso() -> None:
    # A API já entrega a data no fuso da conta (R-17).
    assert padronizar_data("2026-10-01") == date(2026, 10, 1)


@pytest.mark.parametrize(
    "valor", ["", "20261001", "2026-13-01", "2026-10-01T00:00:00-0300", 20261001]
)
def test_data_recusa_fora_do_formato(valor: object) -> None:
    with pytest.raises(ErroPadronizacao):
        padronizar_data(valor)


def test_id_conta_perde_o_prefixo_act() -> None:
    # A conta guarda o account_id, sem o prefixo (ADR-0009 §1; R-35).
    assert padronizar_id_conta("act_990000000000001") == "990000000000001"


@pytest.mark.parametrize(
    "valor", ["", "990000000000001", "act_", "act_99a", 990000000000001]
)
def test_id_conta_recusa_fora_do_formato(valor: object) -> None:
    with pytest.raises(ErroPadronizacao):
        padronizar_id_conta(valor)
