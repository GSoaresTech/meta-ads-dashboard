-- Operandos das métricas derivadas: a razão que a fórmula descreve passa a
-- ser dado do catálogo, como a origem das métricas base e de ação. Assim as
-- funções de analitico calculam CTR, CPC e custo por resultado a partir das
-- somas do recorte sem repetir a fórmula no código, e uma derivada nova
-- entra só com linhas no catálogo (ADR-0007; ADR-0009 §2; REQUIREMENTS §7.1).
--
-- A derivada vale numerador ÷ denominador × fator. O percentual sai como
-- fração, que a formatação pt-BR exibe multiplicada por 100 (RF-35), então o
-- fator do CTR é 1, e o "× 100" da fórmula descreve a exibição.
ALTER TABLE normalizado.metrica
  ADD COLUMN numerador text,
  ADD COLUMN denominador text,
  ADD COLUMN fator numeric;

UPDATE normalizado.metrica AS metrica
SET numerador = operando.numerador,
    denominador = operando.denominador,
    fator = operando.fator
FROM (
  VALUES
    ('frequencia', 'impressoes', 'alcance', 1),
    ('ctr', 'cliques_link', 'impressoes', 1),
    ('cpc', 'investimento', 'cliques_link', 1),
    ('cpm', 'investimento', 'impressoes', 1000),
    ('custo_mil_alcance', 'investimento', 'alcance', 1000),
    ('custo_visualizacao_pagina', 'investimento', 'visualizacoes_pagina_destino', 1),
    ('custo_conversa', 'investimento', 'conversas_iniciadas', 1),
    ('custo_cadastro', 'investimento', 'cadastros', 1),
    ('custo_compra', 'investimento', 'compras', 1),
    ('roas', 'valor_compras', 'investimento', 1),
    ('custo_interacao', 'investimento', 'interacoes_publicacao', 1)
) AS operando (codigo, numerador, denominador, fator)
WHERE metrica.codigo = operando.codigo;

-- As restrições entram depois do UPDATE, porque a nova amarração do tipo à
-- origem recusa a derivada sem operandos.
ALTER TABLE normalizado.metrica
  ADD CONSTRAINT metrica_numerador_fkey FOREIGN KEY (numerador) REFERENCES normalizado.metrica (codigo),
  ADD CONSTRAINT metrica_denominador_fkey FOREIGN KEY (denominador) REFERENCES normalizado.metrica (codigo),
  ADD CONSTRAINT metrica_fator_check CHECK (fator > 0),
  DROP CONSTRAINT metrica_origem_check,
  ADD CONSTRAINT metrica_origem_check CHECK (
    CASE tipo
      WHEN 'base' THEN campo_base IS NOT NULL AND num_nulls(tipo_acao, medida_acao, numerador, denominador, fator) = 5
      WHEN 'acao' THEN
        tipo_acao IS NOT NULL AND medida_acao IS NOT NULL AND num_nulls(campo_base, numerador, denominador, fator) = 4
      ELSE num_nulls(campo_base, tipo_acao, medida_acao) = 3 AND num_nonnulls(numerador, denominador, fator) = 3
    END
  );
