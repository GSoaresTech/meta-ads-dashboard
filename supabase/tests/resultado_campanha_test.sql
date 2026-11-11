-- Prova a resolução do resultado principal de cada campanha pela precedência
-- do ADR-0007: sobrescrita > objetivo + meta de otimização do conjunto >
-- objetivo + "qualquer" > "Não classificado", com o objetivo legado pelo
-- equivalente atual e, quando os conjuntos divergem, o de maior investimento
-- nos últimos 28 dias (RF-14, RF-15; REQUIREMENTS §7.2; ADR-0009 §4).
BEGIN;
SELECT plan(23);

-- Atributos: função interna, sem credencial, que roda com os privilégios de
-- quem chama (ADR-0009 §3 e §4).
SELECT has_function(
  'normalizado', 'resolver_resultado_campanha', ARRAY['uuid'],
  'normalizado.resolver_resultado_campanha(uuid) existe'
);
SELECT results_eq(
  $$
  SELECT p.provolatile = 's', p.prosecdef, p.proconfig::text = '{"search_path=\"\""}'
  FROM pg_catalog.pg_proc AS p
  WHERE p.oid = 'normalizado.resolver_resultado_campanha(uuid)'::regprocedure
  $$,
  $$ VALUES (true, false, true) $$,
  'a resolução é STABLE, SECURITY INVOKER e com search_path vazio'
);
SELECT ok(
  has_function_privilege('etl_carga', 'normalizado.resolver_resultado_campanha(uuid)', 'EXECUTE'),
  'etl_carga executa a resolução, para os avisos do RF-15 e a comparação do RF-16'
);

-- Duas empresas, cada uma com uma conta, uma execução e um criativo. O fuso
-- da conta define o "hoje" da janela de investimento, e o teste o escolhe
-- pela hora em UTC para que esse dia sempre difira do dia em UTC: +14 a
-- partir das 11h, e -11 antes delas. Assim, uma janela contada no fuso
-- errado falha a qualquer hora em que o teste rode.
INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A'), ('Empresa Teste B');
INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, fuso_horario, moeda)
SELECT id, CASE nome WHEN 'Empresa Teste A' THEN '111111111111111' ELSE '222222222222222' END,
  CASE WHEN extract(hour FROM now() AT TIME ZONE 'UTC') >= 11 THEN 'Pacific/Kiritimati' ELSE 'Pacific/Pago_Pago' END,
  'BRL'
FROM normalizado.empresa
WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');
INSERT INTO normalizado.execucao_carga (empresa_id, tipo)
SELECT id, 'diaria' FROM normalizado.empresa WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');
INSERT INTO normalizado.criativo (empresa_id, conta_anuncio_id, id_meta, execucao_id)
SELECT c.empresa_id, c.id, c.id_meta || '9', x.id
FROM normalizado.conta_anuncio AS c
JOIN normalizado.execucao_carga AS x USING (empresa_id);

