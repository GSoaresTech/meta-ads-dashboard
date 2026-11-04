import io
import json
import logging
import warnings
from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID

import pytest

from etl.log_estruturado import (
    CAMPOS_PERMITIDOS,
    configurar_log,
    contexto_execucao,
    registrar_evento,
)

EXECUCAO_ID = UUID("00000000-0000-4000-8000-000000000001")
EMPRESA_ID = UUID("00000000-0000-4000-8000-0000000000e1")
OUTRA_EXECUCAO_ID = UUID("00000000-0000-4000-8000-000000000002")

# Dados fictícios no formato dos reais: o que nenhuma linha de log pode conter
# (RNF-17).
NOME_EMPRESA = "Empresa Exemplo Ltda"
NOME_CAMPANHA = "Promoção Dia das Mães - Empresa Exemplo"
NOME_ANUNCIO = "Vídeo Depoimento Cliente 03"
ID_META_CONTA = "act_990000000000001"
ID_META_CAMPANHA = "990000000000000101"
VALOR_MONETARIO = Decimal("1234.56")
TOKEN = "EAAFicticio0000000000000000000000000000000000ZZ"

# Corpo de erro da Graph API no formato documentado (code, error_subcode,
# error_user_title, error_user_msg, fbtrace_id), com os dados trocados por
# fictícios. O subcódigo 33 é o de objeto inexistente ou sem permissão.
ERRO_META = {
    "error": {
        "message": (
            f"Unsupported get request. Object with ID '{ID_META_CAMPANHA}' does not exist, "
            "cannot be loaded due to missing permissions, or does not support this operation."
        ),
        "type": "GraphMethodException",
        "code": 100,
        "error_subcode": 33,
        "error_user_title": "Campanha indisponível",
        "error_user_msg": (
            f'A campanha "{NOME_CAMPANHA}" da conta {NOME_EMPRESA} não pode ser lida.'
        ),
        "fbtrace_id": "AbCdEfGhIjKlMnOpQrStUv0",
    }
}

DADOS_SENSIVEIS = (
    NOME_EMPRESA,
    NOME_CAMPANHA,
    NOME_ANUNCIO,
    ID_META_CONTA,
    ID_META_CAMPANHA,
    "990000000000001",
    str(VALOR_MONETARIO),
    "1.234,56",
    TOKEN,
    "Unsupported get request",
    "Campanha indisponível",
    "AbCdEfGhIjKlMnOpQrStUv0",
)


class ErroMetaFicticio(Exception):
    """Exceção cuja mensagem repete a da Meta, como faria um cliente
    descuidado."""


@pytest.fixture
def saida() -> Iterator[io.StringIO]:
    raiz = logging.getLogger()
    handlers_originais = raiz.handlers[:]
    nivel_original = raiz.level
    ultimo_recurso_original = logging.lastResort
    fluxo = io.StringIO()
    configurar_log(fluxo)
    yield fluxo
    raiz.handlers[:] = handlers_originais
    raiz.setLevel(nivel_original)
    logging.lastResort = ultimo_recurso_original
    logging.captureWarnings(False)


def ler_linhas(fluxo: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(linha) for linha in fluxo.getvalue().splitlines()]


