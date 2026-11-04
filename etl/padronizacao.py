"""Padronização dos tipos que chegam da Marketing API (RF-13; CLAUDE.md §5).

Funções puras, sem rede, banco nem relógio. A ausência de dado (`None`) passa
como `None` e nunca vira zero. Valor presente fora do formato esperado levanta
ErroPadronizacao, em vez de ser corrigido em silêncio: a carga da empresa
falha de forma visível, e o banco nunca recebe um número reinterpretado.

As mensagens de erro citam só o tipo esperado, nunca o valor, porque podem ir
para os logs do Actions, que são públicos (CLAUDE.md §8).
"""

import re
from datetime import date
from decimal import Decimal
from typing import Final

# Formatos da Meta: dinheiro e contagens são "numeric string" e datas vêm como
# AAAA-MM-DD, já no fuso da conta (R-17). [0-9] em vez de \d, que aceitaria
# dígitos de outros alfabetos. Sem sinal: nenhum desses valores é negativo.
PADRAO_DINHEIRO: Final = re.compile(r"[0-9]+(\.[0-9]+)?")
PADRAO_INTEIRO: Final = re.compile(r"[0-9]+")
PADRAO_DATA: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# O id da conta é act_ seguido do account_id (R-35).
PADRAO_ID_CONTA: Final = re.compile(r"act_([0-9]+)")


class ErroPadronizacao(ValueError):
    """Valor da API fora do tipo esperado."""


def padronizar_texto(valor: object) -> str | None:
    """Apara o texto; vazio ou só espaços vira None."""
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ErroPadronizacao("Esperado texto.")
    aparado = valor.strip()
    return aparado or None


def padronizar_dinheiro(valor: object) -> Decimal | None:
    """Converte direto da string da API para Decimal, sem passar por float.

    Recusa número JSON: um float já teria perdido casas antes de chegar aqui.
    """
    if valor is None:
        return None
    if not isinstance(valor, str) or not PADRAO_DINHEIRO.fullmatch(valor):
        raise ErroPadronizacao("Esperado valor monetário em texto, como 12.34.")
    return Decimal(valor)


def padronizar_inteiro(valor: object) -> int | None:
    """Contagem não negativa, em texto (insights) ou número JSON (window_days)."""
    if valor is None:
        return None
    # bool é subclasse de int, e True não é uma contagem.
    if isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0:
        return valor
    if isinstance(valor, str) and PADRAO_INTEIRO.fullmatch(valor):
        return int(valor)
    raise ErroPadronizacao("Esperado inteiro não negativo.")


def padronizar_data(valor: object) -> date | None:
    """Lê a data como a API entrega, sem conversão de fuso (R-17)."""
    if valor is None:
        return None
    if not isinstance(valor, str) or not PADRAO_DATA.fullmatch(valor):
        raise ErroPadronizacao("Esperada data no formato AAAA-MM-DD.")
    try:
        return date.fromisoformat(valor)
    except ValueError:
        # from None: a mensagem do ValueError original pode repetir o valor.
        raise ErroPadronizacao("Esperada data válida no formato AAAA-MM-DD.") from None


def padronizar_id_conta(valor: object) -> str | None:
    """Tira o prefixo act_ do id da conta (ADR-0009 §1)."""
    if valor is None:
        return None
    correspondencia = (
        PADRAO_ID_CONTA.fullmatch(valor) if isinstance(valor, str) else None
    )
    if correspondencia is None:
        raise ErroPadronizacao("Esperado id de conta no formato act_<número>.")
    return correspondencia.group(1)