-- Uma campanha da empresa A por caso, com um conjunto, salvo no caso sem
-- conjunto. O caso guarda a entrada e o resultado esperado. Os casos de 1 a
-- 15, o 17, o 21, o 24 e o 26 são combinações da tabela do REQUIREMENTS
-- §7.2. Os demais cobrem a regra específica fora dela (16), o legado com
-- equivalente na regra genérica (18), a promoção de app (19), o objetivo
-- desconhecido (20), o conjunto sem meta (22), a campanha sem conjunto (23)
-- e o legado sem equivalente oficial (25).
CREATE TEMPORARY TABLE caso (
  numero integer PRIMARY KEY,
  objetivo text NOT NULL,
  meta_otimizacao text,
  nome_objetivo text NOT NULL,
  metrica_resultado text,
  metrica_kpi text,
  com_conjunto boolean NOT NULL DEFAULT true
);
INSERT INTO caso (numero, objetivo, meta_otimizacao, nome_objetivo, metrica_resultado, metrica_kpi) VALUES
  (1, 'OUTCOME_AWARENESS', 'REACH', 'Reconhecimento', 'alcance', 'custo_mil_alcance'),
  (2, 'OUTCOME_ENGAGEMENT', 'CONVERSATIONS', 'Conversas', 'conversas_iniciadas', 'custo_conversa'),
  (3, 'OUTCOME_ENGAGEMENT', 'POST_ENGAGEMENT', 'Engajamento', 'interacoes_publicacao', 'custo_interacao'),
  (4, 'OUTCOME_ENGAGEMENT', 'THRUPLAY', 'Visualizações de vídeo', NULL, NULL),
  (5, 'OUTCOME_ENGAGEMENT', 'OFFSITE_CONVERSIONS', 'Conversões no site', NULL, NULL),
  (6, 'OUTCOME_LEADS', 'OFFSITE_CONVERSIONS', 'Cadastros', 'cadastros', 'custo_cadastro'),
  (7, 'OUTCOME_LEADS', 'CONVERSATIONS', 'Cadastros por conversa', 'conversas_iniciadas', 'custo_conversa'),
  (8, 'OUTCOME_SALES', 'CONVERSATIONS', 'Vendas por conversa', 'conversas_iniciadas', 'custo_conversa'),
  (9, 'OUTCOME_SALES', 'OFFSITE_CONVERSIONS', 'Vendas', 'compras', 'custo_compra'),
  (10, 'OUTCOME_SALES', 'VALUE', 'Vendas', 'compras', 'custo_compra'),
  (11, 'OUTCOME_TRAFFIC', 'CONVERSATIONS', 'Tráfego para conversas', 'conversas_iniciadas', 'custo_conversa'),
  (12, 'OUTCOME_TRAFFIC', 'PROFILE_VISIT', 'Visitas ao perfil', 'cliques_link', 'cpc'),
  (13, 'OUTCOME_TRAFFIC', 'VISIT_INSTAGRAM_PROFILE', 'Visitas ao perfil', 'cliques_link', 'cpc'),
  (14, 'LINK_CLICKS', 'VISIT_INSTAGRAM_PROFILE', 'Visitas ao perfil', 'cliques_link', 'cpc'),
  (15, 'LINK_CLICKS', 'AUTOMATIC_OBJECTIVE', 'Tráfego', 'cliques_link', 'cpc'),
  (16, 'OUTCOME_TRAFFIC', 'LANDING_PAGE_VIEWS', 'Tráfego', 'visualizacoes_pagina_destino', 'custo_visualizacao_pagina'),
  (17, 'MESSAGES', 'CONVERSATIONS', 'Conversas', 'conversas_iniciadas', 'custo_conversa'),
  (18, 'MESSAGES', 'POST_ENGAGEMENT', 'Engajamento', 'interacoes_publicacao', 'custo_interacao'),
  (19, 'OUTCOME_APP_PROMOTION', 'APP_INSTALLS', 'Promoção de app', 'instalacoes_app', 'custo_instalacao'),
  (20, 'OUTCOME_OBJETIVO_FUTURO', 'REACH', 'Não classificado', NULL, NULL),
  (21, 'CONVERSIONS', 'OFFSITE_CONVERSIONS', 'Conversões (objetivo antigo)', NULL, NULL),
  (22, 'OUTCOME_LEADS', NULL, 'Cadastros', 'cadastros', 'custo_cadastro');
INSERT INTO caso VALUES (23, 'OUTCOME_SALES', NULL, 'Vendas', 'compras', 'custo_compra', false);
INSERT INTO caso (numero, objetivo, meta_otimizacao, nome_objetivo, metrica_resultado, metrica_kpi) VALUES
  (24, 'VIDEO_VIEWS', 'THRUPLAY', 'Visualizações de vídeo (objetivo antigo)', NULL, NULL),
  (25, 'LOCAL_AWARENESS', 'REACH', 'Não classificado', NULL, NULL),
  (26, 'OUTCOME_TRAFFIC', 'LINK_CLICKS', 'Tráfego', 'cliques_link', 'cpc');

-- O ID da Meta da campanha do caso, 1200000000000003NN, e o do conjunto,
-- 1210000000000003NN.
CREATE FUNCTION pg_temp.id_meta_caso(prefixo text, numero integer) RETURNS text
LANGUAGE sql IMMUTABLE AS $$ SELECT prefixo || '0000000000003' || lpad(numero::text, 2, '0') $$;

-- O objetivo desconhecido entra como qualquer outro: o domínio é aberto, e a
-- carga não falha (RF-15).
SELECT lives_ok(
  $$
  INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, objetivo, status, execucao_id)
  SELECT c.empresa_id, c.id, pg_temp.id_meta_caso('120', caso.numero), caso.objetivo, 'ACTIVE', x.id
  FROM caso
  CROSS JOIN normalizado.conta_anuncio AS c
  JOIN normalizado.execucao_carga AS x USING (empresa_id)
  WHERE c.id_meta = '111111111111111'
  $$,
  'as campanhas de todos os casos, inclusive a de objetivo fora do catálogo, são aceitas'
);
INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, meta_otimizacao, status, execucao_id)
SELECT campanha.empresa_id, campanha.id, pg_temp.id_meta_caso('121', caso.numero), caso.meta_otimizacao,
  'ACTIVE', campanha.execucao_id
