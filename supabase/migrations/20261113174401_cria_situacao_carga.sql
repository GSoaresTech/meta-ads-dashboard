-- Situação da carga: o instante da última carga bem-sucedida da empresa, que
-- o painel exibe e compara com o relógio dele para avisar do atraso (RF-28;
-- ADR-0009 §4).
--
-- Vale a execução de qualquer tipo terminada como sucesso: a horária, a
-- diária e a histórica gravam dados de uma vez, na transação da carga, e o
-- leitor só os vê depois do commit (ADR-0009 §5). O instante é o do fim, o
-- do registro gravado depois desse commit. A execução que falhou ou ficou
-- ignorada não escreveu dados, e a em andamento ainda não os confirmou.
--
-- Sai uma linha para a credencial com acesso, com instante nulo se a empresa
-- nunca teve carga bem-sucedida, e o painel distingue esse caso da carga
-- antiga. Credencial inválida, revogada ou de outra empresa devolve zero
-- linhas, sem erro (RF-46). O operador lê qualquer empresa (ADR-0004). A
-- função não lê a hora: o limite do atraso fica no painel, com o relógio
-- dele.
CREATE FUNCTION analitico.obter_situacao_carga(p_credencial text, p_empresa_id uuid)
RETURNS TABLE (ultima_carga_em timestamptz)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
#variable_conflict use_column
BEGIN
  IF NOT EXISTS (
    SELECT FROM normalizado.resolver_credencial(p_credencial) AS credencial
    WHERE credencial.escopo = 'operador' OR credencial.empresa_id = p_empresa_id
  ) THEN
    RETURN;
  END IF;

  RETURN QUERY
  SELECT max(execucao.terminado_em)
  FROM normalizado.execucao_carga AS execucao
  WHERE execucao.empresa_id = p_empresa_id
    AND execucao.status = 'sucesso';
END
$$;

REVOKE ALL ON FUNCTION analitico.obter_situacao_carga(text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analitico.obter_situacao_carga(text, uuid) TO painel_leitor;
