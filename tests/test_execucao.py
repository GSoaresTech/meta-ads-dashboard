import pytest

from etl.cliente_api_meta import ErroApiMeta, ErroAutenticacao
from etl.execucao import (
    StatusExecucao,
    calcular_codigo_saida,
    descrever_erro,
    ler_codigos_erro,
)
from etl.log_estruturado import LIMITE_INTEIRO_LOG


class ErroSemMensagem(Exception):
    pass


def test_descricao_do_erro_traz_o_tipo_e_a_mensagem() -> None:
    erro = ErroAutenticacao(codigo=190, subcodigo=463)

    assert descrever_erro(erro) == f"ErroAutenticacao: {erro}"


def test_descricao_do_erro_sem_mensagem_traz_o_tipo() -> None:
    assert descrever_erro(ErroSemMensagem()) == "ErroSemMensagem"


def test_descricao_do_erro_nao_tem_espaco_nas_pontas() -> None:
    # O CHECK de execucao_carga.erro recusa espaço nas pontas.
    assert descrever_erro(ValueError("  \n")) == "ValueError"
    assert descrever_erro(ValueError(" falha \n")) == "ValueError: falha"


@pytest.mark.parametrize(
    ("status", "codigo"),
    [
        ([], 0),
        ([StatusExecucao.SUCESSO, StatusExecucao.SUCESSO], 0),
        # A ignorada é outro status no RF-19, e só a falha notifica (RF-50).
        ([StatusExecucao.SUCESSO, StatusExecucao.IGNORADA], 0),
        ([StatusExecucao.SUCESSO, StatusExecucao.FALHA], 1),
        ([StatusExecucao.FALHA, StatusExecucao.IGNORADA], 1),
    ],
)
def test_codigo_de_saida_e_diferente_de_zero_so_com_falha(
    status: list[StatusExecucao], codigo: int
) -> None:
    assert calcular_codigo_saida(status) == codigo


def test_descricao_do_erro_troca_o_nul_que_o_postgres_recusa() -> None:
    assert descrever_erro(ValueError("a\x00b")) == "ValueError: a\ufffdb"


def test_codigos_da_meta_vao_ao_log() -> None:
    erro = ErroAutenticacao(codigo=190, subcodigo=463)

    assert ler_codigos_erro(erro) == {"codigo_erro": 190, "subcodigo_erro": 463}


@pytest.mark.parametrize("codigo", [-1, LIMITE_INTEIRO_LOG])
def test_codigo_fora_do_dominio_do_log_e_descartado(codigo: int) -> None:
    erro = ErroApiMeta(codigo=codigo, subcodigo=33)

    assert ler_codigos_erro(erro) == {"subcodigo_erro": 33}


def test_erro_que_nao_e_da_meta_nao_tem_codigo() -> None:
    assert ler_codigos_erro(ErroApiMeta()) == {}
    assert ler_codigos_erro(ValueError("x")) == {}
