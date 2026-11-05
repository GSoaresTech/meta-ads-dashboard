"""Configuração da ETL: constantes de negócio e variáveis de ambiente.

É a única fonte das constantes de negócio (CLAUDE.md §8); cada uma entra
junto com o código que a usa. As cotas do plano são a exceção: entram com o
provisionamento, que as fixa (ADR-0010).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from urllib.parse import urlsplit

PREFIXOS_URL_BANCO = ("postgresql://", "postgres://")
MENSAGEM_URL_BANCO_INVALIDA = "não é uma URL postgresql:// com host e porta válidos"
MENSAGEM_COM_ESPACO = "contém espaço, quebra de linha ou caractere de controle"

# Cotas do plano Pro do Supabase, consultadas em 03/11/2026 em
# https://supabase.com/pricing (R-28). O disco é cotado por projeto e cobrado
# pelo tamanho provisionado. Storage e egress são cotados pela organização,
# que dividimos com outro projeto: o alerta do RF-52 compara o uso deste
# projeto com a parcela reservada a ele (ADR-0010).
COTA_DISCO_PROJETO_GB = 8
COTA_STORAGE_ORGANIZACAO_GB = 100
COTA_EGRESS_ORGANIZACAO_GB = 250
COTA_EGRESS_CACHE_ORGANIZACAO_GB = 250
PARCELA_COTA_ORGANIZACAO = Decimal("0.3")

# Único lugar da versão da Graph/Marketing API (RF-10; R-12).
VERSAO_API_META = "v26.0"
URL_BASE_API_META = "https://graph.facebook.com"
# Espera máxima por uma resposta. Esgotada, a consulta síncrona de insights
# é refeita por job assíncrono (RF-08), e as demais chamadas são tentadas de
# novo.
TEMPO_LIMITE_REQUISICAO_SEGUNDOS = 120
# Jobs assíncronos podem levar até 1 h (R-18).
INTERVALO_CONSULTA_RELATORIO_SEGUNDOS = 15
TEMPO_MAXIMO_RELATORIO_SEGUNDOS = 3600

# Tamanho de página das arestas de cadastro. Com o criativo expandido, a de
# anúncios recusa páginas maiores com o código 1 (R-42).
LIMITE_PAGINA_CADASTRO = 100
# Tamanho de página dos insights: os diários por anúncio e o alcance por
# período. Uma página maior gasta menos chamadas da cota por conta (R-15);
# páginas cheias de 500, com actions e action_values, vieram sem erro (R-21).
LIMITE_PAGINA_INSIGHTS = 500

# Limites da Marketing API (RF-08; R-15). Com estas esperas, a soma mínima
# entre a primeira e a última tentativa (360 s) passa do bloqueio de 300 s do
# nível de desenvolvimento, e a máxima (720 s) cabe na execução horária.
MAXIMO_TENTATIVAS = 5
ESPERA_INICIAL_SEGUNDOS = 60
ESPERA_MAXIMA_SEGUNDOS = 300
# A partir deste uso informado nos cabeçalhos, a próxima chamada espera antes
# de sair, em vez de gastar o que resta da cota até o erro de limite.
LIMITE_USO_PERCENTUAL = 90

# Concorrência da carga (RF-19): a segunda execução da mesma empresa espera
# até 15 min pelo lock e, sem obtê-lo, termina como ignorada. Cada tentativa
# é uma transação curta, para não segurar uma transação aberta durante a
# espera.
ESPERA_MAXIMA_LOCK_SEGUNDOS = 900
INTERVALO_TENTATIVA_LOCK_SEGUNDOS = 10

# A Meta revisa os dados por até 28 dias (R-17): a execução diária recarrega
# os dias anteriores a hoje nessa janela (RF-05).
JANELA_REPROCESSAMENTO_DIAS = 28

# Retenção de bruto pela data de referência (RF-21): a janela de
# reprocessamento de 28 dias mais uma margem (ADR-0005).
RETENCAO_BRUTO_DIAS = 35


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
