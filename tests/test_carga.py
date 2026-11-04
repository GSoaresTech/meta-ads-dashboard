from uuid import UUID, uuid4

from etl.carga import calcular_chave_lock

LIMITE_BIGINT = 2**63


def test_chave_do_lock_e_a_mesma_para_a_mesma_empresa() -> None:
    empresa_id = uuid4()

    assert calcular_chave_lock(empresa_id) == calcular_chave_lock(UUID(str(empresa_id)))


def test_chave_do_lock_cabe_no_bigint_do_postgres() -> None:
    maior = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    menor = UUID("00000000-0000-0000-0000-000000000000")

    for empresa_id in (maior, menor, uuid4()):
        assert -LIMITE_BIGINT <= calcular_chave_lock(empresa_id) < LIMITE_BIGINT


def test_chave_do_lock_difere_entre_empresas() -> None:
    chaves = {calcular_chave_lock(uuid4()) for _ in range(1000)}

    assert len(chaves) == 1000