def emitir_por_todos_os_caminhos() -> None:
    """Exercita o uso correto e os descuidados: mensagem livre com args,
    traceback, campos fora da lista, campos da lista com valor indevido e
    um logger de terceiros com URL e token."""
    registrar_evento(
        "falha",
        etapa="extrair",
        linhas=10,
        tentativas=3,
        duracao_ms=1500,
        codigo_erro=100,
        subcodigo_erro=33,
        nivel=logging.ERROR,
    )
    etl = logging.getLogger("etl")
    etl.error("Falha na campanha %s da empresa %s", NOME_CAMPANHA, NOME_EMPRESA)
    etl.info(f"Anúncio {NOME_ANUNCIO} gastou {VALOR_MONETARIO}")
    try:
        raise ErroMetaFicticio(ERRO_META["error"]["error_user_msg"])
    except ErroMetaFicticio:
        etl.exception("Erro da Meta", stack_info=True)
    etl.warning(
        "campos fora da lista",
        extra={
            "erro_meta": ERRO_META,
            "conta": ID_META_CONTA,
            "investimento": VALOR_MONETARIO,
            "token": TOKEN,
        },
    )
    etl.warning(
        "campos da lista com valor indevido",
        extra={
            "etapa": NOME_CAMPANHA,
            "status": NOME_ANUNCIO,
            "linhas": VALOR_MONETARIO,
            "duracao_ms": int(ID_META_CAMPANHA),
            "tentativas": float(VALOR_MONETARIO),
            "codigo_erro": ID_META_CAMPANHA,
            "subcodigo_erro": True,
            "execucao_id": ID_META_CONTA,
            "empresa_id": NOME_EMPRESA,
            "tipo_execucao": TOKEN,
        },
    )
    logging.getLogger("urllib3.connectionpool").warning(
        "Retrying after connection broken: /v23.0/%s/insights?access_token=%s",
        ID_META_CONTA,
        TOKEN,
    )


def test_nenhum_log_contem_dado_de_empresa(saida: io.StringIO) -> None:
    """Critério de aceite do RNF-17."""
    with contexto_execucao(EXECUCAO_ID, EMPRESA_ID, "diaria"):
        emitir_por_todos_os_caminhos()

    texto = saida.getvalue()
    assert texto
    for dado in DADOS_SENSIVEIS:
        assert dado not in texto
    for linha in ler_linhas(saida):
        assert set(linha) <= CAMPOS_PERMITIDOS


def test_valores_indevidos_em_campos_permitidos_sao_omitidos(
    saida: io.StringIO,
) -> None:
    with contexto_execucao(EXECUCAO_ID, EMPRESA_ID, "diaria"):
        emitir_por_todos_os_caminhos()

    linha_indevida = ler_linhas(saida)[5]
    assert set(linha_indevida) == {
        "instante",
        "nivel",
        "execucao_id",
        "empresa_id",
        "tipo_execucao",
    }
    assert linha_indevida["execucao_id"] == str(EXECUCAO_ID)
    assert linha_indevida["empresa_id"] == str(EMPRESA_ID)
    assert linha_indevida["tipo_execucao"] == "diaria"


def test_erro_da_meta_com_nome_de_campanha_nao_chega_ao_log(saida: io.StringIO) -> None:
    erro = ERRO_META["error"]
    with contexto_execucao(EXECUCAO_ID, EMPRESA_ID, "horaria"):
        try:
            raise ErroMetaFicticio(json.dumps(ERRO_META, ensure_ascii=False))
        except ErroMetaFicticio:
            logging.getLogger("etl.extracao").exception(
                "Erro da Meta: %s", erro["error_user_msg"], extra={"erro": erro}
            )
            registrar_evento(
                "falha",
                etapa="extrair",
                codigo_erro=erro["code"],
                subcodigo_erro=erro["error_subcode"],
                nivel=logging.ERROR,
            )

    texto = saida.getvalue()
    assert NOME_CAMPANHA not in texto
    assert "campanha" not in texto.lower()
    assert erro["message"] not in texto
    assert ID_META_CAMPANHA not in texto
    linha_codigos = ler_linhas(saida)[1]
    assert linha_codigos["codigo_erro"] == 100
    assert linha_codigos["subcodigo_erro"] == 33
    assert linha_codigos["status"] == "falha"
    assert linha_codigos["nivel"] == "ERROR"


def test_toda_linha_de_log_tem_execucao_id(saida: io.StringIO) -> None:
    with contexto_execucao(EXECUCAO_ID, EMPRESA_ID, "diaria"):
        emitir_por_todos_os_caminhos()
        with contexto_execucao(OUTRA_EXECUCAO_ID, EMPRESA_ID, "historica"):
            registrar_evento("em_andamento", etapa="carregar")
        registrar_evento("sucesso", etapa="carregar", linhas=0)
    # Fora de uma execução não há a quem atribuir a linha, que é descartada.
    logging.getLogger("etl").error("sem execução")
    logging.getLogger("psycopg").warning("sem execução")

    linhas = ler_linhas(saida)
    assert len(linhas) == 9
    for linha in linhas:
        assert UUID(str(linha["execucao_id"]))
        assert linha["empresa_id"] == str(EMPRESA_ID)
    assert [linha["execucao_id"] for linha in linhas[-2:]] == [
        str(OUTRA_EXECUCAO_ID),
        str(EXECUCAO_ID),
    ]


