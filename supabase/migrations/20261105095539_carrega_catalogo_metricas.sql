-- Conteúdo inicial do catálogo, transcrito do REQUIREMENTS §7 com os enums
-- confirmados na API (R-40, R-41). Daqui em diante, este seed e as
-- migrations que o alterarem são a fonte da verdade do catálogo global, e o
-- REQUIREMENTS §7 aponta para eles (ADR-0007). É migration, e não o
-- supabase/seed.sql, porque o catálogo precisa existir também em produção.

-- Métricas. As de ação leem o tipo de ação como a API o entrega na tabela
-- longa (R-21); as derivadas são razões, recalculadas em analitico a partir
-- das somas do recorte e nunca somadas.
INSERT INTO normalizado.metrica
  (codigo, rotulo, explicacao, formula, unidade, aditiva, tipo, campo_base, tipo_acao, medida_acao)
VALUES
  ('investimento', 'Investimento',
   'Quanto foi gasto em anúncios no período.',
   'soma do investimento', 'moeda', true, 'base', 'investimento', NULL, NULL),
  ('impressoes', 'Impressões',
   'Quantas vezes os anúncios apareceram na tela das pessoas.',
   'soma das impressões', 'quantidade', true, 'base', 'impressoes', NULL, NULL),
  -- Pessoas únicas: nunca é somado entre dias nem entre entidades, e vem
  -- extraído por período (ADR-0006).
  ('alcance', 'Pessoas alcançadas',
   'Quantas pessoas diferentes viram os anúncios pelo menos uma vez. Não pode ser somado entre dias.',
   'valor extraído por período', 'quantidade', false, 'base', 'alcance', NULL, NULL),
  ('frequencia', 'Frequência',
   'Em média, quantas vezes cada pessoa alcançada viu os anúncios.',
   'impressões ÷ alcance, do mesmo período', 'razao', false, 'derivada', NULL, NULL, NULL),
  ('cliques_link', 'Cliques no link',
   'Cliques que levaram a pessoa para fora do anúncio: site, WhatsApp, formulário ou loja.',
   'soma', 'quantidade', true, 'acao', NULL, 'link_click', 'quantidade'),
  ('ctr', 'Taxa de cliques',
   'De cada 100 vezes que o anúncio apareceu, quantas viraram clique no link.',
   'cliques no link ÷ impressões × 100', 'percentual', false, 'derivada', NULL, NULL, NULL),
  ('cpc', 'Custo por clique',
   'Quanto custou, em média, cada clique no link.',
   'investimento ÷ cliques no link', 'moeda', false, 'derivada', NULL, NULL, NULL),
  ('cpm', 'Custo por mil impressões',
   'Quanto custou fazer os anúncios aparecerem mil vezes.',
   'investimento ÷ impressões × 1000', 'moeda', false, 'derivada', NULL, NULL, NULL),
  ('custo_mil_alcance', 'Custo por mil pessoas alcançadas',
   'Quanto custou alcançar mil pessoas diferentes no período.',
   'investimento ÷ alcance × 1000, do mesmo período', 'moeda', false, 'derivada', NULL, NULL, NULL),
  ('visualizacoes_pagina_destino', 'Visitas ao site',
   'Quantas vezes alguém clicou e o site carregou de fato.',
   'soma', 'quantidade', true, 'acao', NULL, 'landing_page_view', 'quantidade'),
  ('custo_visualizacao_pagina', 'Custo por visita ao site',
   'Quanto custou, em média, cada visita ao site.',
   'investimento ÷ visualizações da página de destino', 'moeda', false, 'derivada', NULL, NULL, NULL),
  ('conversas_iniciadas', 'Conversas iniciadas',
   'Quantas conversas começaram no WhatsApp, Messenger ou Direct a partir do anúncio.',
   'soma', 'quantidade', true, 'acao', NULL, 'onsite_conversion.messaging_conversation_started_7d', 'quantidade'),
  ('custo_conversa', 'Custo por conversa',
   'Quanto custou, em média, cada conversa iniciada.',
   'investimento ÷ conversas iniciadas', 'moeda', false, 'derivada', NULL, NULL, NULL),
  ('cadastros', 'Cadastros',
   'Quantas pessoas deixaram seus dados num formulário do anúncio ou no site.',
   'soma', 'quantidade', true, 'acao', NULL, 'lead', 'quantidade'),
  ('custo_cadastro', 'Custo por cadastro',
   'Quanto custou, em média, cada cadastro.',
   'investimento ÷ cadastros', 'moeda', false, 'derivada', NULL, NULL, NULL),
  ('compras', 'Compras',
   'Quantas compras foram registradas e atribuídas aos anúncios.',
   'soma', 'quantidade', true, 'acao', NULL, 'omni_purchase', 'quantidade'),
  ('valor_compras', 'Valor das compras',
   'Soma do valor das compras atribuídas aos anúncios.',
   'soma', 'moeda', true, 'acao', NULL, 'omni_purchase', 'valor'),
  ('custo_compra', 'Custo por compra',
   'Quanto custou, em média, cada compra.',
   'investimento ÷ compras', 'moeda', false, 'derivada', NULL, NULL, NULL),
  ('roas', 'Retorno sobre o investimento',
   'Quantos reais em vendas voltaram para cada real investido.',
   'valor das compras ÷ investimento', 'razao', false, 'derivada', NULL, NULL, NULL),
  ('interacoes_publicacao', 'Interações com a publicação',
   'Curtidas, comentários, compartilhamentos e cliques na publicação.',
   'soma', 'quantidade', true, 'acao', NULL, 'post_engagement', 'quantidade'),
  ('custo_interacao', 'Custo por interação',
   'Quanto custou, em média, cada interação.',
   'investimento ÷ interações', 'moeda', false, 'derivada', NULL, NULL, NULL);

