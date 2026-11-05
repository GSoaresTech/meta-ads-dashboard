-- Resolução da credencial de acesso ao painel: o banco recebe o token do
-- cookie como chegou, calcula o hash SHA-256 e procura a credencial. O painel
-- nunca envia o hash, e nenhuma das funções devolve o hash ou o token
-- (ADR-0004; ADR-0009 §4).

-- Devolve o escopo de uma credencial existente, não revogada e, no escopo de
-- empresa, de empresa ativa (RF-45, RF-48). Uma entrada que não é token de
-- nenhuma credencial, inclusive nula, devolve zero linhas, sem erro.
--
-- SECURITY INVOKER e sem grant: só as funções de analitico, donas do
-- postgres, a chamam (ADR-0009 §4).
CREATE FUNCTION normalizado.resolver_credencial(p_credencial text)
RETURNS TABLE (escopo text, empresa_id uuid)
LANGUAGE sql
STABLE
SET search_path = ''
AS $$
  SELECT credencial.escopo, credencial.empresa_id
  FROM normalizado.credencial_acesso AS credencial
  LEFT JOIN normalizado.empresa AS empresa ON empresa.id = credencial.empresa_id
  WHERE credencial.hash = sha256(convert_to(p_credencial, 'UTF8'))
    AND credencial.revogado_em IS NULL
    AND (credencial.escopo = 'operador' OR empresa.situacao = 'ativa')
$$;

REVOKE ALL ON FUNCTION normalizado.resolver_credencial(text) FROM PUBLIC;

-- A porta do painel: com zero linhas, a rota responde 404, sem revelar se a
-- empresa existe (RF-46).
CREATE FUNCTION analitico.resolver_acesso(p_credencial text)
RETURNS TABLE (escopo text, empresa_id uuid)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT credencial.escopo, credencial.empresa_id
  FROM normalizado.resolver_credencial(p_credencial) AS credencial
$$;

REVOKE ALL ON FUNCTION analitico.resolver_acesso(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analitico.resolver_acesso(text) TO painel_leitor;
