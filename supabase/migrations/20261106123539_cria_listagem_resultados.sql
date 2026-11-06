-- Tipos de resultado de uma empresa num intervalo: o resultado principal das
-- campanhas com entrega, em cada moeda, que escolhe os totais de resultado da
-- visão Geral (REQUIREMENTS §3.1 e §3.3; RF-34; ADR-0009 §4; ADR-0013).
--
-- O resultado é o da resolução do ADR-0007, com a sobrescrita aplicada, e a
-- campanha sem resultado no catálogo não gera linha. A entrega é a mesma do
-- obter_desempenho: ter dia de métrica no intervalo. A função escolhe só os
-- tipos: o total de cada um continua sendo o do obter_desempenho, que soma
-- todas as campanhas da moeda (RF-32).
--
-- Parâmetro fora do domínio levanta 22023. Credencial inválida, revogada ou
-- de outra empresa devolve zero linhas, sem erro (RF-46). O operador lê
-- qualquer empresa (ADR-0004).
CREATE FUNCTION analitico.listar_resultados(
  p_credencial text,
  p_empresa_id uuid,
  p_inicio date,
  p_fim date
)
RETURNS TABLE (moeda text, metrica text)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
#variable_conflict use_column
BEGIN
  IF p_inicio IS NULL OR p_fim IS NULL OR p_inicio > p_fim THEN
    RAISE EXCEPTION 'intervalo inválido' USING ERRCODE = 'invalid_parameter_value';
  END IF;

  IF NOT EXISTS (
    SELECT FROM normalizado.resolver_credencial(p_credencial) AS credencial
    WHERE credencial.escopo = 'operador' OR credencial.empresa_id = p_empresa_id
  ) THEN
    RETURN;
  END IF;

  RETURN QUERY
  WITH campanha_com_entrega AS (
    SELECT DISTINCT conjunto.campanha_id
    FROM normalizado.metrica_diaria_anuncio AS diaria
    JOIN normalizado.anuncio AS anuncio
      ON anuncio.empresa_id = diaria.empresa_id AND anuncio.id = diaria.anuncio_id
    JOIN normalizado.conjunto_anuncio AS conjunto
      ON conjunto.empresa_id = anuncio.empresa_id AND conjunto.id = anuncio.conjunto_anuncio_id
    WHERE diaria.empresa_id = p_empresa_id
      AND diaria.data BETWEEN p_inicio AND p_fim
  )
  SELECT DISTINCT conta.moeda, resultado.metrica_resultado
  FROM normalizado.resolver_resultado_campanha(p_empresa_id) AS resultado
  JOIN campanha_com_entrega ON campanha_com_entrega.campanha_id = resultado.campanha_id
  JOIN normalizado.campanha AS campanha
    ON campanha.empresa_id = p_empresa_id AND campanha.id = resultado.campanha_id
  JOIN normalizado.conta_anuncio AS conta
    ON conta.empresa_id = campanha.empresa_id AND conta.id = campanha.conta_anuncio_id
  WHERE resultado.metrica_resultado IS NOT NULL
  ORDER BY conta.moeda, resultado.metrica_resultado;
END
$$;

REVOKE ALL ON FUNCTION analitico.listar_resultados(text, uuid, date, date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analitico.listar_resultados(text, uuid, date, date) TO painel_leitor;