FROM caso
JOIN normalizado.campanha AS campanha ON campanha.id_meta = pg_temp.id_meta_caso('120', caso.numero)
WHERE caso.com_conjunto;

-- O resultado resolvido de cada campanha da empresa A, pelo ID da Meta, com
-- o nome do objetivo da regra do catálogo.
CREATE TEMPORARY VIEW resolvido_a AS
SELECT campanha.id_meta, regra.nome_objetivo, resolvido.metrica_resultado, resolvido.metrica_kpi, resolvido.sobrescrita
FROM normalizado.resolver_resultado_campanha(
  (SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Teste A')
) AS resolvido
JOIN normalizado.campanha AS campanha ON campanha.id = resolvido.campanha_id
LEFT JOIN normalizado.resultado_objetivo AS regra ON regra.id = resolvido.resultado_objetivo_id;

SELECT results_eq(
  $$
  SELECT nome_objetivo, metrica_resultado, metrica_kpi, sobrescrita
  FROM resolvido_a
  WHERE id_meta IN (SELECT pg_temp.id_meta_caso('120', numero) FROM caso)
  ORDER BY id_meta
  $$,
  $$
  SELECT nome_objetivo, metrica_resultado, metrica_kpi, false
  FROM caso
  ORDER BY numero
  $$,
  'cada campanha resolve o nome do objetivo, o resultado e o KPI do REQUIREMENTS §7.2, sem sobrescrita'
);

-- RF-14: engajamento otimizado para conversas exibe "Conversas iniciadas";
-- uma sobrescrita gravada muda o resultado sem commit algum, e o nome do
-- objetivo continua o do catálogo.
SELECT is(
  (
    SELECT metrica.rotulo
    FROM resolvido_a
    JOIN normalizado.metrica AS metrica ON metrica.codigo = resolvido_a.metrica_resultado
    WHERE resolvido_a.id_meta = pg_temp.id_meta_caso('120', 2)
  ),
  'Conversas iniciadas',
  'campanha OUTCOME_ENGAGEMENT otimizada para conversas exibe "Conversas iniciadas" (RF-14)'
);
INSERT INTO normalizado.sobrescrita_resultado_campanha (empresa_id, campanha_id, metrica_resultado, metrica_kpi)
SELECT empresa_id, id, 'cadastros', 'custo_cadastro'
FROM normalizado.campanha
WHERE id_meta IN (pg_temp.id_meta_caso('120', 2), pg_temp.id_meta_caso('120', 20));
SELECT results_eq(
  $$
  SELECT nome_objetivo, metrica_resultado, metrica_kpi, sobrescrita
  FROM resolvido_a
  WHERE id_meta IN (pg_temp.id_meta_caso('120', 2), pg_temp.id_meta_caso('120', 20))
  ORDER BY id_meta
  $$,
  $$
  VALUES
    ('Conversas', 'cadastros', 'custo_cadastro', true),
    ('Não classificado', 'cadastros', 'custo_cadastro', true)
  $$,
  'a sobrescrita vence o catálogo, inclusive no objetivo desconhecido, e mantém o nome do objetivo (RF-14)'
);
SELECT is(
  (SELECT count(*) FROM resolvido_a WHERE sobrescrita),
  2::bigint,
  'só as campanhas com sobrescrita a usam'
);
DELETE FROM normalizado.sobrescrita_resultado_campanha
WHERE campanha_id = (SELECT id FROM normalizado.campanha WHERE id_meta = pg_temp.id_meta_caso('120', 2));
SELECT results_eq(
  $$
  SELECT nome_objetivo, metrica_resultado, metrica_kpi, sobrescrita
  FROM resolvido_a
  WHERE id_meta = pg_temp.id_meta_caso('120', 2)
  $$,
  $$ VALUES ('Conversas', 'conversas_iniciadas', 'custo_conversa', false) $$,
  'sem a sobrescrita, a campanha volta ao resultado do catálogo'
);

-- RF-15: o legado mapeado exibe resultado principal; o objetivo fora do
-- catálogo é "Não classificado", sem resultado, com as métricas de apoio da
-- regra própria.
SELECT isnt(
  (SELECT metrica_resultado FROM resolvido_a WHERE id_meta = pg_temp.id_meta_caso('120', 14)),
  NULL,
  'campanha com objetivo legado mapeado exibe resultado principal (RF-15)'
);
SELECT results_eq(
  $$
  SELECT nome_objetivo, metrica_resultado
  FROM resolvido_a
  WHERE id_meta = pg_temp.id_meta_caso('120', 25)
  $$,
  $$ VALUES ('Não classificado', NULL::text) $$,
  'campanha com objetivo fora do catálogo exibe "Não classificado", sem resultado (RF-15)'
);
SELECT results_eq(
  $$
  SELECT apoio.metrica
  FROM normalizado.resolver_resultado_campanha(
    (SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Teste A')
  ) AS resolvido
  JOIN normalizado.campanha AS campanha ON campanha.id = resolvido.campanha_id
  JOIN normalizado.metrica_apoio_resultado AS apoio ON apoio.resultado_objetivo_id = resolvido.resultado_objetivo_id
  WHERE campanha.id_meta = pg_temp.id_meta_caso('120', 25)
  ORDER BY apoio.ordem
  $$,
  $$ VALUES ('investimento'), ('impressoes'), ('cliques_link') $$,
  '"Não classificado" exibe as métricas de apoio da regra própria do catálogo'
);

-- Conjuntos divergentes. A campanha 30 (vendas) tem um conjunto otimizado
-- para conversas e outro para conversões no site; a 31 (cadastros), dois
-- conjuntos sem investimento, com IDs da Meta de tamanhos diferentes, para
-- que a ordem de texto e a numérica discordem. Cada conjunto tem um anúncio.
INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, objetivo, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, v.objetivo, 'ACTIVE', x.id
FROM normalizado.conta_anuncio AS c
JOIN normalizado.execucao_carga AS x USING (empresa_id)
CROSS JOIN (
  VALUES ('120000000000000330', 'OUTCOME_SALES'), ('120000000000000331', 'OUTCOME_LEADS')
) AS v (id_meta, objetivo)
WHERE c.id_meta = '111111111111111';
INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, meta_otimizacao, status, execucao_id)
SELECT campanha.empresa_id, campanha.id, v.id_meta, v.meta_otimizacao, 'ACTIVE', campanha.execucao_id
FROM normalizado.campanha AS campanha
JOIN (
  VALUES
    ('120000000000000330', '121000000000000330', 'CONVERSATIONS'),
    ('120000000000000330', '121000000000000331', 'OFFSITE_CONVERSIONS'),
    ('120000000000000331', '121000000000000332', 'CONVERSATIONS'),
    ('120000000000000331', '99000000000000333', 'OFFSITE_CONVERSIONS')
) AS v (campanha, id_meta, meta_otimizacao) ON v.campanha = campanha.id_meta;
INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, status, execucao_id)
SELECT conjunto.empresa_id, conjunto.id, criativo.id, '122' || right(conjunto.id_meta, 15), 'ACTIVE', conjunto.execucao_id
FROM normalizado.conjunto_anuncio AS conjunto
JOIN normalizado.criativo AS criativo ON criativo.empresa_id = conjunto.empresa_id
WHERE conjunto.id_meta IN ('121000000000000330', '121000000000000331', '121000000000000332', '99000000000000333');

