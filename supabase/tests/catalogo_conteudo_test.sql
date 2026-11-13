-- Prova o conteúdo do catálogo carregado por migration a partir do
-- REQUIREMENTS §7, com os enums confirmados na API (R-40, R-41) e a
-- classificação das combinações observadas nas contas: as regras de
-- resultado apontam para métricas existentes, os textos são de negócio e os
-- casos dos critérios do RF-14 e do RF-31 resolvem como descrito (RNF-01;
-- ADR-0007; ADR-0009 §2).
BEGIN;
SELECT plan(27);

SELECT isnt_empty('SELECT 1 FROM normalizado.metrica', 'o catálogo de métricas está carregado');
SELECT isnt_empty('SELECT 1 FROM normalizado.resultado_objetivo', 'o catálogo de resultado por objetivo está carregado');
SELECT isnt_empty('SELECT 1 FROM normalizado.objetivo_equivalente', 'a equivalência dos objetivos legados está carregada');

-- Toda regra de resultado aponta para métricas existentes. As FKs garantem a
-- referência; a consulta confere o conteúdo carregado.
SELECT is_empty(
  $$
  SELECT r.nome_objetivo, referencia.metrica
  FROM normalizado.resultado_objetivo AS r
  CROSS JOIN LATERAL (VALUES (r.metrica_resultado), (r.metrica_kpi)) AS referencia (metrica)
  WHERE referencia.metrica IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM normalizado.metrica AS m WHERE m.codigo = referencia.metrica)
  UNION ALL
  SELECT r.nome_objetivo, a.metrica
  FROM normalizado.metrica_apoio_resultado AS a
  JOIN normalizado.resultado_objetivo AS r ON r.id = a.resultado_objetivo_id
  WHERE NOT EXISTS (SELECT 1 FROM normalizado.metrica AS m WHERE m.codigo = a.metrica)
  $$,
  'toda regra de resultado aponta para métricas existentes: resultado, KPI e apoio'
);
-- As regras sem resultado principal ficam sem os dois: "Não classificado" e
-- as de resultado que a ETL não extrai ou que depende do evento ou do
-- destino do conjunto (REQUIREMENTS §7.2). Nenhuma linha tem só um deles.
SELECT is_empty(
  $$
  SELECT nome_objetivo
  FROM normalizado.resultado_objetivo
  WHERE (metrica_resultado IS NULL) <> (metrica_kpi IS NULL)
  $$,
  'toda regra com resultado principal tem KPI, e toda regra com KPI tem resultado principal'
);
SELECT is_empty(
  $$
  SELECT r.nome_objetivo
  FROM normalizado.resultado_objetivo AS r
  WHERE NOT EXISTS (SELECT 1 FROM normalizado.metrica_apoio_resultado AS a WHERE a.resultado_objetivo_id = r.id)
  $$,
  'toda regra, inclusive "Não classificado", tem métricas de apoio'
);
SELECT is_empty(
  $$
  SELECT r.nome_objetivo, a.metrica
  FROM normalizado.metrica_apoio_resultado AS a
  JOIN normalizado.resultado_objetivo AS r ON r.id = a.resultado_objetivo_id
  WHERE a.metrica IN (r.metrica_resultado, r.metrica_kpi)
  $$,
  'nenhuma métrica de apoio repete o resultado principal ou o KPI da própria regra'
);
SELECT results_eq(
  $$
  SELECT nome_objetivo, meta_otimizacao, metrica_resultado, metrica_kpi
  FROM normalizado.resultado_objetivo
  WHERE objetivo IS NULL
  $$,
  $$ VALUES ('Não classificado', NULL::text, NULL::text, NULL::text) $$,
  'existe uma única linha sem objetivo, "Não classificado", sem resultado nem KPI'
);

