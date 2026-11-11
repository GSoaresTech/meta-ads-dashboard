-- Classificação das combinações de objetivo e meta de otimização sem linha
-- própria no catálogo, a partir das combinações observadas nas contas
-- verificadas e do resultado que a Meta conta em results (REQUIREMENTS §7.2;
-- R-24; R-40; ADR-0007). O critério de cada regra:
-- - o resultado que a Meta conta vem em actions: a regra usa a métrica dele;
-- - vem só em outro campo, que a ETL não extrai: a regra usa um substituto
--   medido, quando há um próximo, ou fica sem resultado principal, para que
--   o painel mostre "—" em vez do número de outra coisa;
-- - o objetivo legado de mais de um equivalente, que depende do evento ou
--   do destino do conjunto, ganha regra própria sem resultado principal. A regra fica no
--   próprio objetivo legado, e a equivalência continua 1:1;
-- - o objetivo legado sem equivalente oficial continua "Não classificado".

-- Promoção de app: as instalações, pelo tipo agrupado da referência das
-- ações (R-21). O indicator dessas campanhas em results é a confirmar.
INSERT INTO normalizado.metrica
  (codigo, rotulo, explicacao, formula, unidade, aditiva, tipo, campo_base, tipo_acao, medida_acao,
   numerador, denominador, fator)
VALUES
  ('instalacoes_app', 'Instalações do app',
   'Quantas vezes o aplicativo foi instalado a partir dos anúncios.',
   'soma', 'quantidade', true, 'acao', NULL, 'omni_app_install', 'quantidade', NULL, NULL, NULL),
  ('custo_instalacao', 'Custo por instalação',
   'Quanto custou, em média, cada instalação do aplicativo.',
   'investimento ÷ instalações do app', 'moeda', false, 'derivada', NULL, NULL, NULL,
   'investimento', 'instalacoes_app', 1);

UPDATE normalizado.resultado_objetivo
SET metrica_resultado = 'instalacoes_app', metrica_kpi = 'custo_instalacao'
WHERE objetivo = 'OUTCOME_APP_PROMOTION' AND meta_otimizacao IS NULL;

-- Com resultado, a regra tem as métricas de apoio das demais, sem o
-- investimento, que o painel sempre mostra.
DELETE FROM normalizado.metrica_apoio_resultado
WHERE resultado_objetivo_id = (
  SELECT id FROM normalizado.resultado_objetivo
  WHERE objetivo = 'OUTCOME_APP_PROMOTION' AND meta_otimizacao IS NULL
);
INSERT INTO normalizado.metrica_apoio_resultado (resultado_objetivo_id, metrica, ordem)
SELECT regra.id, apoio.metrica, apoio.ordem::smallint
FROM normalizado.resultado_objetivo AS regra
CROSS JOIN LATERAL unnest(ARRAY['cliques_link', 'ctr', 'cpm']) WITH ORDINALITY AS apoio (metrica, ordem)
WHERE regra.objetivo = 'OUTCOME_APP_PROMOTION' AND regra.meta_otimizacao IS NULL;

-- Os cliques no link passam a ser o resultado das campanhas de visita ao
-- perfil, e a explicação diz que eles também levam ao perfil.
UPDATE normalizado.metrica
SET explicacao = 'Cliques que levaram a pessoa para fora do anúncio: site, WhatsApp, perfil do Instagram, formulário ou loja.'
WHERE codigo = 'cliques_link';

-- As regras novas, com as métricas de apoio na ordem de exibição:
-- - conversas em Tráfego: o resultado vem em actions, como nos demais
--   objetivos otimizados para conversas;
-- - visitas ao perfil: a Meta conta profile_visit_view, que só vem dentro de
--   results. Os cliques no link são o substituto: 98% das visitas no
--   agregado das contas verificadas;
-- - ThruPlay e conversões no site: os campos que a Meta conta ficam fora de
--   actions, e nenhum tipo de ação se aproxima deles;
-- - CONVERSIONS e VIDEO_VIEWS: o equivalente depende do evento do objeto
--   promovido ou do destino do conjunto, que o catálogo não guarda. O apoio traz os resultados
--   possíveis.
WITH regra (objetivo, meta_otimizacao, nome_objetivo, metrica_resultado, metrica_kpi, apoio) AS (
  VALUES
    ('OUTCOME_TRAFFIC', 'CONVERSATIONS', 'Tráfego para conversas', 'conversas_iniciadas', 'custo_conversa',
     ARRAY['cliques_link', 'ctr', 'cpm']),
    ('OUTCOME_TRAFFIC', 'VISIT_INSTAGRAM_PROFILE', 'Visitas ao perfil', 'cliques_link', 'cpc',
     ARRAY['ctr', 'cpm', 'alcance']),
    ('OUTCOME_TRAFFIC', 'PROFILE_VISIT', 'Visitas ao perfil', 'cliques_link', 'cpc',
     ARRAY['ctr', 'cpm', 'alcance']),
    ('OUTCOME_ENGAGEMENT', 'THRUPLAY', 'Visualizações de vídeo', NULL, NULL,
     ARRAY['alcance', 'impressoes', 'cpm']),
    ('OUTCOME_ENGAGEMENT', 'OFFSITE_CONVERSIONS', 'Conversões no site', NULL, NULL,
     ARRAY['cliques_link', 'visualizacoes_pagina_destino', 'ctr']),
    ('CONVERSIONS', NULL, 'Conversões (objetivo antigo)', NULL, NULL,
     ARRAY['cadastros', 'compras', 'cliques_link']),
    ('VIDEO_VIEWS', NULL, 'Visualizações de vídeo (objetivo antigo)', NULL, NULL,
     ARRAY['alcance', 'impressoes', 'cpm'])
),
inserida AS (
  INSERT INTO normalizado.resultado_objetivo
    (objetivo, meta_otimizacao, nome_objetivo, metrica_resultado, metrica_kpi)
  SELECT objetivo, meta_otimizacao, nome_objetivo, metrica_resultado, metrica_kpi
  FROM regra
  RETURNING id, objetivo, meta_otimizacao
)
INSERT INTO normalizado.metrica_apoio_resultado (resultado_objetivo_id, metrica, ordem)
SELECT i.id, apoio.metrica, apoio.ordem::smallint
FROM inserida AS i
JOIN regra AS r ON (r.objetivo, r.meta_otimizacao) IS NOT DISTINCT FROM (i.objetivo, i.meta_otimizacao)
CROSS JOIN LATERAL unnest(r.apoio) WITH ORDINALITY AS apoio (metrica, ordem);
