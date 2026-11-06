"""O limite de 37 meses e o ponto de entrada da carga histórica, sem banco nem
rede. O que depende do banco está em tests/test_carga_historica_banco.py.
"""

from datetime import UTC, date, datetime

import psycopg
import pytest

from etl import carga_historica
from etl.carga_historica import calcular_dia_conta, calcular_limite_historico, main
from etl.execucao import CODIGO_SAIDA_FALHA, CODIGO_SAIDA_SUCESSO

SENHA_FICTICIA = "senha-ficticia-do-banco"
URL_FICTICIA = f"postgresql://etl:{SENHA_FICTICIA}@banco.ficticio.invalid:5432/postgres"
TOKEN_FICTICIO = "EAAFicticio0000000000000000000000000000000000ZZ"


@pytest.fixture
def ambiente_valido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_SISTEMA_META", TOKEN_FICTICIO)
    monkeypatch.setenv("URL_BANCO", URL_FICTICIA)


@pytest.mark.parametrize(
    ("hoje", "limite"),
    [
        # Em 06/11/2026, os insights aceitaram o since de 06/10/2023 e
        # recusaram o de 05/10/2023 (R-19). Com o hoje da Meta já em 07/11,
        # o limite dela seria 07/10/2023.
        (date(2026, 11, 6), date(2023, 10, 7)),
        # A conta do mês recua o ano.
        (date(2027, 1, 15), date(2023, 12, 16)),
        # No último dia do mês, o hoje da Meta pode já estar no mês seguinte,
        # e o limite dela, no dia 1: o +1 dia depois do recuo não basta.
        (date(2026, 11, 30), date(2023, 11, 1)),
        (date(2027, 2, 28), date(2024, 2, 1)),
        # O dia que não existe no mês do limite vai para o mês seguinte, o
        # mais tardio entre ajustá-lo para o último dia e transbordá-lo.
        (date(2026, 12, 31), date(2023, 12, 1)),
        (date(2028, 3, 30), date(2025, 3, 3)),
        (date(2028, 3, 31), date(2025, 3, 3)),
    ],
)
def test_limite_e_o_mais_tardio_entre_hoje_e_amanha_menos_37_meses(
    hoje: date, limite: date
) -> None:
    assert calcular_limite_historico(hoje) == limite


def test_dia_da_conta_e_o_do_instante_no_fuso_dela() -> None:
    # 06:43 UTC é 03:43 em Brasília e 23:43 da véspera em Los Angeles.
    instante = datetime(2026, 11, 6, 6, 43, tzinfo=UTC)

    assert calcular_dia_conta(instante, "America/Sao_Paulo") == date(2026, 11, 6)
    assert calcular_dia_conta(instante, "America/Los_Angeles") == date(2026, 11, 5)


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

    monkeypatch.setattr(carga_historica, "conectar_banco", falhar)

    assert main() == CODIGO_SAIDA_FALHA

    saida = capsys.readouterr()
    assert "OperationalError" in saida.err
    assert "banco.ficticio.invalid" not in saida.out + saida.err
    assert SENHA_FICTICIA not in saida.out + saida.err


def test_main_devolve_o_codigo_de_saida_do_laco_por_empresa(
    monkeypatch: pytest.MonkeyPatch, ambiente_valido: None
) -> None:
    monkeypatch.setattr(
        carga_historica,
        "executar_carga_historica",
        lambda ambiente: CODIGO_SAIDA_SUCESSO,
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

    monkeypatch.setattr(carga_historica, "executar_carga_historica", interromper)

    assert main() == CODIGO_SAIDA_FALHA

    saida = capsys.readouterr()
    assert "KeyboardInterrupt" in saida.err
    assert "banco.ficticio.invalid" not in saida.out + saida.err