-- O mapa inteiro, como as migrations de carga e de classificação do
-- catálogo o gravam (REQUIREMENTS §7.2). Uma mudança no catálogo global
-- entra por migration e atualiza esta conferência no mesmo commit
-- (ADR-0007).
SELECT results_eq(
  $$
  SELECT r.objetivo, r.meta_otimizacao, r.nome_objetivo, r.metrica_resultado, r.metrica_kpi,
         array_agg(a.metrica ORDER BY a.ordem)
  FROM normalizado.resultado_objetivo AS r
  JOIN normalizado.metrica_apoio_resultado AS a ON a.resultado_objetivo_id = r.id
  GROUP BY r.id
  ORDER BY r.objetivo NULLS LAST, r.meta_otimizacao NULLS FIRST
  $$,
  $$
  VALUES
    ('CONVERSIONS', NULL, 'Conversões (objetivo antigo)', NULL, NULL, ARRAY['cadastros', 'compras', 'contatos_site', 'cliques_link']),
    ('OUTCOME_APP_PROMOTION', NULL, 'Promoção de app', 'instalacoes_app', 'custo_instalacao', ARRAY['cliques_link', 'ctr', 'cpm']),
    ('OUTCOME_AWARENESS', NULL, 'Reconhecimento', 'alcance', 'custo_mil_alcance', ARRAY['frequencia', 'impressoes', 'cpm']),
    ('OUTCOME_ENGAGEMENT', NULL, 'Engajamento', 'interacoes_publicacao', 'custo_interacao', ARRAY['alcance', 'ctr', 'cpm']),
    ('OUTCOME_ENGAGEMENT', 'CONVERSATIONS', 'Conversas', 'conversas_iniciadas', 'custo_conversa', ARRAY['cliques_link', 'ctr', 'cpm']),
    ('OUTCOME_ENGAGEMENT', 'OFFSITE_CONVERSIONS', 'Conversões no site', 'contatos_site', 'custo_contato_site', ARRAY['cliques_link', 'visualizacoes_pagina_destino', 'ctr']),
    ('OUTCOME_ENGAGEMENT', 'THRUPLAY', 'Visualizações de vídeo', 'visualizacoes_thruplay', 'custo_thruplay', ARRAY['alcance', 'impressoes', 'cpm']),
    ('OUTCOME_LEADS', NULL, 'Cadastros', 'cadastros', 'custo_cadastro', ARRAY['cliques_link', 'ctr', 'cpm']),
    ('OUTCOME_LEADS', 'CONVERSATIONS', 'Cadastros por conversa', 'conversas_iniciadas', 'custo_conversa', ARRAY['cadastros', 'ctr']),
    ('OUTCOME_SALES', NULL, 'Vendas', 'compras', 'custo_compra', ARRAY['valor_compras', 'roas', 'cliques_link']),
    ('OUTCOME_SALES', 'CONVERSATIONS', 'Vendas por conversa', 'conversas_iniciadas', 'custo_conversa', ARRAY['compras', 'valor_compras']),
    ('OUTCOME_TRAFFIC', NULL, 'Tráfego', 'cliques_link', 'cpc', ARRAY['ctr', 'cpm', 'visualizacoes_pagina_destino']),
    ('OUTCOME_TRAFFIC', 'CONVERSATIONS', 'Tráfego para conversas', 'conversas_iniciadas', 'custo_conversa', ARRAY['cliques_link', 'ctr', 'cpm']),
    ('OUTCOME_TRAFFIC', 'LANDING_PAGE_VIEWS', 'Tráfego', 'visualizacoes_pagina_destino', 'custo_visualizacao_pagina', ARRAY['cliques_link', 'ctr', 'cpc']),
    ('OUTCOME_TRAFFIC', 'PROFILE_VISIT', 'Visitas ao perfil', 'visitas_perfil', 'custo_visita_perfil', ARRAY['ctr', 'cpm', 'alcance']),
    ('OUTCOME_TRAFFIC', 'VISIT_INSTAGRAM_PROFILE', 'Visitas ao perfil', 'visitas_perfil', 'custo_visita_perfil', ARRAY['ctr', 'cpm', 'alcance']),
    ('VIDEO_VIEWS', NULL, 'Visualizações de vídeo (objetivo antigo)', NULL, NULL, ARRAY['visualizacoes_thruplay', 'alcance', 'impressoes', 'cpm']),
    (NULL, NULL, 'Não classificado', NULL, NULL, ARRAY['investimento', 'impressoes', 'cliques_link'])
  $$,
  'cada regra tem o nome, o resultado, o KPI e as métricas de apoio, em ordem, do REQUIREMENTS §7.2'
);
SELECT results_eq(
  'SELECT objetivo_legado, objetivo FROM normalizado.objetivo_equivalente ORDER BY objetivo_legado',
  $$
  VALUES
    ('APP_INSTALLS', 'OUTCOME_APP_PROMOTION'),
    ('BRAND_AWARENESS', 'OUTCOME_AWARENESS'),
    ('EVENT_RESPONSES', 'OUTCOME_ENGAGEMENT'),
    ('LEAD_GENERATION', 'OUTCOME_LEADS'),
    ('LINK_CLICKS', 'OUTCOME_TRAFFIC'),
    ('MESSAGES', 'OUTCOME_ENGAGEMENT'),
    ('PAGE_LIKES', 'OUTCOME_ENGAGEMENT'),
    ('POST_ENGAGEMENT', 'OUTCOME_ENGAGEMENT'),
    ('PRODUCT_CATALOG_SALES', 'OUTCOME_SALES'),
    ('REACH', 'OUTCOME_AWARENESS'),
    ('STORE_VISITS', 'OUTCOME_AWARENESS')
  $$,
  'cada objetivo legado de equivalente único leva ao objetivo atual da tabela oficial (R-40)'
);

