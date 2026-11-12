"""A janela, as campanhas das quebras relidas à parte e o ponto de entrada da
rotina horária, sem banco nem rede. O que depende do banco está em
tests/test_rotina_horaria_banco.py.
"""

from datetime import date

import psycopg
import pytest

from etl import rotina_horaria
from etl.cliente_api_meta import Endpoint
from etl.execucao import CODIGO_SAIDA_FALHA, CODIGO_SAIDA_SUCESSO
from etl.extracao import Consulta, EntidadesExtraidas, TipoQuebra
from etl.rotina_horaria import (
    calcular_janela_horaria,
    listar_campanhas_sem_anuncio,
    main,
)

SENHA_FICTICIA = "senha-ficticia-do-banco"
URL_FICTICIA = f"postgresql://etl:{SENHA_FICTICIA}@banco.ficticio.invalid:5432/postgres"
TOKEN_FICTICIO = "EAAFicticio0000000000000000000000000000000000ZZ"
ID_CAMPANHA_DO_ANUNCIO = "995000000000000002"
ID_CAMPANHA_SO_NAS_QUEBRAS = "995000000000000099"


@pytest.fixture
def ambiente_valido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_SISTEMA_META", TOKEN_FICTICIO)
    monkeypatch.setenv("URL_BANCO", URL_FICTICIA)


def test_janela_e_ontem_e_hoje() -> None:
    assert calcular_janela_horaria(date(2026, 10, 2)) == (
        date(2026, 10, 1),
        date(2026, 10, 2),
    )


def test_janela_cruza_a_virada_do_ano() -> None:
    assert calcular_janela_horaria(date(2027, 1, 1)) == (
        date(2026, 12, 31),
        date(2027, 1, 1),
    )


def montar_consulta(paginas: list[dict[str, object]]) -> Consulta:
    return Consulta(Endpoint.INSIGHTS, {}, paginas)


def test_campanha_que_so_aparece_nas_quebras_e_relida_uma_vez() -> None:
    # A campanha do anúncio relido já vem com ele; a que só aparece nas
    # quebras também teve entrega, e entra uma vez, mesmo em duas quebras.
    linha_do_anuncio = {"campaign_id": ID_CAMPANHA_DO_ANUNCIO}
    linha_so_nas_quebras = {"campaign_id": ID_CAMPANHA_SO_NAS_QUEBRAS}
    quebras = {
        TipoQuebra.IDADE_GENERO: montar_consulta(
            [{"data": [linha_do_anuncio, linha_so_nas_quebras]}]
        ),
        TipoQuebra.REGIAO: montar_consulta([{"data": [linha_so_nas_quebras]}]),
    }
    entidades = EntidadesExtraidas(
        montar_consulta([]),
        montar_consulta([]),
        Consulta(Endpoint.OBJETO, {}, [{"id": ID_CAMPANHA_DO_ANUNCIO}]),
    )

    assert listar_campanhas_sem_anuncio(quebras, entidades) == [
        ID_CAMPANHA_SO_NAS_QUEBRAS
    ]


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

    monkeypatch.setattr(rotina_horaria, "conectar_banco", falhar)

    assert main() == CODIGO_SAIDA_FALHA

    saida = capsys.readouterr()
    assert "OperationalError" in saida.err
    assert "banco.ficticio.invalid" not in saida.out + saida.err
    assert SENHA_FICTICIA not in saida.out + saida.err


def test_main_devolve_o_codigo_de_saida_do_laco_por_empresa(
    monkeypatch: pytest.MonkeyPatch, ambiente_valido: None
) -> None:
    monkeypatch.setattr(
        rotina_horaria, "executar_rotina", lambda ambiente: CODIGO_SAIDA_SUCESSO
    )

    assert main() == CODIGO_SAIDA_SUCESSO
