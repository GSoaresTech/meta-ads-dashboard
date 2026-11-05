-- Revogação da credencial de acesso ao painel, pela área do operador
-- (ADR-0004; ADR-0009 §4; RF-45).
--
-- Grava revogado_em e mantém a linha: a resolução deixa de achar a
-- credencial já na chamada seguinte, e a data fica para a lista de links.
-- Revogar de novo mantém a data da primeira revogação. Um ID que não é de
-- nenhuma credencial levanta P0002, para que um engano do operador não
-- passe como revogação feita.
CREATE FUNCTION analitico.revogar_credencial(p_credencial text, p_credencial_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  PERFORM normalizado.exigir_operador(p_credencial);

  -- Em READ COMMITTED, o UPDATE vê a credencial que outra sessão confirmou
  -- depois do início desta transação, e o now() fica antes do criado_em
  -- dela. O greatest mantém o CHECK revogado_em >= criado_em, que, violado,
  -- levaria a linha, com o hash, à mensagem de erro e ao log.
  UPDATE normalizado.credencial_acesso AS credencial
  SET revogado_em = coalesce(credencial.revogado_em, greatest(now(), credencial.criado_em))
  WHERE credencial.id = p_credencial_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'credencial não encontrada' USING ERRCODE = 'no_data_found';
  END IF;
END
$$;

REVOKE ALL ON FUNCTION analitico.revogar_credencial(text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analitico.revogar_credencial(text, uuid) TO painel_leitor;
