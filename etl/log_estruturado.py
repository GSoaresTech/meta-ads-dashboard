"""Log estruturado da ETL: uma linha JSON por registro, só com campos permitidos.

Os logs do Actions são públicos (ADR-0008), então a linha não tem texto
livre: só os campos de CAMPOS_PERMITIDOS, com valor UUID, inteiro ou de
domínio fechado (RNF-17; CLAUDE.md §8). A mensagem, os args e o traceback de
um registro nunca são escritos, porque podem trazer nome de empresa, de
campanha ou de anúncio, ID da Meta, valor monetário ou token. A mensagem de
erro da Meta é o caso típico: o erro entra só pelo código e pelo subcódigo.

O handler fica na raiz, e o formatador vale também para os registros de
bibliotecas como o urllib3 e o psycopg e para os avisos do módulo warnings,
cujas mensagens podem conter a URL ou o ID da conta. Deles sobram o nível e
os identificadores da execução. Exceções não capturadas não passam por aqui:
o traceback delas é impresso pelo Python, e o ponto de entrada da ETL precisa
capturá-las.
"""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, TextIO
from uuid import UUID

CAMPOS_PERMITIDOS: Final = frozenset(
    {
        "instante",
        "nivel",
        "execucao_id",
        "empresa_id",
        "tipo_execucao",
        "etapa",
        "status",
        "linhas",
        "tentativas",
        "duracao_ms",
        "codigo_erro",
        "subcodigo_erro",
    }
)

# Os domínios de tipo e status repetem os CHECKs de execucao_carga
# (ADR-0009 §2); as etapas são as do CLAUDE.md §3, mais a retenção de bruto
# da execução diária (RF-21).
TIPOS_EXECUCAO: Final = frozenset({"horaria", "diaria", "historica"})
DOMINIOS_REGISTRO: Final = {
    "etapa": frozenset({"extrair", "transformar", "carregar", "reter"}),
    "status": frozenset({"em_andamento", "sucesso", "falha", "ignorada"}),
}
CAMPOS_INTEIROS: Final = (
    "linhas",
    "tentativas",
    "duracao_ms",
    "codigo_erro",
    "subcodigo_erro",
)

# Um ID da Meta tem de 15 a 18 dígitos (CLAUDE.md §5). O teto recusa o ID
# passado como inteiro num campo de contagem ou de código, com folga sobre os
# códigos e subcódigos da Meta e sobre a duração em ms de uma execução.
LIMITE_INTEIRO_LOG: Final = 10**12

MENSAGEM_FORA_DO_DOMINIO = "fora do domínio permitido"
MENSAGEM_INTEIRO_INVALIDO = "deve ser inteiro de zero até abaixo de LIMITE_INTEIRO_LOG"
MENSAGEM_UUID_INVALIDO = "deve ser UUID"

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextoExecucao:
    execucao_id: UUID
    empresa_id: UUID
    tipo_execucao: str


_contexto: ContextVar[ContextoExecucao | None] = ContextVar(
    "contexto_execucao", default=None
)


@contextmanager
def contexto_execucao(
    execucao_id: UUID, empresa_id: UUID, tipo_execucao: str
) -> Iterator[None]:
    """Marca as linhas emitidas dentro do bloco com a execução e a empresa.

    Os erros citam só o nome do campo, nunca o valor recebido.
    """
    for campo, valor in (("execucao_id", execucao_id), ("empresa_id", empresa_id)):
        if not isinstance(valor, UUID):
            raise TypeError(f"{campo}: {MENSAGEM_UUID_INVALIDO}")
    if tipo_execucao not in TIPOS_EXECUCAO:
        raise ValueError(f"tipo_execucao: {MENSAGEM_FORA_DO_DOMINIO}")
    token = _contexto.set(ContextoExecucao(execucao_id, empresa_id, tipo_execucao))
    try:
        yield
    finally:
        _contexto.reset(token)


