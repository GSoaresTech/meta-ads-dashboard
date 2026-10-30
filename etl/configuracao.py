"""Configuração da ETL: constantes de negócio e variáveis de ambiente.

É a única fonte das constantes de negócio (CLAUDE.md §8); cada uma entra
junto com o código que a usa.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

PREFIXOS_URL_BANCO = ("postgresql://", "postgres://")
MENSAGEM_URL_BANCO_INVALIDA = "não é uma URL postgresql:// com host e porta válidos"
MENSAGEM_COM_ESPACO = "contém espaço, quebra de linha ou caractere de controle"


class ErroConfiguracao(Exception):
    """Variável de ambiente ausente ou inválida na inicialização."""


@dataclass(frozen=True)
class Ambiente:
    # repr=False porque os logs do Actions são públicos (CLAUDE.md §8): o
    # token e a senha da URL não podem aparecer num repr acidental.
    token_sistema_meta: str = field(repr=False)
    url_banco: str = field(repr=False)


def carregar_ambiente(variaveis: Mapping[str, str]) -> Ambiente:
    """Valida as variáveis e falha listando todos os problemas de uma vez.

    As mensagens citam só o nome da variável, nunca o valor.
    """
    token = variaveis.get("TOKEN_SISTEMA_META", "")
    url_banco = variaveis.get("URL_BANCO", "")
    problemas = [
        f"{nome}: {problema}"
        for nome, problema in (
            ("TOKEN_SISTEMA_META", validar_token(token)),
            ("URL_BANCO", validar_url_banco(url_banco)),
        )
        if problema is not None
    ]
    if problemas:
        raise ErroConfiguracao("Configuração inválida. " + "; ".join(problemas))
    return Ambiente(token_sistema_meta=token, url_banco=url_banco)


def validar_token(valor: str) -> str | None:
    if not valor.strip():
        return "ausente ou vazia"
    # Um espaço ou quebra de linha colada no secret invalidaria o cabeçalho
    # de autorização; recusamos em vez de aparar o segredo em silêncio.
    if contem_espaco_ou_controle(valor):
        return MENSAGEM_COM_ESPACO
    return None


def validar_url_banco(valor: str) -> str | None:
    if not valor.strip():
        return "ausente ou vazia"
    # urlsplit apara as pontas, descarta tab e quebra de linha e põe o esquema
    # em minúsculas; a libpq não faz nada disso e recusaria a URL só na
    # conexão, com uma mensagem que mostra a senha. Por isso conferimos o
    # valor bruto antes de interpretá-lo.
    if contem_espaco_ou_controle(valor):
        return MENSAGEM_COM_ESPACO
    if not valor.startswith(PREFIXOS_URL_BANCO):
        return MENSAGEM_URL_BANCO_INVALIDA
    try:
        partes = urlsplit(valor)
        # Ler .port levanta ValueError se a porta não for número de 0 a 65535.
        porta = partes.port
    except ValueError:
        return MENSAGEM_URL_BANCO_INVALIDA
    if not partes.hostname or porta == 0:
        return MENSAGEM_URL_BANCO_INVALIDA
    return None


def contem_espaco_ou_controle(valor: str) -> bool:
    return any(c.isspace() or not c.isprintable() for c in valor)
