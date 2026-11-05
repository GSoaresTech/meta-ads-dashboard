"""A janela de reprocessamento e o ponto de entrada da rotina diária, sem banco
nem rede. O que depende do banco está em tests/test_rotina_diaria_banco.py.
"""

from datetime import date

import psycopg
import pytest

from etl import rotina_diaria
from etl.execucao import CODIGO_SAIDA_FALHA, CODIGO_SAIDA_SUCESSO
from etl.rotina_diaria import calcular_janela_reprocessamento, main

SENHA_FICTICIA = "senha-ficticia-do-banco"
URL_FICTICIA = f"postgresql://etl:{SENHA_FICTICIA}@banco.ficticio.invalid:5432/postgres"
TOKEN_FICTICIO = "EAAFicticio0000000000000000000000000000000000ZZ"


@pytest.fixture
def ambiente_valido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_SISTEMA_META", TOKEN_FICTICIO)
    monkeypatch.setenv("URL_BANCO", URL_FICTICIA)


def test_janela_sao_os_28_dias_anteriores_sem_o_dia_de_hoje() -> None:
    # Como a execução de 07/04/2026 do ADR-0006: hoje fica com a rotina
    # horária (ADR-0005).
    assert calcular_janela_reprocessamento(date(2026, 4, 7)) == (
        date(2026, 3, 10),
        date(2026, 4, 6),
    )


def test_janela_cruza_a_virada_do_ano() -> None:
    assert calcular_janela_reprocessamento(date(2027, 1, 10)) == (
        date(2026, 12, 13),
        date(2027, 1, 9),
    )


def test_main_com_variavel_ausente_falha_citando_so_o_nome(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TOKEN_SISTEMA_META", TOKEN_FICTICIO)
    monkeypatch.delenv("URL_BANCO", raising=False)

    assert main() == CODIGO_SAIDA_FALHA

    saida = capsys.readouterr()
    assert "URL_BANCO" in saida.err
    assert TOKEN_FICTICIO not in saida.out + saida.err


def test_main_sem_banco_falha_sem_expor_a_mensagem_do_erro(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ambiente_valido: None,
) -> None:
    # A mensagem de conexão da libpq pode trazer o host, o usuário e a senha,
    # e o traceback iria para o log público do Actions (RNF-17).
    def falhar(url_banco: str) -> psycopg.Connection:
        raise psycopg.OperationalError(f"sem conexão com {url_banco}")

    monkeypatch.setattr(rotina_diaria, "conectar_banco", falhar)

    assert main() == CODIGO_SAIDA_FALHA

    saida = capsys.readouterr()
    assert "OperationalError" in saida.err
    assert "banco.ficticio.invalid" not in saida.out + saida.err
    assert SENHA_FICTICIA not in saida.out + saida.err


def test_main_devolve_o_codigo_de_saida_do_laco_por_empresa(
    monkeypatch: pytest.MonkeyPatch, ambiente_valido: None
) -> None:
    monkeypatch.setattr(
        rotina_diaria, "executar_rotina", lambda ambiente: CODIGO_SAIDA_SUCESSO
    )

    assert main() == CODIGO_SAIDA_SUCESSO


def test_main_interrompida_nao_expoe_o_erro_em_tratamento(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ambiente_valido: None,
) -> None:
    # Sem captura, o Python imprimiria a interrupção com o erro encadeado.
    def interromper(ambiente: object) -> int:
        try:
            raise psycopg.OperationalError("sem conexão com banco.ficticio.invalid")
        except psycopg.OperationalError:
            raise KeyboardInterrupt

    monkeypatch.setattr(rotina_diaria, "executar_rotina", interromper)

    assert main() == CODIGO_SAIDA_FALHA

    saida = capsys.readouterr()
    assert "KeyboardInterrupt" in saida.err
    assert "banco.ficticio.invalid" not in saida.out + saida.err
