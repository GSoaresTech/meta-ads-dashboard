-- Prova a função de desempenho por entidade e período: os parâmetros, o
-- isolamento entre empresas, a aditividade entre níveis e entre períodos, as
-- razões recalculadas a partir das somas, os totais por moeda e o agrupamento
-- pelo calendário (RF-25, RF-32, RF-33, RF-34; RNF-14; REQUIREMENTS §7.1;
-- ADR-0009 §4).
BEGIN;
SELECT plan(46);

-- Atributos: o painel_leitor só executa, e a função roda com os privilégios
-- do postgres, com search_path vazio (ADR-0009 §3 e §4).
SELECT has_function(
  'analitico', 'obter_desempenho', ARRAY['text', 'uuid', 'text', 'uuid', 'date', 'date', 'text'],
  'analitico.obter_desempenho existe com a assinatura do ADR-0009 §4'
);
SELECT results_eq(
  $$
  SELECT p.provolatile = 's', p.prosecdef, p.proconfig::text = '{"search_path=\"\""}'
  FROM pg_catalog.pg_proc AS p
  WHERE p.oid = 'analitico.obter_desempenho(text, uuid, text, uuid, date, date, text)'::regprocedure
  $$,
  $$ VALUES (true, true, true) $$,
  'a função é STABLE, SECURITY DEFINER e com search_path vazio'
);
SELECT is(
  pg_get_function_result('analitico.obter_desempenho(text, uuid, text, uuid, date, date, text)'::regprocedure),
  'TABLE(nivel text, entidade_id uuid, inicio_periodo date, fim_periodo date, moeda text, metrica text, valor numeric)',
  'uma linha por entidade × período × moeda × métrica, pelo código do catálogo'
);
SELECT ok(
  has_function_privilege('painel_leitor', 'analitico.obter_desempenho(text, uuid, text, uuid, date, date, text)', 'EXECUTE'),
  'painel_leitor executa analitico.obter_desempenho'
);
SELECT ok(
  NOT has_function_privilege('etl_carga', 'analitico.obter_desempenho(text, uuid, text, uuid, date, date, text)', 'EXECUTE'),
  'etl_carga não executa analitico.obter_desempenho'
);

-- A empresa A tem uma conta em BRL, com duas campanhas, e uma em USD, com
-- uma. A empresa B tem uma conta, cujos números nunca podem aparecer para a
-- credencial de A.
INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A'), ('Empresa Teste B');
INSERT INTO normalizado.execucao_carga (empresa_id, tipo)
SELECT id, 'diaria' FROM normalizado.empresa WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');
INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, fuso_horario, moeda, execucao_id)
SELECT x.empresa_id, v.id_meta, v.fuso_horario, v.moeda, x.id
FROM (
  VALUES
    ('Empresa Teste A', '311111111111111', 'America/Sao_Paulo', 'BRL'),
    ('Empresa Teste A', '311111111111112', 'America/New_York', 'USD'),
    ('Empresa Teste B', '322222222222221', 'America/Sao_Paulo', 'BRL')
) AS v (empresa, id_meta, fuso_horario, moeda)
JOIN normalizado.empresa AS e ON e.nome = v.empresa
JOIN normalizado.execucao_carga AS x ON x.empresa_id = e.id;
INSERT INTO normalizado.criativo (empresa_id, conta_anuncio_id, id_meta, execucao_id)
SELECT empresa_id, id, id_meta || '9', execucao_id FROM normalizado.conta_anuncio
WHERE id_meta IN ('311111111111111', '311111111111112', '322222222222221');
INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, objetivo, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, v.objetivo, 'ACTIVE', c.execucao_id
FROM (
  VALUES
    ('311111111111111', '320000000000000001', 'OUTCOME_ENGAGEMENT'),
    ('311111111111111', '320000000000000002', 'OUTCOME_SALES'),
    ('311111111111112', '320000000000000003', 'OUTCOME_TRAFFIC'),
    ('322222222222221', '320000000000000004', 'OUTCOME_ENGAGEMENT')
) AS v (conta, id_meta, objetivo)
JOIN normalizado.conta_anuncio AS c ON c.id_meta = v.conta;
-- A primeira campanha tem dois conjuntos, cada um com um anúncio.
INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, 'ACTIVE', c.execucao_id
FROM (
  VALUES
    ('320000000000000001', '330000000000000001'),
    ('320000000000000001', '330000000000000002'),
    ('320000000000000002', '330000000000000003'),
    ('320000000000000003', '330000000000000004'),
    ('320000000000000004', '330000000000000005')
) AS v (campanha, id_meta)
JOIN normalizado.campanha AS c ON c.id_meta = v.campanha;
INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, status, execucao_id)
SELECT j.empresa_id, j.id, k.id, v.id_meta, 'ACTIVE', j.execucao_id
FROM (
  VALUES
    ('330000000000000001', '350000000000000001'),
    ('330000000000000002', '350000000000000002'),
    ('330000000000000003', '350000000000000003'),
    ('330000000000000004', '350000000000000004'),
    ('330000000000000005', '350000000000000005')
) AS v (conjunto, id_meta)
JOIN normalizado.conjunto_anuncio AS j ON j.id_meta = v.conjunto
JOIN normalizado.campanha AS c ON c.empresa_id = j.empresa_id AND c.id = j.campanha_id
JOIN normalizado.criativo AS k ON k.empresa_id = c.empresa_id AND k.conta_anuncio_id = c.conta_anuncio_id;