-- Os critérios do RF-14 e do RF-31, na parte do catálogo: o rótulo exibido
-- vem da métrica apontada pela regra.
SELECT results_eq(
  $$
  SELECT r.objetivo, r.meta_otimizacao, resultado.rotulo, kpi.rotulo
  FROM normalizado.resultado_objetivo AS r
  JOIN normalizado.metrica AS resultado ON resultado.codigo = r.metrica_resultado
  JOIN normalizado.metrica AS kpi ON kpi.codigo = r.metrica_kpi
  WHERE (r.objetivo, r.meta_otimizacao) IN (('OUTCOME_ENGAGEMENT', 'CONVERSATIONS'))
     OR (r.objetivo = 'OUTCOME_SALES' AND r.meta_otimizacao IS NULL)
  ORDER BY r.objetivo
  $$,
  $$
  VALUES
    ('OUTCOME_ENGAGEMENT', 'CONVERSATIONS', 'Conversas iniciadas', 'Custo por conversa'),
    ('OUTCOME_SALES', NULL, 'Compras', 'Custo por compra')
  $$,
  'engajamento otimizado para conversas mostra "Conversas iniciadas", e vendas mostra "Compras" e "Custo por compra"'
);

-- Enums confirmados na API: os seis objetivos atuais têm uma linha genérica,
-- e as metas de otimização do catálogo existem na referência do conjunto.
SELECT results_eq(
  $$
  SELECT objetivo
  FROM normalizado.resultado_objetivo
  WHERE objetivo ~ '^OUTCOME_' AND meta_otimizacao IS NULL
  ORDER BY objetivo
  $$,
  $$
  VALUES ('OUTCOME_APP_PROMOTION'), ('OUTCOME_AWARENESS'), ('OUTCOME_ENGAGEMENT'),
         ('OUTCOME_LEADS'), ('OUTCOME_SALES'), ('OUTCOME_TRAFFIC')
  $$,
  'cada objetivo atual da API tem uma linha para qualquer meta de otimização (R-40)'
);
SELECT is_empty(
  $$
  SELECT meta_otimizacao
  FROM normalizado.resultado_objetivo
  WHERE meta_otimizacao NOT IN (
    'NONE', 'APP_INSTALLS', 'AD_RECALL_LIFT', 'ENGAGED_USERS', 'EVENT_RESPONSES', 'IMPRESSIONS',
    'LEAD_GENERATION', 'QUALITY_LEAD', 'LINK_CLICKS', 'OFFSITE_CONVERSIONS', 'PAGE_LIKES',
    'POST_ENGAGEMENT', 'QUALITY_CALL', 'REACH', 'LANDING_PAGE_VIEWS', 'VISIT_INSTAGRAM_PROFILE',
    'ENGAGED_PAGE_VIEWS', 'VALUE', 'THRUPLAY', 'DERIVED_EVENTS', 'APP_INSTALLS_AND_OFFSITE_CONVERSIONS',
    'CONVERSATIONS', 'IN_APP_VALUE', 'MESSAGING_PURCHASE_CONVERSION',
    'MESSAGING_DEEP_CONVERSATION_AND_FOLLOW', 'SUBSCRIBERS', 'REMINDERS_SET', 'MEANINGFUL_CALL_ATTEMPT',
    'PROFILE_VISIT', 'PROFILE_AND_PAGE_ENGAGEMENT', 'ADVERTISER_SILOED_VALUE', 'AUTOMATIC_OBJECTIVE',
    'MESSAGING_APPOINTMENT_CONVERSION'
  )
  $$,
  'toda meta de otimização do catálogo é um valor da referência do conjunto (R-41)'
);