def registrar_evento(
    status: str,
    *,
    etapa: str | None = None,
    linhas: int | None = None,
    tentativas: int | None = None,
    duracao_ms: int | None = None,
    codigo_erro: int | None = None,
    subcodigo_erro: int | None = None,
    nivel: int = logging.INFO,
) -> None:
    """Emite uma linha com os campos dados, dentro de contexto_execucao.

    Um valor fora do domínio é erro de programação: falha na chamada, sem
    citar o valor, em vez de sumir da linha em silêncio.
    """
    if _contexto.get() is None:
        raise RuntimeError("registrar_evento chamado fora de uma execução")
    campos = {
        "etapa": etapa,
        "status": status,
        "linhas": linhas,
        "tentativas": tentativas,
        "duracao_ms": duracao_ms,
        "codigo_erro": codigo_erro,
        "subcodigo_erro": subcodigo_erro,
    }
    extra = {campo: valor for campo, valor in campos.items() if valor is not None}
    for campo, valor in extra.items():
        problema = validar_campo_registro(campo, valor)
        if problema is not None:
            raise ValueError(f"{campo}: {problema}")
    LOGGER.log(nivel, "evento", extra=extra)


def validar_campo_registro(campo: str, valor: object) -> str | None:
    if campo in DOMINIOS_REGISTRO:
        if isinstance(valor, str) and valor in DOMINIOS_REGISTRO[campo]:
            return None
        return MENSAGEM_FORA_DO_DOMINIO
    # type() em vez de isinstance para recusar bool, que é subclasse de int.
    if (
        campo in CAMPOS_INTEIROS
        and type(valor) is int
        and 0 <= valor < LIMITE_INTEIRO_LOG
    ):
        return None
    return MENSAGEM_INTEIRO_INVALIDO


def montar_campos(
    registro: logging.LogRecord, contexto: ContextoExecucao | None
) -> dict[str, object]:
    """Escolhe do registro só os campos permitidos com valor válido.

    Nunca chama getMessage(): a mensagem não é escrita, e um registro com
    args errados não gera o erro que o logging imprimiria com os args.
    """
    campos: dict[str, object] = {
        "instante": datetime.fromtimestamp(registro.created, UTC).isoformat(
            timespec="milliseconds"
        ),
        "nivel": registro.levelname,
    }
    if contexto is not None:
        campos["execucao_id"] = str(contexto.execucao_id)
        campos["empresa_id"] = str(contexto.empresa_id)
        campos["tipo_execucao"] = contexto.tipo_execucao
    for campo in (*DOMINIOS_REGISTRO, *CAMPOS_INTEIROS):
        valor = registro.__dict__.get(campo)
        if valor is not None and validar_campo_registro(campo, valor) is None:
            campos[campo] = valor
    return {
        campo: valor for campo, valor in campos.items() if campo in CAMPOS_PERMITIDOS
    }


class FormatadorJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(montar_campos(record, _contexto.get()))


class ManipuladorJson(logging.StreamHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        # O handleError padrão imprime no stderr a mensagem e os args do
        # registro, que iriam ao log público quando a escrita falhasse.
        sys.stderr.write(
            "Falha ao escrever uma linha de log; conteúdo omitido (RNF-17).\n"
        )


def pertence_a_execucao(registro: logging.LogRecord) -> bool:
    """Descarta o registro emitido fora de uma execução: sem execucao_id, a
    linha não teria a quem ser atribuída. Uma thread nova não herda o
    contexto: quem a cria precisa rodá-la com contextvars.copy_context()."""
    return _contexto.get() is not None


def configurar_log(fluxo: TextIO = sys.stdout) -> None:
    """Põe o handler JSON como único handler da raiz, no nível INFO.

    Deve ser a primeira coisa do processo: até aqui, um registro sai em
    texto puro pelo logging.lastResort.
    """
    handler = ManipuladorJson(fluxo)
    handler.setFormatter(FormatadorJson())
    handler.addFilter(pertence_a_execucao)
    logging.basicConfig(handlers=[handler], level=logging.INFO, force=True)
    # O lastResort escreveria em texto puro o registro de um logger sem
    # handler na cadeia, como um com propagate=False.
    logging.lastResort = None
    logging.captureWarnings(True)