-- O investimento do anúncio do conjunto %1$L, %2$s dias antes de hoje no
-- fuso da conta, com o valor %3$s.
CREATE TEMPORARY TABLE modelo_investimento (sql text NOT NULL);
INSERT INTO modelo_investimento VALUES ($$
  INSERT INTO normalizado.metrica_diaria_anuncio (empresa_id, anuncio_id, data, investimento, execucao_id)
  SELECT anuncio.empresa_id, anuncio.id,
    (now() AT TIME ZONE conta.fuso_horario)::date - %2$s, %3$s, anuncio.execucao_id
  FROM normalizado.anuncio AS anuncio
  JOIN normalizado.conjunto_anuncio AS conjunto
    ON conjunto.empresa_id = anuncio.empresa_id AND conjunto.id = anuncio.conjunto_anuncio_id
  JOIN normalizado.conta_anuncio AS conta
    ON conta.empresa_id = anuncio.empresa_id AND conta.id_meta = '111111111111111'
  WHERE conjunto.id_meta = %1$L
$$);

-- Conversas: 100 ontem. Conversões no site: 1000 há 28 dias, fora da
-- janela, e 60 há 27 dias, o primeiro dia dela.
SELECT lives_ok(format(sql, conjunto, dias, valor), format('investimento de %s no conjunto %s', valor, conjunto))
FROM modelo_investimento
CROSS JOIN (
  VALUES
    ('121000000000000330', 1, '100'),
    ('121000000000000331', 28, '1000'),
    ('121000000000000331', 27, '60')
) AS v (conjunto, dias, valor);
SELECT results_eq(
  $$ SELECT nome_objetivo, metrica_resultado FROM resolvido_a WHERE id_meta = '120000000000000330' $$,
  $$ VALUES ('Vendas por conversa', 'conversas_iniciadas') $$,
  'conjuntos divergentes resolvem pelo de maior investimento nos últimos 28 dias, sem contar o anterior'
);
-- Mais 50 hoje no conjunto de conversões no site: 110 contra 100.
SELECT lives_ok(format(sql, '121000000000000331', 0, '50'), 'investimento de hoje no conjunto de conversões no site')
FROM modelo_investimento;
SELECT results_eq(
  $$ SELECT nome_objetivo, metrica_resultado FROM resolvido_a WHERE id_meta = '120000000000000330' $$,
  $$ VALUES ('Vendas', 'compras') $$,
  'o conjunto que passa a ter o maior investimento, contando o de hoje, define o resultado da campanha'
);
SELECT results_eq(
  $$ SELECT nome_objetivo, metrica_resultado FROM resolvido_a WHERE id_meta = '120000000000000331' $$,
  $$ VALUES ('Cadastros', 'cadastros') $$,
  'no empate, inclusive sem investimento na janela, vence o conjunto de menor ID da Meta, em ordem numérica'
);
SELECT is(
  (SELECT count(*) FROM resolvido_a WHERE id_meta IN ('120000000000000330', '120000000000000331')),
  2::bigint,
  'a campanha com vários conjuntos tem uma só linha'
);