-- Objetivos legados: os de equivalente único passam pela tabela oficial
-- (R-40). Os de mais de um equivalente, que depende do evento ou do destino
-- do conjunto, têm regra própria sem resultado principal, e os sem
-- equivalente oficial ficam em "Não classificado" (REQUIREMENTS §7.2).
SELECT results_eq(
  $$
  SELECT legado
  FROM unnest(ARRAY[
    'APP_INSTALLS', 'BRAND_AWARENESS', 'CONVERSIONS', 'EVENT_RESPONSES', 'LEAD_GENERATION',
    'LINK_CLICKS', 'LOCAL_AWARENESS', 'MESSAGES', 'OFFER_CLAIMS', 'PAGE_LIKES', 'POST_ENGAGEMENT',
    'PRODUCT_CATALOG_SALES', 'REACH', 'STORE_VISITS', 'VIDEO_VIEWS'
  ]) AS legado
  WHERE NOT EXISTS (SELECT 1 FROM normalizado.objetivo_equivalente AS e WHERE e.objetivo_legado = legado)
    AND NOT EXISTS (SELECT 1 FROM normalizado.resultado_objetivo AS r WHERE r.objetivo = legado)
  ORDER BY legado
  $$,
  $$ VALUES ('LOCAL_AWARENESS'), ('OFFER_CLAIMS') $$,
  'todo objetivo legado da API tem equivalente ou regra própria, salvo os sem equivalente oficial'
);
SELECT results_eq(
  $$
  SELECT r.objetivo, r.meta_otimizacao, r.metrica_resultado
  FROM normalizado.resultado_objetivo AS r
  WHERE r.objetivo IS NOT NULL AND r.objetivo !~ '^OUTCOME_'
  ORDER BY r.objetivo
  $$,
  $$ VALUES ('CONVERSIONS', NULL::text, NULL::text), ('VIDEO_VIEWS', NULL, NULL) $$,
  'só os legados de mais de um equivalente têm regra própria, para qualquer meta e sem resultado principal'
);
SELECT is(
  (SELECT count(*) FROM normalizado.objetivo_equivalente),
  11::bigint,
  'o catálogo não tem objetivo legado fora da lista da API (R-40)'
);
SELECT is_empty(
  $$
  SELECT e.objetivo_legado, e.objetivo
  FROM normalizado.objetivo_equivalente AS e
  WHERE NOT EXISTS (
    SELECT 1 FROM normalizado.resultado_objetivo AS r
    WHERE r.objetivo = e.objetivo AND r.meta_otimizacao IS NULL
  )
  $$,
  'todo objetivo legado leva a um objetivo atual com linha para qualquer meta de otimização'
);
SELECT is_empty(
  $$
  SELECT r.objetivo
  FROM normalizado.resultado_objetivo AS r
  JOIN normalizado.objetivo_equivalente AS e ON e.objetivo_legado = r.objetivo
  $$,
  'nenhum objetivo legado com equivalente tem regra própria: ele passa pelo equivalente'
);

