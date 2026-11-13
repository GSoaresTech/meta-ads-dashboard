-- Sentido de melhora de cada métrica: a variação em relação ao período
-- anterior é melhora na alta ou na queda conforme a métrica, e isso é dado do
-- catálogo, não regra da tela (RF-27; ADR-0007; ADR-0021). Todo custo melhora
-- na queda. O investimento e a frequência são indiferentes: gastar mais ou
-- repetir mais o anúncio depende do plano da campanha, e a tela mostra a
-- variação deles sem avaliá-la.
--
-- A coluna não tem valor padrão: uma métrica nova entra no catálogo com o
-- sentido escolhido, nunca com um herdado sem querer.
ALTER TABLE normalizado.metrica
  ADD COLUMN sentido_melhora text,
  ADD CONSTRAINT metrica_sentido_melhora_check CHECK (sentido_melhora IN ('alta', 'queda', 'indiferente'));

UPDATE normalizado.metrica
SET sentido_melhora = CASE
  WHEN codigo IN ('investimento', 'frequencia') THEN 'indiferente'
  WHEN tipo = 'derivada' AND numerador = 'investimento' THEN 'queda'
  ELSE 'alta'
END;

ALTER TABLE normalizado.metrica ALTER COLUMN sentido_melhora SET NOT NULL;

-- O retorno ganha uma coluna, e o Postgres não troca o tipo de retorno com
-- CREATE OR REPLACE. O corpo e os privilégios são os da criação.
DROP FUNCTION analitico.listar_metricas(text);

CREATE FUNCTION analitico.listar_metricas(p_credencial text)
RETURNS TABLE (codigo text, rotulo text, explicacao text, unidade text, sentido_melhora text)
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
  SELECT metrica.codigo, metrica.rotulo, metrica.explicacao, metrica.unidade, metrica.sentido_melhora
  FROM normalizado.metrica AS metrica
  ORDER BY metrica.rotulo;
END
$$;

REVOKE ALL ON FUNCTION analitico.listar_metricas(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analitico.listar_metricas(text) TO painel_leitor;