-- Isolamento: cada empresa vê só as próprias campanhas. A B tem uma campanha
-- de vendas, com sobrescrita.
INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, objetivo, status, execucao_id)
SELECT c.empresa_id, c.id, '120000000000000399', 'OUTCOME_SALES', 'ACTIVE', x.id
FROM normalizado.conta_anuncio AS c
JOIN normalizado.execucao_carga AS x USING (empresa_id)
WHERE c.id_meta = '222222222222222';
INSERT INTO normalizado.sobrescrita_resultado_campanha (empresa_id, campanha_id, metrica_resultado, metrica_kpi)
SELECT empresa_id, id, 'conversas_iniciadas', 'custo_conversa'
FROM normalizado.campanha
WHERE id_meta = '120000000000000399';
SELECT is(
  (SELECT count(*) FROM resolvido_a),
  (SELECT count(*) FROM normalizado.campanha AS c JOIN normalizado.empresa AS e ON e.id = c.empresa_id WHERE e.nome = 'Empresa Teste A'),
  'a empresa A resolve todas as próprias campanhas, uma linha cada'
);
SELECT results_eq(
  $$
  SELECT campanha.id_meta, resolvido.metrica_resultado, resolvido.sobrescrita
  FROM normalizado.resolver_resultado_campanha(
    (SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Teste B')
  ) AS resolvido
  JOIN normalizado.campanha AS campanha ON campanha.id = resolvido.campanha_id
  $$,
  $$ VALUES ('120000000000000399', 'conversas_iniciadas', true) $$,
  'a empresa B resolve só a própria campanha, com a própria sobrescrita'
);

-- A ETL executa a resolução com os próprios privilégios, e o RLS não pode
-- esconder dela nenhuma linha que a resolução lê: as linhas inteiras, e não
-- só a contagem, porque um investimento ou uma sobrescrita invisível mudaria
-- o resultado sem mudar o número de campanhas. Como etl_carga, as funções do
-- pgTAP não ficam acessíveis: o resultado é guardado num parâmetro da
-- transação.
CREATE FUNCTION pg_temp.resumir_resolucao() RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT string_agg(resolvido::text, ';' ORDER BY resolvido.campanha_id)
  FROM normalizado.resolver_resultado_campanha(
    (SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Teste A')
  ) AS resolvido
$$;
GRANT EXECUTE ON FUNCTION pg_temp.resumir_resolucao() TO etl_carga;
SET LOCAL ROLE etl_carga;
SELECT set_config('resultado_campanha_test.resolucao_etl_carga', pg_temp.resumir_resolucao(), true);
RESET ROLE;
SELECT is(
  current_setting('resultado_campanha_test.resolucao_etl_carga'),
  pg_temp.resumir_resolucao(),
  'etl_carga resolve as campanhas da empresa com os próprios privilégios, com o mesmo resultado'
);

SELECT * FROM finish();
ROLLBACK;