-- A origem de cada métrica existe no banco, e a aditividade segue as regras
-- de agregação do REQUIREMENTS §7.1.
SELECT is_empty(
  $$
  SELECT m.codigo, m.campo_base
  FROM normalizado.metrica AS m
  WHERE m.tipo = 'base'
    AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns AS c
      WHERE c.table_schema = 'normalizado'
        AND c.table_name = 'metrica_diaria_anuncio'
        AND c.column_name = m.campo_base
    )
  $$,
  'toda métrica base lê uma coluna existente de metrica_diaria_anuncio'
);
SELECT is_empty(
  $$
  SELECT codigo
  FROM normalizado.metrica
  WHERE (tipo = 'derivada' AND aditiva) OR (tipo = 'acao' AND NOT aditiva)
  $$,
  'razões e derivadas nunca são aditivas, e as métricas de ação sempre são'
);
-- Cada derivada é a razão da própria fórmula. O percentual sai como fração,
-- que a formatação pt-BR exibe multiplicada por 100 (RF-35), então o fator do
-- CTR é 1, e o "× 100" da fórmula descreve a exibição.
SELECT results_eq(
  $$
  SELECT codigo, numerador, denominador, fator
  FROM normalizado.metrica
  WHERE tipo = 'derivada'
  ORDER BY codigo
  $$,
  $$
  VALUES
    ('cpc', 'investimento', 'cliques_link', 1::numeric),
    ('cpm', 'investimento', 'impressoes', 1000::numeric),
    ('ctr', 'cliques_link', 'impressoes', 1::numeric),
    ('custo_cadastro', 'investimento', 'cadastros', 1::numeric),
    ('custo_compra', 'investimento', 'compras', 1::numeric),
    ('custo_contato_site', 'investimento', 'contatos_site', 1::numeric),
    ('custo_conversa', 'investimento', 'conversas_iniciadas', 1::numeric),
    ('custo_instalacao', 'investimento', 'instalacoes_app', 1::numeric),
    ('custo_interacao', 'investimento', 'interacoes_publicacao', 1::numeric),
    ('custo_mil_alcance', 'investimento', 'alcance', 1000::numeric),
    ('custo_thruplay', 'investimento', 'visualizacoes_thruplay', 1::numeric),
    ('custo_visita_perfil', 'investimento', 'visitas_perfil', 1::numeric),
    ('custo_visualizacao_pagina', 'investimento', 'visualizacoes_pagina_destino', 1::numeric),
    ('frequencia', 'impressoes', 'alcance', 1::numeric),
    ('roas', 'valor_compras', 'investimento', 1::numeric)
  $$,
  'cada métrica derivada é a razão entre as métricas da própria fórmula, com o fator de escala'
);
-- Os resultados que a Meta conta fora de actions são métricas de ação, com
-- o tipo que a ETL grava na tabela longa: o indicator de results, com ponto
-- no lugar dos dois-pontos (R-24; REQUIREMENTS §7.2).
SELECT results_eq(
  $$
  SELECT codigo, tipo, tipo_acao, medida_acao, unidade, aditiva
  FROM normalizado.metrica
  WHERE codigo IN ('visitas_perfil', 'visualizacoes_thruplay', 'contatos_site')
  ORDER BY codigo
  $$,
  $$
  VALUES
    ('contatos_site', 'acao', 'conversions.contact_website', 'quantidade', 'quantidade', true),
    ('visitas_perfil', 'acao', 'profile_visit_view', 'quantidade', 'quantidade', true),
    ('visualizacoes_thruplay', 'acao', 'video_thruplay_watched_actions', 'quantidade', 'quantidade', true)
  $$,
  'visitas ao perfil, ThruPlay e contato no site leem o tipo gravado a partir do indicator de results'
);
-- Se a alta de uma métrica é melhora ou piora vem do catálogo, e não da tela
-- (RF-27; ADR-0007). Todo custo, que é o investimento dividido por outra
-- métrica, melhora na queda.
SELECT is_empty(
  $$
  SELECT codigo
  FROM normalizado.metrica
  WHERE tipo = 'derivada' AND numerador = 'investimento' AND sentido_melhora <> 'queda'
  $$,
  'RF-27: todo custo melhora na queda'
);
-- O investimento e a frequência não são bons nem ruins por si: gastar mais ou
-- repetir mais o anúncio depende do plano da campanha.
SELECT results_eq(
  $$ SELECT codigo, sentido_melhora FROM normalizado.metrica ORDER BY codigo $$,
  $$
  VALUES
    ('alcance', 'alta'),
    ('cadastros', 'alta'),
    ('cliques_link', 'alta'),
    ('compras', 'alta'),
    ('contatos_site', 'alta'),
    ('conversas_iniciadas', 'alta'),
    ('cpc', 'queda'),
    ('cpm', 'queda'),
    ('ctr', 'alta'),
    ('custo_cadastro', 'queda'),
    ('custo_compra', 'queda'),
    ('custo_contato_site', 'queda'),
    ('custo_conversa', 'queda'),
    ('custo_instalacao', 'queda'),
    ('custo_interacao', 'queda'),
    ('custo_mil_alcance', 'queda'),
    ('custo_thruplay', 'queda'),
    ('custo_visita_perfil', 'queda'),
    ('custo_visualizacao_pagina', 'queda'),
    ('frequencia', 'indiferente'),
    ('impressoes', 'alta'),
    ('instalacoes_app', 'alta'),
    ('interacoes_publicacao', 'alta'),
    ('investimento', 'indiferente'),
    ('roas', 'alta'),
    ('valor_compras', 'alta'),
    ('visitas_perfil', 'alta'),
    ('visualizacoes_pagina_destino', 'alta'),
    ('visualizacoes_thruplay', 'alta')
  $$,
  'cada métrica do catálogo tem o sentido de melhora do negócio'
);
-- As funções de analitico calculam a derivada a partir das somas dos
-- operandos, sem encadear uma derivada em outra.
SELECT is_empty(
  $$
  SELECT derivada.codigo, operando.codigo
  FROM normalizado.metrica AS derivada
  JOIN normalizado.metrica AS operando ON operando.codigo IN (derivada.numerador, derivada.denominador)
  WHERE derivada.tipo = 'derivada'
    AND operando.tipo = 'derivada'
  $$,
  'os operandos de toda derivada são métricas base ou de ação'
);