-- Os dias cruzam a virada do ano: a semana ISO 53 de 2026 vai de 28/12 a
-- 03/01 e pega dois meses. Um dia sem impressões informadas (NULL) e um dia
-- com tudo zerado testam a diferença entre NULL e zero. As ações saem das
-- colunas de quantidade, como a API as omite quando não ocorrem, e o
-- video_view é um tipo fora do catálogo.
CREATE TEMPORARY TABLE diario (
  anuncio text NOT NULL,
  data date NOT NULL,
  investimento numeric,
  impressoes bigint,
  alcance bigint,
  cliques bigint NOT NULL,
  conversas bigint NOT NULL,
  compras bigint NOT NULL,
  valor_compras numeric
);
INSERT INTO diario VALUES
  ('350000000000000001', '2026-12-27', 10.00, 100, 80, 10, 2, 0, NULL),
  ('350000000000000001', '2026-12-28', 20.00, 900, 700, 9, 1, 0, NULL),
  ('350000000000000001', '2027-01-04', 5.50, 50, 40, 0, 0, 0, NULL),
  ('350000000000000002', '2026-12-28', 7.25, 300, 250, 3, 0, 0, NULL),
  ('350000000000000002', '2027-01-01', 2.75, 100, 90, 1, 1, 0, NULL),
  ('350000000000000003', '2026-12-31', 30.00, NULL, NULL, 4, 0, 2, 150.00),
  ('350000000000000003', '2027-01-05', 0.00, 0, 0, 0, 0, 0, NULL),
  ('350000000000000004', '2026-12-29', 12.00, 400, 300, 8, 0, 0, NULL),
  ('350000000000000004', '2027-01-02', 3.00, 100, 90, 2, 0, 0, NULL),
  ('350000000000000005', '2026-12-28', 99.00, 999, 900, 99, 9, 0, NULL);
INSERT INTO normalizado.metrica_diaria_anuncio (empresa_id, anuncio_id, data, investimento, impressoes, alcance, execucao_id)
SELECT a.empresa_id, a.id, d.data, d.investimento, d.impressoes, d.alcance, a.execucao_id
FROM diario AS d
JOIN normalizado.anuncio AS a ON a.id_meta = d.anuncio;
INSERT INTO normalizado.acao_diaria_anuncio (empresa_id, anuncio_id, data, tipo_acao, quantidade, valor, execucao_id)
SELECT a.empresa_id, a.id, d.data, acao.tipo_acao, acao.quantidade, acao.valor, a.execucao_id
FROM diario AS d
JOIN normalizado.anuncio AS a ON a.id_meta = d.anuncio
CROSS JOIN LATERAL (
  VALUES
    ('link_click', d.cliques, NULL::numeric),
    ('onsite_conversion.messaging_conversation_started_7d', d.conversas, NULL),
    ('omni_purchase', d.compras, d.valor_compras),
    ('video_view', d.impressoes / 2, NULL)
) AS acao (tipo_acao, quantidade, valor)
WHERE acao.quantidade > 0;