def test_registrar_evento_fora_de_execucao_falha(saida: io.StringIO) -> None:
    with pytest.raises(RuntimeError, match="fora de uma execução"):
        registrar_evento("sucesso")

    assert saida.getvalue() == ""


def test_registra_campos_completos_em_json(saida: io.StringIO) -> None:
    with contexto_execucao(EXECUCAO_ID, EMPRESA_ID, "historica"):
        registrar_evento(
            "sucesso",
            etapa="carregar",
            linhas=42,
            tentativas=1,
            duracao_ms=250,
        )

    [linha] = ler_linhas(saida)
    assert linha == {
        "instante": linha["instante"],
        "nivel": "INFO",
        "execucao_id": str(EXECUCAO_ID),
        "empresa_id": str(EMPRESA_ID),
        "tipo_execucao": "historica",
        "etapa": "carregar",
        "status": "sucesso",
        "linhas": 42,
        "tentativas": 1,
        "duracao_ms": 250,
    }
    assert str(linha["instante"]).endswith("+00:00")


def test_registra_a_retencao_so_com_a_contagem(saida: io.StringIO) -> None:
    with contexto_execucao(EXECUCAO_ID, EMPRESA_ID, "diaria"):
        registrar_evento("em_andamento", etapa="reter", linhas=3)

    [linha] = ler_linhas(saida)
    assert linha == {
        "instante": linha["instante"],
        "nivel": "INFO",
        "execucao_id": str(EXECUCAO_ID),
        "empresa_id": str(EMPRESA_ID),
        "tipo_execucao": "diaria",
        "etapa": "reter",
        "status": "em_andamento",
        "linhas": 3,
    }


@pytest.mark.parametrize(
    ("argumentos", "campo"),
    [
        ({"status": NOME_CAMPANHA}, "status"),
        ({"status": "sucesso", "etapa": NOME_ANUNCIO}, "etapa"),
        ({"status": "sucesso", "linhas": -1}, "linhas"),
        ({"status": "sucesso", "linhas": VALOR_MONETARIO}, "linhas"),
        ({"status": "sucesso", "tentativas": 1.5}, "tentativas"),
        ({"status": "sucesso", "duracao_ms": True}, "duracao_ms"),
        ({"status": "falha", "codigo_erro": ID_META_CAMPANHA}, "codigo_erro"),
        ({"status": "falha", "subcodigo_erro": -33}, "subcodigo_erro"),
        ({"status": "falha", "codigo_erro": int(ID_META_CAMPANHA)}, "codigo_erro"),
    ],
)
def test_registrar_evento_recusa_valor_indevido_sem_ecoa_lo(
    saida: io.StringIO, argumentos: dict[str, object], campo: str
) -> None:
    with (
        contexto_execucao(EXECUCAO_ID, EMPRESA_ID, "diaria"),
        pytest.raises(ValueError, match=campo) as erro,
    ):
        registrar_evento(**argumentos)

    for valor in argumentos.values():
        assert str(valor) not in str(erro.value)
    assert saida.getvalue() == ""


def test_registrar_evento_recusa_campo_fora_da_lista(saida: io.StringIO) -> None:
    with contexto_execucao(EXECUCAO_ID, EMPRESA_ID, "diaria"), pytest.raises(TypeError):
        registrar_evento("sucesso", campanha=NOME_CAMPANHA)

    assert saida.getvalue() == ""