-- Explicações e rótulos em linguagem de negócio: nenhum nome de campo ou
-- valor de enum da API, cujos nomes sempre têm sublinhado ou são termos
-- em inglês como os da RNF-02.
SELECT is_empty(
  $$
  SELECT origem, texto
  FROM (
    SELECT 'metrica ' || codigo, unnest(ARRAY[rotulo, explicacao, formula]) FROM normalizado.metrica
    UNION ALL
    SELECT 'resultado_objetivo', nome_objetivo FROM normalizado.resultado_objetivo
  ) AS textos (origem, texto)
  WHERE texto ~ '_'
     OR texto ~* '\m(spend|impressions|reach|frequency|clicks?|ctr|cpc|cpm|actions?|action_values|results?|objective|outcome)\M'
  $$,
  'nenhum rótulo, explicação ou fórmula do catálogo tem termo da API'
);

-- A ETL lê o catálogo carregado pela política do RLS. Como etl_carga, as
-- funções do pgTAP não ficam acessíveis: a contagem é guardada num parâmetro
-- da transação e comparada depois de voltar ao postgres.
SET LOCAL ROLE etl_carga;
SELECT set_config(
  'catalogo_conteudo_test.linhas_etl_carga',
  (
    (SELECT count(*) FROM normalizado.metrica)
    + (SELECT count(*) FROM normalizado.resultado_objetivo)
    + (SELECT count(*) FROM normalizado.metrica_apoio_resultado)
    + (SELECT count(*) FROM normalizado.objetivo_equivalente)
  )::text,
  true
);
RESET ROLE;

SELECT is(
  current_setting('catalogo_conteudo_test.linhas_etl_carga')::bigint,
  (SELECT count(*) FROM normalizado.metrica)
    + (SELECT count(*) FROM normalizado.resultado_objetivo)
    + (SELECT count(*) FROM normalizado.metrica_apoio_resultado)
    + (SELECT count(*) FROM normalizado.objetivo_equivalente),
  'etl_carga lê todas as linhas do catálogo'
);

SELECT * FROM finish();
ROLLBACK;