-- Resultado principal por objetivo e meta de otimização, com as métricas de
-- apoio na ordem de exibição. Meta nula é "qualquer", e a linha específica
-- (CONVERSATIONS, LANDING_PAGE_VIEWS) vence a genérica do mesmo objetivo. O
-- resultado de OUTCOME_APP_PROMOTION é a confirmar (Q-10) e fica nulo, e a
-- linha sem objetivo é "Não classificado", sem resultado principal e só com
-- as métricas de apoio.
WITH regra (objetivo, meta_otimizacao, nome_objetivo, metrica_resultado, metrica_kpi, apoio) AS (
  VALUES
    ('OUTCOME_AWARENESS', NULL, 'Reconhecimento', 'alcance', 'custo_mil_alcance',
     ARRAY['frequencia', 'impressoes', 'cpm']),
    ('OUTCOME_TRAFFIC', 'LANDING_PAGE_VIEWS', 'Tráfego', 'visualizacoes_pagina_destino', 'custo_visualizacao_pagina',
     ARRAY['cliques_link', 'ctr', 'cpc']),
    ('OUTCOME_TRAFFIC', NULL, 'Tráfego', 'cliques_link', 'cpc',
     ARRAY['ctr', 'cpm', 'visualizacoes_pagina_destino']),
    ('OUTCOME_ENGAGEMENT', 'CONVERSATIONS', 'Conversas', 'conversas_iniciadas', 'custo_conversa',
     ARRAY['cliques_link', 'ctr', 'cpm']),
    ('OUTCOME_ENGAGEMENT', NULL, 'Engajamento', 'interacoes_publicacao', 'custo_interacao',
     ARRAY['alcance', 'ctr', 'cpm']),
    ('OUTCOME_LEADS', NULL, 'Cadastros', 'cadastros', 'custo_cadastro',
     ARRAY['cliques_link', 'ctr', 'cpm']),
    ('OUTCOME_LEADS', 'CONVERSATIONS', 'Cadastros por conversa', 'conversas_iniciadas', 'custo_conversa',
     ARRAY['cadastros', 'ctr']),
    ('OUTCOME_SALES', NULL, 'Vendas', 'compras', 'custo_compra',
     ARRAY['valor_compras', 'roas', 'cliques_link']),
    ('OUTCOME_SALES', 'CONVERSATIONS', 'Vendas por conversa', 'conversas_iniciadas', 'custo_conversa',
     ARRAY['compras', 'valor_compras']),
    ('OUTCOME_APP_PROMOTION', NULL, 'Promoção de app', NULL, NULL,
     ARRAY['investimento', 'cliques_link']),
    (NULL, NULL, 'Não classificado', NULL, NULL,
     ARRAY['investimento', 'impressoes', 'cliques_link'])
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

-- Equivalência oficial dos objetivos legados (R-40). CONVERSIONS e
-- VIDEO_VIEWS, com mais de um equivalente, e LOCAL_AWARENESS e OFFER_CLAIMS,
-- sem equivalente oficial, ficam de fora até a Q-10 ser resolvida; uma
-- campanha com eles cai em "Não classificado" (RF-15).
INSERT INTO normalizado.objetivo_equivalente (objetivo_legado, objetivo)
VALUES
  ('APP_INSTALLS', 'OUTCOME_APP_PROMOTION'),
  ('BRAND_AWARENESS', 'OUTCOME_AWARENESS'),
  ('REACH', 'OUTCOME_AWARENESS'),
  ('STORE_VISITS', 'OUTCOME_AWARENESS'),
  ('LINK_CLICKS', 'OUTCOME_TRAFFIC'),
  ('EVENT_RESPONSES', 'OUTCOME_ENGAGEMENT'),
  ('MESSAGES', 'OUTCOME_ENGAGEMENT'),
  ('PAGE_LIKES', 'OUTCOME_ENGAGEMENT'),
  ('POST_ENGAGEMENT', 'OUTCOME_ENGAGEMENT'),
  ('LEAD_GENERATION', 'OUTCOME_LEADS'),
  ('PRODUCT_CATALOG_SALES', 'OUTCOME_SALES');
