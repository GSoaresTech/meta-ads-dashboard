import pytest

from etl.configuracao import ErroConfiguracao, carregar_ambiente

TOKEN_FICTICIO = "token-ficticio"
URL_FICTICIA = "postgresql://postgres:senha-ficticia@127.0.0.1:54322/postgres"


def montar_variaveis(**sobrescritas: str) -> dict[str, str]:
    variaveis = {"TOKEN_SISTEMA_META": TOKEN_FICTICIO, "URL_BANCO": URL_FICTICIA}
    variaveis.update(sobrescritas)
    return variaveis


def test_carrega_variaveis_validas() -> None:
    ambiente = carregar_ambiente(montar_variaveis())

    assert ambiente.token_sistema_meta == TOKEN_FICTICIO
    assert ambiente.url_banco == URL_FICTICIA


def test_aceita_esquema_postgres_abreviado() -> None:
    url = "postgres://postgres:senha-ficticia@db.exemplo.invalid:5432/postgres"

    ambiente = carregar_ambiente(montar_variaveis(URL_BANCO=url))

    assert ambiente.url_banco == url


@pytest.mark.parametrize("nome", ["TOKEN_SISTEMA_META", "URL_BANCO"])
def test_falha_com_variavel_ausente(nome: str) -> None:
    variaveis = montar_variaveis()
    del variaveis[nome]

    with pytest.raises(ErroConfiguracao, match=f"{nome}: ausente ou vazia"):
        carregar_ambiente(variaveis)


@pytest.mark.parametrize("nome", ["TOKEN_SISTEMA_META", "URL_BANCO"])
@pytest.mark.parametrize("valor", ["", "   "])
def test_falha_com_variavel_vazia(nome: str, valor: str) -> None:
    with pytest.raises(ErroConfiguracao, match=f"{nome}: ausente ou vazia"):
        carregar_ambiente(montar_variaveis(**{nome: valor}))


@pytest.mark.parametrize("token", ["token ficticio", "token-ficticio\n"])
def test_falha_com_token_com_espaco(token: str) -> None:
    with pytest.raises(ErroConfiguracao, match="TOKEN_SISTEMA_META: contém espaço"):
        carregar_ambiente(montar_variaveis(TOKEN_SISTEMA_META=token))


@pytest.mark.parametrize(
    "url",
    [
        f" {URL_FICTICIA}",
        f"{URL_FICTICIA}\n",
        "postgresql://postgres:senha@127.0.0.1\t:54322/postgres",
    ],
)
def test_falha_com_url_banco_com_espaco(url: str) -> None:
    with pytest.raises(ErroConfiguracao, match="URL_BANCO: contém espaço"):
        carregar_ambiente(montar_variaveis(URL_BANCO=url))


@pytest.mark.parametrize(
    "url",
    [
        "nao-e-url",
        "POSTGRESQL://postgres:senha@127.0.0.1:54322/postgres",
        "mysql://usuario:senha@127.0.0.1:3306/banco",
        "postgresql:///postgres",
        "postgresql://127.0.0.1:porta/postgres",
        "postgresql://127.0.0.1:99999/postgres",
        "postgresql://127.0.0.1:0/postgres",
    ],
)
def test_falha_com_url_banco_invalida(url: str) -> None:
    with pytest.raises(ErroConfiguracao, match="URL_BANCO: não é uma URL postgresql"):
        carregar_ambiente(montar_variaveis(URL_BANCO=url))


def test_lista_todos_os_problemas_de_uma_vez() -> None:
    with pytest.raises(ErroConfiguracao) as erro:
        carregar_ambiente({"URL_BANCO": "nao-e-url"})

    assert "TOKEN_SISTEMA_META: ausente ou vazia" in str(erro.value)
    assert "URL_BANCO: não é uma URL postgresql" in str(erro.value)


def test_mensagem_de_erro_nao_expoe_valores() -> None:
    token = "token secreto"
    url = "mysql://usuario:senha-secreta@127.0.0.1:3306/banco"

    with pytest.raises(ErroConfiguracao) as erro:
        carregar_ambiente(montar_variaveis(TOKEN_SISTEMA_META=token, URL_BANCO=url))

    assert token not in str(erro.value)
    assert "senha-secreta" not in str(erro.value)


def test_repr_do_ambiente_nao_expoe_valores() -> None:
    ambiente = carregar_ambiente(montar_variaveis())

    assert TOKEN_FICTICIO not in repr(ambiente)
    assert "senha-ficticia" not in repr(ambiente)