@pytest.mark.parametrize(
    ("execucao_id", "empresa_id", "tipo_execucao", "excecao", "campo"),
    [
        (str(EXECUCAO_ID), EMPRESA_ID, "diaria", TypeError, "execucao_id"),
        (EXECUCAO_ID, ID_META_CONTA, "diaria", TypeError, "empresa_id"),
        (EXECUCAO_ID, EMPRESA_ID, NOME_EMPRESA, ValueError, "tipo_execucao"),
    ],
)
def test_contexto_execucao_recusa_valor_indevido_sem_ecoa_lo(
    execucao_id: object,
    empresa_id: object,
    tipo_execucao: str,
    excecao: type[Exception],
    campo: str,
) -> None:
    with (
        pytest.raises(excecao, match=campo) as erro,
        contexto_execucao(execucao_id, empresa_id, tipo_execucao),
    ):
        pass

    assert ID_META_CONTA not in str(erro.value)
    assert NOME_EMPRESA not in str(erro.value)


def test_contexto_execucao_restaura_o_anterior_apos_excecao(saida: io.StringIO) -> None:
    with contexto_execucao(EXECUCAO_ID, EMPRESA_ID, "diaria"):
        with (
            pytest.raises(ErroMetaFicticio),
            contexto_execucao(OUTRA_EXECUCAO_ID, EMPRESA_ID, "diaria"),
        ):
            raise ErroMetaFicticio
        registrar_evento("falha")

    assert ler_linhas(saida)[0]["execucao_id"] == str(EXECUCAO_ID)


def test_configurar_log_substitui_handlers_e_fixa_nivel_info(
    saida: io.StringIO,
) -> None:
    raiz = logging.getLogger()
    raiz.addHandler(logging.StreamHandler(io.StringIO()))
    fluxo = io.StringIO()

    configurar_log(fluxo)
    with contexto_execucao(EXECUCAO_ID, EMPRESA_ID, "diaria"):
        logging.getLogger("urllib3").debug("Starting new HTTPS connection")
        logging.getLogger("urllib3").info("Starting new HTTPS connection")

    assert len(raiz.handlers) == 1
    assert raiz.level == logging.INFO
    assert [linha["nivel"] for linha in ler_linhas(fluxo)] == ["INFO"]


class FluxoQuebrado(io.StringIO):
    def write(self, texto: str) -> int:
        raise OSError("pipe quebrado")


def test_falha_de_escrita_nao_imprime_mensagem_nem_args(
    saida: io.StringIO, capsys: pytest.CaptureFixture[str]
) -> None:
    configurar_log(FluxoQuebrado())
    with contexto_execucao(EXECUCAO_ID, EMPRESA_ID, "diaria"):
        logging.getLogger("etl").error("Campanha %s, token %s", NOME_CAMPANHA, TOKEN)

    erro = capsys.readouterr().err
    assert "conteúdo omitido" in erro
    assert NOME_CAMPANHA not in erro
    assert TOKEN not in erro


def test_logger_sem_handler_nao_cai_no_ultimo_recurso(
    saida: io.StringIO, capsys: pytest.CaptureFixture[str]
) -> None:
    isolado = logging.getLogger("terceiro.isolado")
    isolado.propagate = False
    try:
        with contexto_execucao(EXECUCAO_ID, EMPRESA_ID, "diaria"):
            isolado.warning("Campanha %s", NOME_CAMPANHA)
    finally:
        isolado.propagate = True

    capturado = capsys.readouterr()
    assert NOME_CAMPANHA not in capturado.err + capturado.out + saida.getvalue()


def test_aviso_do_modulo_warnings_passa_pelo_formatador(
    saida: io.StringIO, capsys: pytest.CaptureFixture[str]
) -> None:
    with (
        contexto_execucao(EXECUCAO_ID, EMPRESA_ID, "diaria"),
        warnings.catch_warnings(),
    ):
        warnings.simplefilter("always")
        warnings.warn(f"/v23.0/{ID_META_CONTA}?access_token={TOKEN}", stacklevel=1)

    capturado = capsys.readouterr()
    assert TOKEN not in capturado.err + saida.getvalue()
    assert ID_META_CONTA not in capturado.err + saida.getvalue()
    [linha] = ler_linhas(saida)
    assert linha["nivel"] == "WARNING"
    assert linha["execucao_id"] == str(EXECUCAO_ID)
