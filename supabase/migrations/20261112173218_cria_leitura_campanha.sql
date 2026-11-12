-- A leitura da campanha em foco, para a visão dela: o objetivo e o status em
-- rótulo de negócio, o resultado principal e o KPI resolvidos, com a
-- sobrescrita aplicada, e as métricas de apoio da regra do catálogo, na ordem
-- de exibição (REQUIREMENTS §3.1; RF-31; ADR-0007; ADR-0009 §4). Nenhuma outra
-- função de analitico expõe as métricas de apoio, e sem elas a tela não tem
-- de onde lê-las.
--
-- As métricas de apoio vêm da regra mesmo com sobrescrita, que troca só o
-- resultado e o KPI (ADR-0009 §4). A campanha "Não classificado" tem o
-- objetivo e o apoio da regra sem objetivo, e as regras sem resultado
-- principal devolvem o resultado e o KPI nulos. Tudo sai como código do
-- catálogo, de onde o painel lê o rótulo, a explicação e a unidade, e nenhum
-- valor de enum da API sai da função (RF-37).
--
-- Campanha nula levanta 22023. Credencial inválida, revogada ou de outra
-- empresa, e campanha que não é da empresa, devolvem zero linhas, sem erro
-- (RF-46). O operador lê qualquer empresa (ADR-0004).
CREATE FUNCTION analitico.obter_campanha(
  p_credencial text,
  p_empresa_id uuid,
  p_campanha_id uuid
)
RETURNS TABLE (
  objetivo text,
  status text,
  metrica_resultado text,
  metrica_kpi text,
  metricas_apoio text[]
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
#variable_conflict use_column
BEGIN
  IF p_campanha_id IS NULL THEN
    RAISE EXCEPTION 'a campanha é obrigatória' USING ERRCODE = 'invalid_parameter_value';
  END IF;

  IF NOT EXISTS (
    SELECT FROM normalizado.resolver_credencial(p_credencial) AS credencial
    WHERE credencial.escopo = 'operador' OR credencial.empresa_id = p_empresa_id
  ) THEN
    RETURN;
  END IF;

  RETURN QUERY
  SELECT
    regra.nome_objetivo,
    rotulo.rotulo,
    resolvido.metrica_resultado,
    resolvido.metrica_kpi,
    ARRAY(
      SELECT apoio.metrica
      FROM normalizado.metrica_apoio_resultado AS apoio
      WHERE apoio.resultado_objetivo_id = regra.id
      ORDER BY apoio.ordem
    )
  FROM normalizado.resolver_resultado_campanha(p_empresa_id) AS resolvido
  JOIN normalizado.campanha AS campanha
    ON campanha.empresa_id = p_empresa_id AND campanha.id = resolvido.campanha_id
  JOIN normalizado.resultado_objetivo AS regra ON regra.id = resolvido.resultado_objetivo_id
  LEFT JOIN normalizado.rotulo_valor_api AS rotulo
    ON rotulo.dominio = 'status' AND rotulo.valor = campanha.status
  WHERE resolvido.campanha_id = p_campanha_id;
END
$$;

REVOKE ALL ON FUNCTION analitico.obter_campanha(text, uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analitico.obter_campanha(text, uuid, uuid) TO painel_leitor;
