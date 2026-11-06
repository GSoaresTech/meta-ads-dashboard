-- Catálogo de métricas para o painel: o rótulo, a explicação e a unidade de
-- cada métrica, que a tela não guarda em lugar nenhum (RF-30; ADR-0007;
-- ADR-0009 §4). As colunas são as que a tela exibe; fórmula e aditividade
-- entram com a visão que as usar.
--
-- O catálogo é global, sem dado de empresa, e por isso a função não recebe
-- p_empresa_id. Credencial inválida ou revogada devolve zero linhas, sem erro,
-- como nas demais funções de leitura. A ordem é a do rótulo, para que os
-- cartões não mudem de lugar entre as chamadas.
CREATE FUNCTION analitico.listar_metricas(p_credencial text)
RETURNS TABLE (codigo text, rotulo text, explicacao text, unidade text)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
#variable_conflict use_column
BEGIN
  IF NOT EXISTS (SELECT FROM normalizado.resolver_credencial(p_credencial)) THEN
    RETURN;
  END IF;

  RETURN QUERY
  SELECT metrica.codigo, metrica.rotulo, metrica.explicacao, metrica.unidade
  FROM normalizado.metrica AS metrica
  ORDER BY metrica.rotulo;
END
$$;

REVOKE ALL ON FUNCTION analitico.listar_metricas(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analitico.listar_metricas(text) TO painel_leitor;
