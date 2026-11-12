-- Visitas ao perfil, ThruPlay e contato no site pelo valor que a Meta conta
-- em results (REQUIREMENTS §7.2; R-24; ADR-0007). A ETL passou a extrair os
-- três, fora de actions, e a gravá-los na tabela longa das ações com o
-- indicator de results como tipo, com ponto no lugar dos dois-pontos, que o
-- formato do tipo de ação não aceita (ADR-0009 §2):
-- - profile_visit_view, que só vem dentro de results;
-- - video_thruplay_watched_actions, do campo de mesmo nome;
-- - conversions.contact_website, do item contact_website do campo
--   conversions.
-- As três viram métricas de ação, com o custo de cada uma como KPI, e as
-- regras que usavam o substituto ou ficavam sem resultado principal passam a
-- usá-las.
INSERT INTO normalizado.metrica
  (codigo, rotulo, explicacao, formula, unidade, aditiva, tipo, campo_base, tipo_acao, medida_acao,
   numerador, denominador, fator)
VALUES
  ('visitas_perfil', 'Visitas ao perfil',
   'Quantas vezes o perfil no Instagram ou a Página no Facebook foi visitado a partir dos anúncios.',
   'soma', 'quantidade', true, 'acao', NULL, 'profile_visit_view', 'quantidade', NULL, NULL, NULL),
  ('custo_visita_perfil', 'Custo por visita ao perfil',
   'Quanto custou, em média, cada visita ao perfil.',
   'investimento ÷ visitas ao perfil', 'moeda', false, 'derivada', NULL, NULL, NULL,
   'investimento', 'visitas_perfil', 1),
  ('visualizacoes_thruplay', 'Visualizações do vídeo (ThruPlay)',
   'Quantas vezes o vídeo foi assistido até o fim ou por pelo menos 15 segundos.',
   'soma', 'quantidade', true, 'acao', NULL, 'video_thruplay_watched_actions', 'quantidade', NULL, NULL, NULL),
  ('custo_thruplay', 'Custo por ThruPlay',
   'Quanto custou, em média, cada vez que o vídeo foi assistido até o fim ou por pelo menos 15 segundos.',
   'investimento ÷ visualizações do vídeo', 'moeda', false, 'derivada', NULL, NULL, NULL,
   'investimento', 'visualizacoes_thruplay', 1),
  ('contatos_site', 'Contatos pelo site',
   'Quantas vezes alguém entrou em contato com a empresa pelo site depois do anúncio, por telefone, e-mail ou chat.',
   'soma', 'quantidade', true, 'acao', NULL, 'conversions.contact_website', 'quantidade', NULL, NULL, NULL),
  ('custo_contato_site', 'Custo por contato pelo site',
   'Quanto custou, em média, cada contato pelo site.',
   'investimento ÷ contatos pelo site', 'moeda', false, 'derivada', NULL, NULL, NULL,
   'investimento', 'contatos_site', 1);

-- As métricas de apoio dessas regras não mudam: nenhuma delas repete o
-- resultado nem o KPI novos.
UPDATE normalizado.resultado_objetivo AS regra
SET metrica_resultado = nova.metrica_resultado, metrica_kpi = nova.metrica_kpi
FROM (
  VALUES
    ('OUTCOME_TRAFFIC', 'PROFILE_VISIT', 'visitas_perfil', 'custo_visita_perfil'),
    ('OUTCOME_TRAFFIC', 'VISIT_INSTAGRAM_PROFILE', 'visitas_perfil', 'custo_visita_perfil'),
    ('OUTCOME_ENGAGEMENT', 'THRUPLAY', 'visualizacoes_thruplay', 'custo_thruplay'),
    ('OUTCOME_ENGAGEMENT', 'OFFSITE_CONVERSIONS', 'contatos_site', 'custo_contato_site')
) AS nova (objetivo, meta_otimizacao, metrica_resultado, metrica_kpi)
WHERE regra.objetivo = nova.objetivo AND regra.meta_otimizacao = nova.meta_otimizacao;

-- Os legados de mais de um equivalente trazem os resultados possíveis entre
-- as métricas de apoio (REQUIREMENTS §7.2): o ThruPlay no VIDEO_VIEWS, que
-- equivale a OUTCOME_ENGAGEMENT com destino no vídeo, e o contato no site no
-- CONVERSIONS, que equivale a OUTCOME_ENGAGEMENT com o evento de contato.
DELETE FROM normalizado.metrica_apoio_resultado
WHERE resultado_objetivo_id IN (
  SELECT id FROM normalizado.resultado_objetivo
  WHERE objetivo IN ('VIDEO_VIEWS', 'CONVERSIONS') AND meta_otimizacao IS NULL
);
INSERT INTO normalizado.metrica_apoio_resultado (resultado_objetivo_id, metrica, ordem)
SELECT regra.id, apoio.metrica, apoio.ordem::smallint
FROM normalizado.resultado_objetivo AS regra
JOIN (
  VALUES
    ('VIDEO_VIEWS', ARRAY['visualizacoes_thruplay', 'alcance', 'impressoes', 'cpm']),
    ('CONVERSIONS', ARRAY['cadastros', 'compras', 'contatos_site', 'cliques_link'])
) AS nova (objetivo, metricas) ON nova.objetivo = regra.objetivo
CROSS JOIN LATERAL unnest(nova.metricas) WITH ORDINALITY AS apoio (metrica, ordem)
WHERE regra.meta_otimizacao IS NULL;