-- Credenciais geradas pela função do banco, a cada execução, para que
-- nenhum token fique no repositório.
CREATE TEMPORARY TABLE credencial_teste (caso text PRIMARY KEY, token text NOT NULL);
INSERT INTO credencial_teste (caso, token)
SELECT v.caso, normalizado.gerar_credencial(v.escopo, e.id)
FROM (
  VALUES
    ('empresa_a', 'empresa', 'Empresa Teste A'),
    ('empresa_a_revogada', 'empresa', 'Empresa Teste A'),
    ('empresa_b', 'empresa', 'Empresa Teste B'),
    ('operador', 'operador', NULL)
) AS v (caso, escopo, empresa)
LEFT JOIN normalizado.empresa AS e ON e.nome = v.empresa;
UPDATE normalizado.credencial_acesso
SET revogado_em = now()
WHERE hash = (SELECT sha256(convert_to(token, 'UTF8')) FROM credencial_teste WHERE caso = 'empresa_a_revogada');

-- A chamada pelo nome da empresa e pelo ID da Meta da entidade em foco, que
-- deixam os casos legíveis.
CREATE TEMPORARY VIEW entidade_teste AS
SELECT id, id_meta FROM normalizado.conta_anuncio
UNION ALL SELECT id, id_meta FROM normalizado.campanha
UNION ALL SELECT id, id_meta FROM normalizado.anuncio;

CREATE FUNCTION pg_temp.desempenho(
  p_caso text, p_empresa text, p_nivel text, p_id_meta text, p_inicio date, p_fim date, p_granularidade text
)
RETURNS TABLE (nivel text, entidade_id uuid, inicio_periodo date, fim_periodo date, moeda text, metrica text, valor numeric)
LANGUAGE sql STABLE AS $$
  SELECT *
  FROM analitico.obter_desempenho(
    (SELECT token FROM credencial_teste WHERE caso = p_caso),
    (SELECT id FROM normalizado.empresa WHERE nome = p_empresa),
    p_nivel,
    (SELECT id FROM entidade_teste WHERE id_meta = p_id_meta),
    p_inicio, p_fim, p_granularidade
  )
$$;

-- Parâmetros fora do domínio levantam 22023, mesmo com credencial válida
-- (ADR-0009 §4).
SELECT throws_ok(
  format(
    $$ SELECT * FROM pg_temp.desempenho('empresa_a', 'Empresa Teste A', %L, %L, %L, %L, %L) $$,
    nivel, id_meta, inicio, fim, granularidade
  ),
  '22023',
  NULL,
  descricao
)
FROM (
  VALUES
    ('empresa', NULL, '2026-12-27', '2027-01-05', 'dia', 'nível fora do domínio é recusado'),
    (NULL, NULL, '2026-12-27', '2027-01-05', 'dia', 'nível nulo é recusado'),
    ('geral', '311111111111111', '2026-12-27', '2027-01-05', 'dia', 'entidade no nível geral é recusada'),
    ('conta', NULL, '2026-12-27', '2027-01-05', 'dia', 'nível conta sem entidade é recusado'),
    ('geral', NULL, '2026-12-27', '2027-01-05', 'trimestre', 'granularidade fora do domínio é recusada'),
    ('geral', NULL, '2026-12-27', '2027-01-05', NULL, 'granularidade nula é recusada'),
    ('geral', NULL, '2027-01-05', '2026-12-27', 'dia', 'início depois do fim é recusado'),
    ('geral', NULL, NULL, '2027-01-05', 'dia', 'início nulo é recusado'),
    ('geral', NULL, '2026-12-27', NULL, 'dia', 'fim nulo é recusado')
) AS caso (nivel, id_meta, inicio, fim, granularidade, descricao);

-- Todas as chamadas da empresa A no intervalo, em cada granularidade, com
-- foco no geral e em cada conta, campanha e anúncio dela. A linha da própria
-- entidade em foco repete o nível da chamada; as demais são das filhas.
CREATE TEMPORARY TABLE foco (nivel text NOT NULL, id_meta text);
INSERT INTO foco VALUES
  ('geral', NULL),
  ('conta', '311111111111111'), ('conta', '311111111111112'),
  ('campanha', '320000000000000001'), ('campanha', '320000000000000002'), ('campanha', '320000000000000003'),
  ('anuncio', '350000000000000001'), ('anuncio', '350000000000000002'),
  ('anuncio', '350000000000000003'), ('anuncio', '350000000000000004');
CREATE TEMPORARY TABLE resultado AS
SELECT
  foco.nivel || coalesce(foco.id_meta, '') AS chamada,
  foco.nivel AS nivel_foco,
  granularidade,
  linha.*,
  -- O geral tem entidade nula; a chave não nula facilita as junções.
  coalesce(linha.entidade_id::text, 'empresa') AS chave_entidade
FROM foco
CROSS JOIN unnest(ARRAY['dia', 'semana', 'mes', 'ano', 'periodo']) AS granularidade
CROSS JOIN LATERAL pg_temp.desempenho(
  'empresa_a', 'Empresa Teste A', foco.nivel, foco.id_meta, '2026-12-27', '2027-01-05', granularidade
) AS linha;

-- RNF-14: a credencial de uma empresa nunca devolve linha de outra. O
-- acesso negado devolve zero linhas, sem erro (ADR-0009 §4).
SELECT is_empty(
  format(
    $$ SELECT * FROM pg_temp.desempenho(%L, %L, %L, %L, '2026-12-27', '2027-01-05', 'periodo') $$,
    caso, empresa, nivel, id_meta
  ),
  descricao
)
FROM (
  VALUES
    ('empresa_a', 'Empresa Teste B', 'geral', NULL, 'RNF-14: a credencial de A não lê o geral de B'),
    ('empresa_b', 'Empresa Teste A', 'geral', NULL, 'RNF-14: a credencial de B não lê o geral de A'),
    ('empresa_a', 'Empresa Teste A', 'conta', '322222222222221', 'RNF-14: a credencial de A não lê a conta de B pela empresa A'),
    ('empresa_a', 'Empresa Teste A', 'campanha', '320000000000000004', 'RNF-14: a credencial de A não lê a campanha de B pela empresa A'),
    ('empresa_a', 'Empresa Teste A', 'anuncio', '350000000000000005', 'RNF-14: a credencial de A não lê o anúncio de B pela empresa A'),
    ('empresa_a_revogada', 'Empresa Teste A', 'geral', NULL, 'a credencial revogada não lê nada'),
    ('desconhecida', 'Empresa Teste A', 'geral', NULL, 'a credencial nula não lê nada')
) AS caso (caso, empresa, nivel, id_meta, descricao);
SELECT is_empty(
  $$
  SELECT * FROM analitico.obter_desempenho(
    translate(encode(extensions.gen_random_bytes(32), 'base64'), '+/=', '-_'),
    (SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Teste A'),
    'geral', NULL, '2026-12-27', '2027-01-05', 'periodo'
  )
  $$,
  'um token sem credencial gravada não lê nada'
);
SELECT is_empty(
  $$
  SELECT r.chave_entidade
  FROM resultado AS r
  JOIN normalizado.empresa AS e ON e.nome = 'Empresa Teste B'
  JOIN (
    SELECT empresa_id, id FROM normalizado.conta_anuncio
    UNION ALL SELECT empresa_id, id FROM normalizado.campanha
    UNION ALL SELECT empresa_id, id FROM normalizado.anuncio
  ) AS entidade ON entidade.id = r.entidade_id AND entidade.empresa_id = e.id
  $$,
  'RNF-14: nenhuma chamada da empresa A, em nível ou granularidade alguma, devolve entidade de B'
);
SELECT isnt_empty(
  $$ SELECT * FROM pg_temp.desempenho('operador', 'Empresa Teste B', 'geral', NULL, '2026-12-27', '2027-01-05', 'periodo') $$,
  'o operador lê qualquer empresa'
);
SELECT set_eq(
  $$ SELECT * FROM pg_temp.desempenho('operador', 'Empresa Teste A', 'conta', '311111111111111', '2026-12-27', '2027-01-05', 'dia') $$,
  $$ SELECT * FROM pg_temp.desempenho('empresa_a', 'Empresa Teste A', 'conta', '311111111111111', '2026-12-27', '2027-01-05', 'dia') $$,
  'o operador e o link da empresa leem os mesmos números'
);
-- O painel_leitor executa sem SELECT nas tabelas. Como ele, as funções do
-- pgTAP não ficam acessíveis: a contagem vai num parâmetro da transação.
SELECT set_config('desempenho_test.token_a', token, true) FROM credencial_teste WHERE caso = 'empresa_a';
SELECT set_config('desempenho_test.empresa_a', id::text, true) FROM normalizado.empresa WHERE nome = 'Empresa Teste A';
SET LOCAL ROLE painel_leitor;
SELECT set_config(
  'desempenho_test.linhas_painel_leitor',
  (
    SELECT count(*)
    FROM analitico.obter_desempenho(
      current_setting('desempenho_test.token_a'), current_setting('desempenho_test.empresa_a')::uuid,
      'geral', NULL, '2026-12-27', '2027-01-05', 'dia'
    )
  )::text,
  true
);
RESET ROLE;
SELECT is(
  current_setting('desempenho_test.linhas_painel_leitor')::bigint,
  (SELECT count(*) FROM resultado WHERE chamada = 'geral' AND granularidade = 'dia'),
  'painel_leitor lê pela função as mesmas linhas que o postgres'
);

-- RF-34: o geral tem um total por moeda e nenhum total que some moedas.
SELECT results_eq(
  $$
  SELECT nivel, moeda, valor
  FROM resultado
  WHERE chamada = 'geral' AND granularidade = 'periodo' AND metrica = 'investimento'
  ORDER BY nivel DESC, moeda
  $$,
  $$ VALUES ('geral', 'BRL', 75.50), ('geral', 'USD', 15.00), ('conta', 'BRL', 75.50), ('conta', 'USD', 15.00) $$,
  'RF-34: o geral traz um investimento por moeda, igual ao da conta daquela moeda'
);

-- RF-32: a soma das campanhas é o investimento da conta.
SELECT results_eq(
  $$
  SELECT r.nivel, e.id_meta, r.valor
  FROM resultado AS r
  JOIN entidade_teste AS e ON e.id = r.entidade_id
  WHERE r.chamada = 'conta311111111111111' AND r.granularidade = 'periodo' AND r.metrica = 'investimento'
  ORDER BY r.nivel DESC, e.id_meta
  $$,
  $$
  VALUES ('conta', '311111111111111', 75.50), ('campanha', '320000000000000001', 45.50),
         ('campanha', '320000000000000002', 30.00)
  $$,
  'RF-32: as campanhas somam 45,50 e 30,00, e a conta, 75,50'
);
-- RF-32: a soma dos anúncios é o investimento da campanha.
SELECT results_eq(
  $$
  SELECT r.nivel, e.id_meta, r.valor
  FROM resultado AS r
  JOIN entidade_teste AS e ON e.id = r.entidade_id
  WHERE r.chamada = 'campanha320000000000000001' AND r.granularidade = 'periodo' AND r.metrica = 'investimento'
  ORDER BY r.nivel DESC, e.id_meta
  $$,
  $$
  VALUES ('campanha', '320000000000000001', 45.50), ('anuncio', '350000000000000001', 35.50),
         ('anuncio', '350000000000000002', 10.00)
  $$,
  'RF-32: os anúncios somam 35,50 e 10,00, e a campanha, 45,50'
);
-- Em toda chamada, granularidade, período e moeda, cada métrica aditiva da
-- entidade em foco é a soma das filhas, e não há filha sem a linha do foco.
-- No período sem nenhuma filha, a entidade em foco tem zero.
SELECT is_empty(
  $$
  WITH proprio AS (
    SELECT chamada, granularidade, inicio_periodo, moeda, metrica, valor
    FROM resultado
    WHERE nivel = nivel_foco AND nivel_foco <> 'anuncio'
  ),
  filhas AS (
    SELECT chamada, granularidade, inicio_periodo, moeda, metrica, sum(valor) AS valor
    FROM resultado
    WHERE nivel <> nivel_foco
    GROUP BY chamada, granularidade, inicio_periodo, moeda, metrica
  )
  SELECT *
  FROM proprio
  FULL JOIN filhas USING (chamada, granularidade, inicio_periodo, moeda, metrica)
  WHERE metrica IN (SELECT codigo FROM normalizado.metrica WHERE aditiva)
    AND proprio.valor IS DISTINCT FROM coalesce(filhas.valor, CASE WHEN filhas.metrica IS NULL THEN 0 END)
  $$,
  'RF-32: em todo nível, período e granularidade, cada métrica aditiva é a soma das entidades filhas'
);
-- Cada filha numa chamada tem os mesmos números, inclusive as razões, que a
-- chamada com foco nela. A chamada com foco traz a mais só os períodos sem
-- entrega, com as aditivas zeradas e as razões nulas.
SELECT is_empty(
  $$
  SELECT granularidade, nivel, entidade_id, inicio_periodo, fim_periodo, moeda, metrica, valor FROM resultado WHERE nivel <> nivel_foco
  EXCEPT
  SELECT granularidade, nivel, entidade_id, inicio_periodo, fim_periodo, moeda, metrica, valor
  FROM resultado
  WHERE nivel = nivel_foco AND nivel <> 'geral'
  $$,
  'RF-32: a conta, a campanha e o anúncio têm os mesmos números como filhas e como entidade em foco'
);
SELECT is_empty(
  $$
  WITH sobra AS (
    SELECT granularidade, nivel, entidade_id, inicio_periodo, fim_periodo, moeda, metrica, valor
    FROM resultado
    WHERE nivel = nivel_foco AND nivel <> 'geral'
    EXCEPT
    SELECT granularidade, nivel, entidade_id, inicio_periodo, fim_periodo, moeda, metrica, valor FROM resultado WHERE nivel <> nivel_foco
  )
  SELECT sobra.*
  FROM sobra
  JOIN normalizado.metrica AS catalogo ON catalogo.codigo = sobra.metrica
  WHERE (catalogo.aditiva AND sobra.valor IS DISTINCT FROM 0)
     OR (NOT catalogo.aditiva AND sobra.valor IS NOT NULL)
  $$,
  'a entidade em foco só tem a mais que as filhas os períodos sem entrega, zerados'
);
-- RF-25: os dias, as semanas, os meses e os anos de cada entidade somam o
-- total do intervalo.
SELECT is_empty(
  $$
  WITH soma AS (
    SELECT chamada, granularidade, chave_entidade, moeda, metrica, sum(valor) AS valor
    FROM resultado
    WHERE granularidade <> 'periodo'
    GROUP BY chamada, granularidade, chave_entidade, moeda, metrica
  ),
  total AS (
    SELECT chamada, g.granularidade, chave_entidade, moeda, metrica, valor
    FROM resultado
    CROSS JOIN unnest(ARRAY['dia', 'semana', 'mes', 'ano']) AS g (granularidade)
    WHERE resultado.granularidade = 'periodo'
  )
  SELECT *
  FROM soma
  FULL JOIN total USING (chamada, granularidade, chave_entidade, moeda, metrica)
  WHERE metrica IN (SELECT codigo FROM normalizado.metrica WHERE aditiva)
    AND soma.valor IS DISTINCT FROM total.valor
  $$,
  'RF-25: em toda entidade, os períodos de cada granularidade somam o total do intervalo'
);

-- RF-33: o CTR do mês é a soma dos cliques sobre a soma das impressões do
-- mês, 19 ÷ 1000, e não a média dos CTRs diários, (10% + 1%) ÷ 2.
SELECT is(
  (
    SELECT valor
    FROM pg_temp.desempenho('empresa_a', 'Empresa Teste A', 'anuncio', '350000000000000001', '2026-12-01', '2026-12-31', 'mes')
    WHERE metrica = 'ctr'
  ),
  0.019,
  'RF-33: o CTR do mês é 19 cliques ÷ 1.000 impressões'
);
SELECT is(
  (
    SELECT avg(valor)
    FROM pg_temp.desempenho('empresa_a', 'Empresa Teste A', 'anuncio', '350000000000000001', '2026-12-01', '2026-12-31', 'dia')
    WHERE metrica = 'ctr'
  ),
  0.055,
  'RF-33: no mesmo caso, a média dos CTRs diários é outra, 5,5%'
);
-- Cada razão do geral em BRL sai das somas do intervalo: 75,50 investidos,
-- 1.450 impressões, 27 cliques, 4 conversas, 2 compras de 150,00 e nenhum
-- cadastro, contato pelo site, interação, ThruPlay, visita ao perfil ou
-- visita ao site, cuja razão fica nula.
SELECT results_eq(
  $$
  SELECT metrica, round(valor, 12)
  FROM resultado
  WHERE chamada = 'geral' AND nivel = 'geral' AND granularidade = 'periodo' AND moeda = 'BRL'
    AND metrica IN (SELECT codigo FROM normalizado.metrica WHERE tipo = 'derivada')
  ORDER BY metrica
  $$,
  $$
  VALUES
    ('cpc', round(75.50 / 27, 12)),
    ('cpm', round(75.50 / 1450 * 1000, 12)),
    ('ctr', round(27 / 1450::numeric, 12)),
    ('custo_cadastro', NULL),
    ('custo_compra', round(75.50 / 2, 12)),
    ('custo_contato_site', NULL),
    ('custo_conversa', round(75.50 / 4, 12)),
    ('custo_instalacao', NULL),
    ('custo_interacao', NULL),
    ('custo_thruplay', NULL),
    ('custo_visita_perfil', NULL),
    ('custo_visualizacao_pagina', NULL),
    ('roas', round(150.00 / 75.50, 12))
  $$,
  'RF-33: cada razão é recalculada a partir das somas do recorte, com o fator do catálogo'
);
-- As métricas devolvidas são as aditivas e as derivadas de operandos
-- aditivos. Alcance e frequência não são somados entre dias e vêm do alcance
-- por período (REQUIREMENTS §3.3; ADR-0006).
SELECT set_eq(
  'SELECT DISTINCT metrica FROM resultado',
  $$
  SELECT codigo FROM normalizado.metrica WHERE aditiva
  UNION
  SELECT derivada.codigo
  FROM normalizado.metrica AS derivada
  JOIN normalizado.metrica AS numerador ON numerador.codigo = derivada.numerador
  JOIN normalizado.metrica AS denominador ON denominador.codigo = derivada.denominador
  WHERE derivada.tipo = 'derivada' AND numerador.aditiva AND denominador.aditiva
  $$,
  'devolve as métricas aditivas do catálogo e as derivadas calculáveis a partir delas'
);
SELECT is_empty(
  $$ SELECT metrica FROM resultado WHERE metrica IN ('alcance', 'frequencia', 'custo_mil_alcance') $$,
  'RF-33: alcance, frequência e custo por mil pessoas alcançadas nunca saem de somas diárias'
);
-- A função lê cada coluna base pelo campo_base do catálogo. Uma métrica base
-- aditiva nova sem a coluna lida na função sairia nula em toda linha.
SELECT is_empty(
  $$
  SELECT codigo
  FROM normalizado.metrica
  WHERE tipo = 'base' AND aditiva
    AND codigo NOT IN (SELECT metrica FROM resultado WHERE valor IS NOT NULL)
  $$,
  'toda métrica base aditiva do catálogo sai com valor'
);

-- NULL não é zero (REQUIREMENTS §7.1; CLAUDE.md §5): sem impressões
-- informadas, impressões e CPM ficam nulos; a ação ausente é zero; e a razão
-- com denominador zero fica nula, nunca zero ou infinito.
SELECT results_eq(
  $$
  SELECT r.metrica, r.valor
  FROM resultado AS r
  JOIN entidade_teste AS e ON e.id = r.entidade_id
  WHERE r.chamada = 'conta311111111111111' AND r.granularidade = 'dia' AND r.inicio_periodo = '2026-12-31'
    AND e.id_meta = '320000000000000002'
    AND r.metrica IN ('investimento', 'impressoes', 'cpm', 'ctr', 'compras', 'valor_compras', 'roas', 'conversas_iniciadas')
  ORDER BY r.metrica
  $$,
  $$
  VALUES ('compras', 2::numeric), ('conversas_iniciadas', 0), ('cpm', NULL), ('ctr', NULL),
         ('impressoes', NULL), ('investimento', 30.00), ('roas', 5), ('valor_compras', 150.00)
  $$,
  'sem impressões informadas, impressões, CPM e CTR ficam nulos, e a ação ausente é zero'
);
SELECT results_eq(
  $$
  SELECT metrica, valor
  FROM resultado
  WHERE chamada = 'anuncio350000000000000001' AND granularidade = 'dia' AND inicio_periodo = '2027-01-04'
    AND metrica IN ('cliques_link', 'cpc', 'ctr')
  ORDER BY metrica
  $$,
  $$ VALUES ('cliques_link', 0::numeric), ('cpc', NULL), ('ctr', 0) $$,
  'sem cliques, o CPC fica nulo e o CTR é zero'
);
SELECT results_eq(
  $$
  SELECT metrica, valor
  FROM resultado
  WHERE chamada = 'anuncio350000000000000003' AND granularidade = 'dia' AND inicio_periodo = '2027-01-05'
    AND metrica IN ('investimento', 'impressoes', 'cpm', 'ctr', 'roas')
  ORDER BY metrica
  $$,
  $$ VALUES ('cpm', NULL::numeric), ('ctr', NULL), ('impressoes', 0), ('investimento', 0.00), ('roas', NULL) $$,
  'num dia todo zerado, as métricas são zero e as razões, nulas'
);
SELECT is(
  (
    SELECT valor
    FROM resultado AS r
    JOIN entidade_teste AS e ON e.id = r.entidade_id
    WHERE r.chamada = 'conta311111111111111' AND r.granularidade = 'periodo'
      AND e.id_meta = '320000000000000002' AND r.metrica = 'conversas_iniciadas'
  ),
  0::numeric,
  'a campanha sem nenhuma conversa no intervalo tem zero conversas, não nulo'
);

-- RF-25: a série da entidade em foco tem um ponto por período, mesmo sem
-- entrega. Em 30/12 nenhuma conta da empresa A teve entrega: o investimento é
-- zero, e as razões ficam nulas.
SELECT results_eq(
  $$
  SELECT moeda, metrica, valor
  FROM resultado
  WHERE chamada = 'geral' AND nivel = 'geral' AND granularidade = 'dia' AND inicio_periodo = '2026-12-30'
    AND metrica IN ('investimento', 'impressoes', 'cliques_link', 'ctr', 'cpc')
  ORDER BY moeda, metrica
  $$,
  $$
  VALUES ('BRL', 'cliques_link', 0::numeric), ('BRL', 'cpc', NULL), ('BRL', 'ctr', NULL), ('BRL', 'impressoes', 0),
         ('BRL', 'investimento', 0), ('USD', 'cliques_link', 0), ('USD', 'cpc', NULL), ('USD', 'ctr', NULL),
         ('USD', 'impressoes', 0), ('USD', 'investimento', 0)
  $$,
  'RF-25: o dia sem entrega aparece na série do geral, com zero investido e razões nulas, em cada moeda'
);

-- Calendário: cada período é o do calendário, cortado no intervalo pedido.
-- A semana ISO 53 de 2026 cruza o ano, e todo dia do intervalo aparece.
SELECT set_eq(
  $$ SELECT DISTINCT granularidade, inicio_periodo, fim_periodo FROM resultado WHERE chamada = 'geral' $$,
  $$
  VALUES
    ('dia', '2026-12-27'::date, '2026-12-27'::date), ('dia', '2026-12-28', '2026-12-28'),
    ('dia', '2026-12-29', '2026-12-29'), ('dia', '2026-12-30', '2026-12-30'),
    ('dia', '2026-12-31', '2026-12-31'), ('dia', '2027-01-01', '2027-01-01'),
    ('dia', '2027-01-02', '2027-01-02'), ('dia', '2027-01-03', '2027-01-03'),
    ('dia', '2027-01-04', '2027-01-04'), ('dia', '2027-01-05', '2027-01-05'),
    ('semana', '2026-12-27', '2026-12-27'), ('semana', '2026-12-28', '2027-01-03'), ('semana', '2027-01-04', '2027-01-05'),
    ('mes', '2026-12-27', '2026-12-31'), ('mes', '2027-01-01', '2027-01-05'),
    ('ano', '2026-12-27', '2026-12-31'), ('ano', '2027-01-01', '2027-01-05'),
    ('periodo', '2026-12-27', '2027-01-05')
  $$,
  'os períodos seguem o dia, a semana ISO, o mês e o ano do calendário, cortados no intervalo, sem buracos'
);
SELECT set_eq(
  $$
  SELECT DISTINCT inicio_periodo, fim_periodo
  FROM pg_temp.desempenho('empresa_a', 'Empresa Teste A', 'geral', NULL, '2026-12-30', '2027-01-05', 'semana')
  $$,
  $$ VALUES ('2026-12-30'::date, '2027-01-03'::date), ('2027-01-04', '2027-01-05') $$,
  'a semana que começa antes do intervalo vem só com os dias pedidos'
);

SELECT * FROM finish();
ROLLBACK;
