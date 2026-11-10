-- Prova a função de alcance e frequência por entidade e período: os
-- parâmetros, o isolamento entre empresas e cada regra de alcance e
-- frequência da §3.3 do REQUIREMENTS, com o período em andamento, o Geral e o
-- período sem linha de alcance do ADR-0016 (RF-33; RNF-14; ADR-0006;
-- ADR-0009 §4).
BEGIN;
SELECT plan(63);

-- Atributos: o painel_leitor só executa, e a função roda com os privilégios
-- do postgres, com search_path vazio (ADR-0009 §3 e §4).
SELECT has_function(
  'analitico', 'obter_alcance', ARRAY['text', 'uuid', 'text', 'uuid', 'date', 'date', 'text'],
  'analitico.obter_alcance existe com a assinatura do ADR-0009 §4'
);
SELECT results_eq(
  $$
  SELECT p.provolatile = 's', p.prosecdef, p.proconfig::text = '{"search_path=\"\""}'
  FROM pg_catalog.pg_proc AS p
  WHERE p.oid = 'analitico.obter_alcance(text, uuid, text, uuid, date, date, text)'::regprocedure
  $$,
  $$ VALUES (true, true, true) $$,
  'a função é STABLE, SECURITY DEFINER e com search_path vazio'
);
SELECT is(
  pg_get_function_result('analitico.obter_alcance(text, uuid, text, uuid, date, date, text)'::regprocedure),
  'TABLE(nivel text, entidade_id uuid, inicio_periodo date, fim_periodo date, moeda text, metrica text, valor numeric, fim_apurado date, motivo text)',
  'uma linha por entidade × período × moeda × métrica, com o fim apurado ou o motivo da indisponibilidade'
);
SELECT ok(
  has_function_privilege('painel_leitor', 'analitico.obter_alcance(text, uuid, text, uuid, date, date, text)', 'EXECUTE'),
  'painel_leitor executa analitico.obter_alcance'
);
SELECT ok(
  NOT has_function_privilege('etl_carga', 'analitico.obter_alcance(text, uuid, text, uuid, date, date, text)', 'EXECUTE'),
  'etl_carga não executa analitico.obter_alcance'
);
-- A agregação interna roda com os privilégios de quem chama e é planejada
-- a cada chamada, para que o plano genérico não passe do RNF-06 na mesma
-- conexão (ADR-0009 §4).
SELECT results_eq(
  $$
  SELECT
    p.provolatile = 's',
    p.prosecdef,
    p.proconfig::text = '{"search_path=\"\"",plan_cache_mode=force_custom_plan}'
  FROM pg_catalog.pg_proc AS p
  WHERE p.oid = 'normalizado.agregar_alcance(uuid, text, uuid, date, date, text)'::regprocedure
  $$,
  $$ VALUES (true, false, true) $$,
  'a agregação interna é STABLE, SECURITY INVOKER e planejada a cada chamada'
);

-- A empresa A tem uma conta em BRL, com duas campanhas, e uma em USD, com
-- uma. A empresa B tem uma conta só, cujos números nunca podem aparecer para
-- a credencial de A.
INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A'), ('Empresa Teste B');
INSERT INTO normalizado.execucao_carga (empresa_id, tipo)
SELECT id, 'diaria' FROM normalizado.empresa WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');
INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, fuso_horario, moeda, execucao_id)
SELECT x.empresa_id, v.id_meta, v.fuso_horario, v.moeda, x.id
FROM (
  VALUES
    ('Empresa Teste A', '411111111111111', 'America/Sao_Paulo', 'BRL'),
    ('Empresa Teste A', '411111111111112', 'America/New_York', 'USD'),
    ('Empresa Teste B', '422222222222221', 'America/Sao_Paulo', 'BRL')
) AS v (empresa, id_meta, fuso_horario, moeda)
JOIN normalizado.empresa AS e ON e.nome = v.empresa
JOIN normalizado.execucao_carga AS x ON x.empresa_id = e.id;
INSERT INTO normalizado.criativo (empresa_id, conta_anuncio_id, id_meta, execucao_id)
SELECT empresa_id, id, id_meta || '9', execucao_id FROM normalizado.conta_anuncio
WHERE id_meta IN ('411111111111111', '411111111111112', '422222222222221');
INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, objetivo, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, 'OUTCOME_AWARENESS', 'ACTIVE', c.execucao_id
FROM (
  VALUES
    ('411111111111111', '420000000000000001'),
    ('411111111111111', '420000000000000002'),
    ('411111111111112', '420000000000000003'),
    ('422222222222221', '420000000000000004')
) AS v (conta, id_meta)
JOIN normalizado.conta_anuncio AS c ON c.id_meta = v.conta;
-- A primeira campanha tem dois conjuntos, cada um com um anúncio.
INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, 'ACTIVE', c.execucao_id
FROM (
  VALUES
    ('420000000000000001', '430000000000000001'),
    ('420000000000000001', '430000000000000002'),
    ('420000000000000002', '430000000000000003'),
    ('420000000000000003', '430000000000000004'),
    ('420000000000000004', '430000000000000005')
) AS v (campanha, id_meta)
JOIN normalizado.campanha AS c ON c.id_meta = v.campanha;
INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, status, execucao_id)
SELECT j.empresa_id, j.id, k.id, v.id_meta, 'ACTIVE', j.execucao_id
FROM (
  VALUES
    ('430000000000000001', '450000000000000001'),
    ('430000000000000002', '450000000000000002'),
    ('430000000000000003', '450000000000000003'),
    ('430000000000000004', '450000000000000004'),
    ('430000000000000005', '450000000000000005')
) AS v (conjunto, id_meta)
JOIN normalizado.conjunto_anuncio AS j ON j.id_meta = v.conjunto
JOIN normalizado.campanha AS c ON c.empresa_id = j.empresa_id AND c.id = j.campanha_id
JOIN normalizado.criativo AS k ON k.empresa_id = c.empresa_id AND k.conta_anuncio_id = c.conta_anuncio_id;

-- Os dias de 2035, o último ano do calendário, ficam depois do limite de 37
-- meses enquanto o calendário valer (R-19); os de 2023 já ficaram antes
-- dele. Em 2035, 1º de janeiro é segunda-feira, e a semana, o mês e o ano
-- começam no mesmo dia. A rotina diária mais recente extraiu até 13/02, e a
-- carga horária já trouxe o dia 14 (ADR-0005).
INSERT INTO normalizado.metrica_diaria_anuncio (empresa_id, anuncio_id, data, investimento, impressoes, alcance, execucao_id)
SELECT a.empresa_id, a.id, v.data, v.investimento, v.impressoes, v.impressoes, a.execucao_id
FROM (
  VALUES
    ('450000000000000001', '2023-01-04'::date, 1.00, 100),
    ('450000000000000001', '2035-01-02', 10.00, 1000),
    ('450000000000000001', '2035-01-09', 20.00, 2000),
    ('450000000000000001', '2035-02-05', 5.00, 500),
    ('450000000000000001', '2035-02-14', 7.00, 700),
    ('450000000000000002', '2035-01-03', 4.00, 400),
    ('450000000000000002', '2035-02-12', 6.00, 600),
    ('450000000000000003', '2035-01-10', 8.00, 800),
    ('450000000000000003', '2035-03-05', 3.00, 300),
    ('450000000000000004', '2035-01-02', 2.00, 200),
    ('450000000000000005', '2035-01-02', 50.00, 5000)
) AS v (anuncio, data, investimento, impressoes)
JOIN normalizado.anuncio AS a ON a.id_meta = v.anuncio;

-- O alcance extraído. A semana, o mês e o ano em andamento vão até 13/02
-- (ADR-0006). As impressões de cada resposta diferem da soma dos dias, para
-- provar de onde a frequência as lê. Na primeira campanha, de extrações
-- paradas, o mês vai só até 20/01, e o ano, até 31/01. A semana de 05/03 da
-- conta vai só até o próprio dia, como na rotina diária da terça-feira.
-- Nenhuma linha cobre o mês de março, com entrega, nem as semanas da
-- primeira campanha, e o ano e os meses de 2023 começam antes do limite.
CREATE TEMPORARY VIEW entidade_teste AS
SELECT empresa_id, id, id_meta FROM normalizado.conta_anuncio
UNION ALL SELECT empresa_id, id, id_meta FROM normalizado.campanha
UNION ALL SELECT empresa_id, id, id_meta FROM normalizado.anuncio;
INSERT INTO normalizado.alcance_periodo
  (empresa_id, conta_anuncio_id, campanha_id, anuncio_id, tipo_periodo, inicio_periodo, fim_periodo, alcance, impressoes, execucao_id)
SELECT
  e.empresa_id,
  (SELECT id FROM normalizado.conta_anuncio WHERE id = e.id),
  (SELECT id FROM normalizado.campanha WHERE id = e.id),
  (SELECT id FROM normalizado.anuncio WHERE id = e.id),
  v.tipo_periodo, v.inicio, v.fim, v.alcance, v.impressoes,
  (SELECT x.id FROM normalizado.execucao_carga AS x WHERE x.empresa_id = e.empresa_id)
FROM (
  VALUES
    ('411111111111111', 'semana', '2023-01-02'::date, '2023-01-08'::date, 90, 100),
    ('411111111111111', 'semana', '2035-01-01', '2035-01-07', 1000, 1500),
    ('411111111111111', 'semana', '2035-01-08', '2035-01-14', 1600, 3000),
    ('411111111111111', 'semana', '2035-02-05', '2035-02-11', 480, 500),
    ('411111111111111', 'semana', '2035-02-12', '2035-02-13', 550, 600),
    ('411111111111111', 'semana', '2035-03-05', '2035-03-05', 250, 300),
    ('411111111111111', 'mes', '2035-01-01', '2035-01-31', 2000, 4500),
    ('411111111111111', 'mes', '2035-02-01', '2035-02-13', 800, 1200),
    ('411111111111111', 'ano', '2035-01-01', '2035-02-13', 2500, 5600),
    ('420000000000000001', 'mes', '2035-01-01', '2035-01-20', 1400, 3000),
    ('420000000000000001', 'ano', '2035-01-01', '2035-01-31', 1600, 3400),
    ('420000000000000002', 'semana', '2035-01-08', '2035-01-14', 640, 1000),
    ('420000000000000002', 'mes', '2035-01-01', '2035-01-31', 640, 1000),
    ('450000000000000001', 'mes', '2035-01-01', '2035-01-31', 1500, 3000),
    ('450000000000000002', 'mes', '2035-01-01', '2035-01-31', 320, 400),
    ('450000000000000003', 'mes', '2035-01-01', '2035-01-31', 640, 1000),
    ('411111111111112', 'mes', '2035-01-01', '2035-01-31', 150, 200),
    ('420000000000000003', 'mes', '2035-01-01', '2035-01-31', 150, 200),
    ('450000000000000004', 'mes', '2035-01-01', '2035-01-31', 150, 200),
    ('422222222222221', 'mes', '2035-01-01', '2035-01-31', 4000, 6000),
    ('420000000000000004', 'mes', '2035-01-01', '2035-01-31', 4000, 6000),
    ('450000000000000005', 'mes', '2035-01-01', '2035-01-31', 4000, 6000)
) AS v (id_meta, tipo_periodo, inicio, fim, alcance, impressoes)
JOIN entidade_teste AS e ON e.id_meta = v.id_meta;

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

-- A chamada pelo nome da empresa e pelo ID da Meta da entidade em foco, e o
-- retorno com o ID da Meta de cada entidade, que deixam os casos legíveis.
CREATE FUNCTION pg_temp.alcance(
  p_caso text, p_empresa text, p_nivel text, p_id_meta text, p_inicio date, p_fim date, p_granularidade text
)
RETURNS TABLE (
  nivel text, entidade_id uuid, inicio_periodo date, fim_periodo date, moeda text, metrica text,
  valor numeric, fim_apurado date, motivo text
)
LANGUAGE sql STABLE AS $$
  SELECT *
  FROM analitico.obter_alcance(
    (SELECT token FROM credencial_teste WHERE caso = p_caso),
    (SELECT id FROM normalizado.empresa WHERE nome = p_empresa),
    p_nivel,
    (SELECT id FROM entidade_teste WHERE id_meta = p_id_meta),
    p_inicio, p_fim, p_granularidade
  )
$$;
CREATE FUNCTION pg_temp.alcance_a(p_nivel text, p_id_meta text, p_inicio date, p_fim date, p_granularidade text)
RETURNS TABLE (
  nivel text, id_meta text, inicio_periodo date, fim_periodo date, moeda text, metrica text,
  valor numeric, fim_apurado date, motivo text
)
LANGUAGE sql STABLE AS $$
  SELECT r.nivel, e.id_meta, r.inicio_periodo, r.fim_periodo, r.moeda, r.metrica, r.valor, r.fim_apurado, r.motivo
  FROM pg_temp.alcance('empresa_a', 'Empresa Teste A', p_nivel, p_id_meta, p_inicio, p_fim, p_granularidade) AS r
  LEFT JOIN entidade_teste AS e ON e.id = r.entidade_id
$$;

-- Parâmetros fora do domínio levantam 22023, mesmo com credencial válida
-- (ADR-0009 §4).
SELECT throws_ok(
  format(
    $$ SELECT * FROM pg_temp.alcance('empresa_a', 'Empresa Teste A', %L, %L, %L, %L, %L) $$,
    nivel, id_meta, inicio, fim, granularidade
  ),
  '22023',
  NULL,
  descricao
)
FROM (
  VALUES
    ('empresa', NULL, '2035-01-01', '2035-01-31', 'mes', 'nível fora do domínio é recusado'),
    (NULL, NULL, '2035-01-01', '2035-01-31', 'mes', 'nível nulo é recusado'),
    ('geral', '411111111111111', '2035-01-01', '2035-01-31', 'mes', 'entidade no nível geral é recusada'),
    ('conta', NULL, '2035-01-01', '2035-01-31', 'mes', 'nível conta sem entidade é recusado'),
    ('geral', NULL, '2035-01-01', '2035-01-31', 'trimestre', 'granularidade fora do domínio é recusada'),
    ('geral', NULL, '2035-01-01', '2035-01-31', NULL, 'granularidade nula é recusada'),
    ('geral', NULL, '2035-01-31', '2035-01-01', 'mes', 'início depois do fim é recusado'),
    ('geral', NULL, NULL, '2035-01-31', 'mes', 'início nulo é recusado'),
    ('geral', NULL, '2035-01-01', NULL, 'mes', 'fim nulo é recusado')
) AS caso (nivel, id_meta, inicio, fim, granularidade, descricao);

-- Todas as chamadas da empresa A no primeiro trimestre de 2035, em cada
-- granularidade, com foco no geral e em cada conta, campanha e anúncio dela.
CREATE TEMPORARY TABLE foco (nivel text NOT NULL, id_meta text);
INSERT INTO foco VALUES
  ('geral', NULL),
  ('conta', '411111111111111'), ('conta', '411111111111112'),
  ('campanha', '420000000000000001'), ('campanha', '420000000000000002'), ('campanha', '420000000000000003'),
  ('anuncio', '450000000000000001'), ('anuncio', '450000000000000002'),
  ('anuncio', '450000000000000003'), ('anuncio', '450000000000000004');
CREATE TEMPORARY TABLE resultado AS
SELECT foco.nivel AS nivel_foco, foco.id_meta AS id_meta_foco, granularidade, linha.*
FROM foco
CROSS JOIN unnest(ARRAY['dia', 'semana', 'mes', 'ano', 'periodo']) AS granularidade
CROSS JOIN LATERAL pg_temp.alcance(
  'empresa_a', 'Empresa Teste A', foco.nivel, foco.id_meta, '2035-01-01', '2035-03-31', granularidade
) AS linha;

-- RNF-14: a credencial de uma empresa nunca devolve linha de outra. O
-- acesso negado devolve zero linhas, sem erro (ADR-0009 §4).
SELECT is_empty(
  format(
    $$ SELECT * FROM pg_temp.alcance(%L, %L, %L, %L, '2035-01-01', '2035-01-31', 'periodo') $$,
    caso, empresa, nivel, id_meta
  ),
  descricao
)
FROM (
  VALUES
    ('empresa_a', 'Empresa Teste B', 'geral', NULL, 'RNF-14: a credencial de A não lê o geral de B'),
    ('empresa_b', 'Empresa Teste A', 'geral', NULL, 'RNF-14: a credencial de B não lê o geral de A'),
    ('empresa_a', 'Empresa Teste A', 'conta', '422222222222221', 'RNF-14: a credencial de A não lê a conta de B pela empresa A'),
    ('empresa_a', 'Empresa Teste A', 'campanha', '420000000000000004', 'RNF-14: a credencial de A não lê a campanha de B pela empresa A'),
    ('empresa_a', 'Empresa Teste A', 'anuncio', '450000000000000005', 'RNF-14: a credencial de A não lê o anúncio de B pela empresa A'),
    ('empresa_a_revogada', 'Empresa Teste A', 'geral', NULL, 'a credencial revogada não lê nada'),
    ('desconhecida', 'Empresa Teste A', 'geral', NULL, 'a credencial nula não lê nada')
) AS caso (caso, empresa, nivel, id_meta, descricao);
SELECT is_empty(
  $$
  SELECT * FROM analitico.obter_alcance(
    translate(encode(extensions.gen_random_bytes(32), 'base64'), '+/=', '-_'),
    (SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Teste A'),
    'geral', NULL, '2035-01-01', '2035-01-31', 'periodo'
  )
  $$,
  'um token sem credencial gravada não lê nada'
);
SELECT isnt_empty(
  $$ SELECT * FROM resultado $$,
  'as chamadas da empresa A devolvem linhas'
);
SELECT is_empty(
  $$
  SELECT r.entidade_id
  FROM resultado AS r
  JOIN entidade_teste AS e ON e.id = r.entidade_id
  JOIN normalizado.empresa AS b ON b.id = e.empresa_id AND b.nome = 'Empresa Teste B'
  $$,
  'RNF-14: nenhuma chamada da empresa A, em nível ou granularidade alguma, devolve entidade de B'
);
SELECT isnt_empty(
  $$ SELECT * FROM pg_temp.alcance('operador', 'Empresa Teste B', 'geral', NULL, '2035-01-01', '2035-01-31', 'periodo') $$,
  'o operador lê qualquer empresa'
);
SELECT set_eq(
  $$ SELECT * FROM pg_temp.alcance('operador', 'Empresa Teste A', 'conta', '411111111111111', '2035-01-01', '2035-03-31', 'semana') $$,
  $$ SELECT * FROM pg_temp.alcance('empresa_a', 'Empresa Teste A', 'conta', '411111111111111', '2035-01-01', '2035-03-31', 'semana') $$,
  'o operador e o link da empresa leem os mesmos números'
);
-- O painel_leitor executa sem SELECT nas tabelas. Como ele, as funções do
-- pgTAP não ficam acessíveis: a contagem vai num parâmetro da transação.
SELECT set_config('alcance_frequencia_test.token_a', token, true) FROM credencial_teste WHERE caso = 'empresa_a';
SELECT set_config('alcance_frequencia_test.empresa_a', id::text, true) FROM normalizado.empresa WHERE nome = 'Empresa Teste A';
SET LOCAL ROLE painel_leitor;
SELECT set_config(
  'alcance_frequencia_test.linhas_painel_leitor',
  (
    SELECT count(*)
    FROM analitico.obter_alcance(
      current_setting('alcance_frequencia_test.token_a'), current_setting('alcance_frequencia_test.empresa_a')::uuid,
      'geral', NULL, '2035-01-01', '2035-03-31', 'semana'
    )
  )::text,
  true
);
RESET ROLE;
SELECT is(
  current_setting('alcance_frequencia_test.linhas_painel_leitor')::bigint,
  (SELECT count(*) FROM resultado WHERE nivel_foco = 'geral' AND granularidade = 'semana'),
  'painel_leitor lê pela função as mesmas linhas que o postgres'
);

-- As métricas vêm do catálogo (ADR-0007): as bases não aditivas e as
-- derivadas com um operando entre elas. Com a obter_desempenho, que fica
-- com as demais, a leitura cobre o catálogo inteiro, sem métrica nas duas
-- (ADR-0009 §4).
CREATE FUNCTION pg_temp.desempenho_metricas()
RETURNS TABLE (metrica text)
LANGUAGE sql STABLE AS $$
  SELECT DISTINCT d.metrica
  FROM analitico.obter_desempenho(
    (SELECT token FROM credencial_teste WHERE caso = 'empresa_a'),
    (SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Teste A'),
    'geral', NULL, '2035-01-01', '2035-03-31', 'periodo'
  ) AS d
$$;
SELECT set_eq(
  $$ SELECT DISTINCT metrica FROM resultado $$,
  $$
  SELECT metrica.codigo
  FROM normalizado.metrica AS metrica
  LEFT JOIN normalizado.metrica AS numerador ON numerador.codigo = metrica.numerador
  LEFT JOIN normalizado.metrica AS denominador ON denominador.codigo = metrica.denominador
  WHERE (metrica.tipo = 'base' AND NOT metrica.aditiva)
     OR (numerador.tipo = 'base' AND NOT numerador.aditiva)
     OR (denominador.tipo = 'base' AND NOT denominador.aditiva)
  $$,
  'as métricas são o alcance e as derivadas que dependem dele, pelo catálogo'
);
SELECT set_eq(
  $$ SELECT metrica FROM resultado UNION SELECT metrica FROM pg_temp.desempenho_metricas() $$,
  $$ SELECT codigo FROM normalizado.metrica $$,
  'a obter_alcance e a obter_desempenho cobrem juntas todo o catálogo'
);
SELECT is_empty(
  $$ SELECT metrica FROM resultado INTERSECT SELECT metrica FROM pg_temp.desempenho_metricas() $$,
  'nenhuma métrica sai das duas funções'
);

-- §3.3: semana ISO, mês ou ano → o valor extraído da API para o período e a
-- entidade (ADR-0006). A frequência são as impressões da mesma resposta ÷ o
-- alcance, e o custo por mil pessoas alcançadas, o investimento dos mesmos
-- dias ÷ o alcance × 1000.
SELECT results_eq(
  $$
  SELECT nivel, id_meta, metrica, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2035-01-08', '2035-01-14', 'periodo')
  WHERE nivel = 'conta'
  ORDER BY metrica
  $$,
  $$
  VALUES
    ('conta', '411111111111111', 'alcance', 1600::numeric, '2035-01-14'::date, NULL::text),
    ('conta', '411111111111111', 'custo_mil_alcance', 17.5, '2035-01-14', NULL),
    ('conta', '411111111111111', 'frequencia', 1.875, '2035-01-14', NULL)
  $$,
  '§3.3: o intervalo que é uma semana ISO mostra o alcance extraído da semana'
);
SELECT results_eq(
  $$
  SELECT nivel, id_meta, moeda, metrica, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2035-01-01', '2035-01-31', 'periodo')
  ORDER BY nivel DESC, id_meta, metrica
  $$,
  $$
  VALUES
    ('conta', '411111111111111', 'BRL', 'alcance', 2000::numeric, '2035-01-31'::date, NULL::text),
    ('conta', '411111111111111', 'BRL', 'custo_mil_alcance', 21, '2035-01-31', NULL),
    ('conta', '411111111111111', 'BRL', 'frequencia', 2.25, '2035-01-31', NULL),
    ('campanha', '420000000000000001', 'BRL', 'alcance', 1600, '2035-01-31', NULL),
    ('campanha', '420000000000000001', 'BRL', 'custo_mil_alcance', 21.25, '2035-01-31', NULL),
    ('campanha', '420000000000000001', 'BRL', 'frequencia', 2.125, '2035-01-31', NULL),
    ('campanha', '420000000000000002', 'BRL', 'alcance', 640, '2035-01-31', NULL),
    ('campanha', '420000000000000002', 'BRL', 'custo_mil_alcance', 12.5, '2035-01-31', NULL),
    ('campanha', '420000000000000002', 'BRL', 'frequencia', 1.5625, '2035-01-31', NULL)
  $$,
  '§3.3: o intervalo que é um mês mostra o alcance extraído do mês, na conta e em cada campanha'
);
SELECT results_eq(
  $$
  SELECT id_meta, valor
  FROM pg_temp.alcance_a('campanha', '420000000000000001', '2035-01-01', '2035-01-31', 'periodo')
  WHERE metrica = 'alcance'
  ORDER BY nivel DESC, id_meta
  $$,
  $$ VALUES ('420000000000000001', 1600::numeric), ('450000000000000001', 1500), ('450000000000000002', 320) $$,
  '§3.3: a campanha e cada anúncio dela mostram o próprio alcance extraído'
);
SELECT results_eq(
  $$
  SELECT inicio_periodo, fim_periodo, metrica, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2035-01-01', '2035-02-13', 'ano')
  WHERE nivel = 'conta'
  ORDER BY metrica
  $$,
  $$
  VALUES
    ('2035-01-01'::date, '2035-02-13'::date, 'alcance', 2500::numeric, '2035-02-13'::date, NULL::text),
    ('2035-01-01', '2035-02-13', 'custo_mil_alcance', 21.2, '2035-02-13', NULL),
    ('2035-01-01', '2035-02-13', 'frequencia', 2.24, '2035-02-13', NULL)
  $$,
  '§3.3: o ano da série mostra o alcance extraído do ano'
);
SELECT results_eq(
  $$
  SELECT inicio_periodo, fim_periodo, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2035-01-01', '2035-01-14', 'semana')
  WHERE nivel = 'conta' AND metrica = 'alcance'
  ORDER BY inicio_periodo
  $$,
  $$
  VALUES
    ('2035-01-01'::date, '2035-01-07'::date, 1000::numeric, '2035-01-07'::date, NULL::text),
    ('2035-01-08', '2035-01-14', 1600, '2035-01-14', NULL)
  $$,
  '§3.3: cada semana ISO da série mostra o alcance extraído dela'
);

-- RF-33: o alcance nunca é somado entre entidades nem entre períodos.
SELECT isnt(
  (SELECT valor FROM resultado WHERE nivel_foco = 'conta' AND id_meta_foco = '411111111111111'
     AND granularidade = 'mes' AND nivel = 'conta' AND inicio_periodo = '2035-01-01' AND metrica = 'alcance'),
  (SELECT sum(valor) FROM resultado WHERE nivel_foco = 'conta' AND id_meta_foco = '411111111111111'
     AND granularidade = 'mes' AND nivel = 'campanha' AND inicio_periodo = '2035-01-01' AND metrica = 'alcance'),
  'RF-33: o alcance da conta no mês não é a soma do alcance das campanhas'
);
SELECT isnt(
  (SELECT valor FROM resultado WHERE nivel_foco = 'conta' AND id_meta_foco = '411111111111111'
     AND granularidade = 'mes' AND nivel = 'conta' AND inicio_periodo = '2035-01-01' AND metrica = 'alcance'),
  (SELECT sum(valor) FROM resultado WHERE nivel_foco = 'conta' AND id_meta_foco = '411111111111111'
     AND granularidade = 'semana' AND nivel = 'conta' AND fim_periodo <= '2035-01-31' AND metrica = 'alcance'),
  'RF-33: o alcance do mês não é a soma do alcance das semanas'
);

-- ADR-0016: o período em andamento, extraído até 13/02, coincide com o
-- período exibido que começa no primeiro dia dele e chega pelo menos a
-- 13/02. O custo usa só o investimento até 13/02, sem o dia 14.
SELECT results_eq(
  $$
  SELECT nivel, metrica, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2035-02-01', '2035-02-14', 'periodo')
  WHERE nivel = 'conta'
  ORDER BY metrica
  $$,
  $$
  VALUES
    ('conta', 'alcance', 800::numeric, '2035-02-13'::date, NULL::text),
    ('conta', 'custo_mil_alcance', 13.75, '2035-02-13', NULL),
    ('conta', 'frequencia', 1.5, '2035-02-13', NULL)
  $$,
  'ADR-0016: "este mês" mostra o alcance do mês em andamento até o último dia extraído'
);
SELECT results_eq(
  $$
  SELECT metrica, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2035-01-01', '2035-02-14', 'periodo')
  WHERE nivel = 'conta'
  ORDER BY metrica
  $$,
  $$
  VALUES
    ('alcance', 2500::numeric, '2035-02-13'::date, NULL::text),
    ('custo_mil_alcance', 21.2, '2035-02-13', NULL),
    ('frequencia', 2.24, '2035-02-13', NULL)
  $$,
  'ADR-0016: "este ano" mostra o alcance do ano em andamento até o último dia extraído'
);
SELECT results_eq(
  $$
  SELECT inicio_periodo, fim_periodo, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2035-02-01', '2035-02-14', 'semana')
  WHERE nivel = 'conta' AND metrica = 'alcance'
  ORDER BY inicio_periodo
  $$,
  $$
  VALUES
    ('2035-02-01'::date, '2035-02-04'::date, NULL::numeric, NULL::date, 'periodo_livre'),
    ('2035-02-05', '2035-02-11', 480, '2035-02-11', NULL),
    ('2035-02-12', '2035-02-14', 550, '2035-02-13', NULL)
  $$,
  'ADR-0016: na série, a semana em andamento mostra o alcance até o último dia extraído, e a semana cortada é período livre'
);
SELECT results_eq(
  $$
  SELECT DISTINCT nivel, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2035-02-01', '2035-02-10', 'periodo')
  ORDER BY nivel DESC
  $$,
  $$
  VALUES
    ('conta', NULL::numeric, NULL::date, 'periodo_livre'),
    ('campanha', NULL, NULL, 'periodo_livre')
  $$,
  'ADR-0016: o período exibido que termina antes do último dia extraído é período livre'
);
SELECT results_eq(
  $$
  SELECT valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('campanha', '420000000000000001', '2035-01-01', '2035-01-31', 'periodo')
  WHERE nivel = 'campanha' AND metrica = 'alcance'
  $$,
  $$ VALUES (1600::numeric, '2035-01-31'::date, NULL::text) $$,
  'ADR-0016: entre o mês, extraído até 20/01, e o ano, até 31/01, vale o extraído até mais tarde'
);

-- §3.3: semana ISO, mês ou ano que começa antes do limite de 37 meses →
-- "Não disponível". A linha extraída quando o período ainda estava dentro
-- do limite continua valendo (ADR-0016).
SELECT results_eq(
  $$
  SELECT DISTINCT inicio_periodo, fim_periodo, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2023-01-01', '2023-12-31', 'ano')
  $$,
  $$ VALUES ('2023-01-01'::date, '2023-12-31'::date, NULL::numeric, NULL::date, 'limite_historico') $$,
  '§3.3: o ano que começa antes do limite de 37 meses não está disponível'
);
SELECT results_eq(
  $$
  SELECT DISTINCT inicio_periodo, fim_periodo, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2023-01-01', '2023-01-31', 'mes')
  $$,
  $$ VALUES ('2023-01-01'::date, '2023-01-31'::date, NULL::numeric, NULL::date, 'limite_historico') $$,
  '§3.3: o mês que começa antes do limite de 37 meses não está disponível'
);
SELECT results_eq(
  $$
  SELECT valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2023-01-02', '2023-01-08', 'periodo')
  WHERE nivel = 'conta' AND metrica = 'alcance'
  $$,
  $$ VALUES (90::numeric, '2023-01-08'::date, NULL::text) $$,
  'ADR-0016: a semana extraída antes de sair do limite continua com o valor'
);

-- §3.3: período livre → "Não disponível", salvo quando coincide exatamente
-- com uma semana ISO, um mês ou um ano (os casos acima).
SELECT results_eq(
  $$
  SELECT DISTINCT nivel, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2035-01-03', '2035-01-20', 'periodo')
  ORDER BY nivel DESC
  $$,
  $$
  VALUES
    ('conta', NULL::numeric, NULL::date, 'periodo_livre'),
    ('campanha', NULL, NULL, 'periodo_livre')
  $$,
  '§3.3: o intervalo livre não está disponível, na conta e nas campanhas'
);
SELECT results_eq(
  $$
  SELECT DISTINCT inicio_periodo, valor, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2035-01-01', '2035-01-03', 'dia')
  WHERE nivel = 'conta'
  ORDER BY inicio_periodo
  $$,
  $$
  VALUES
    ('2035-01-01'::date, NULL::numeric, 'periodo_livre'),
    ('2035-01-02', NULL, 'periodo_livre'),
    ('2035-01-03', NULL, 'periodo_livre')
  $$,
  '§3.3: o dia é período livre quando a semana, o mês e o ano que ele abre foram extraídos além dele'
);
SELECT results_eq(
  $$
  SELECT inicio_periodo, metrica, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2035-03-04', '2035-03-06', 'dia')
  WHERE nivel = 'conta'
  ORDER BY inicio_periodo, metrica
  $$,
  $$
  VALUES
    ('2035-03-04'::date, 'alcance', NULL::numeric, NULL::date, 'periodo_livre'),
    ('2035-03-04', 'custo_mil_alcance', NULL, NULL, 'periodo_livre'),
    ('2035-03-04', 'frequencia', NULL, NULL, 'periodo_livre'),
    ('2035-03-05', 'alcance', 250, '2035-03-05', NULL),
    ('2035-03-05', 'custo_mil_alcance', 12, '2035-03-05', NULL),
    ('2035-03-05', 'frequencia', 1.2, '2035-03-05', NULL),
    ('2035-03-06', 'alcance', NULL, NULL, 'periodo_livre'),
    ('2035-03-06', 'custo_mil_alcance', NULL, NULL, 'periodo_livre'),
    ('2035-03-06', 'frequencia', NULL, NULL, 'periodo_livre')
  $$,
  'ADR-0016: o dia que abre a semana extraída só até ele tem o alcance dela, como "ontem" na terça-feira'
);
SELECT set_eq(
  $$
  SELECT DISTINCT e.id_meta, r.inicio_periodo
  FROM resultado AS r
  JOIN entidade_teste AS e ON e.id = r.entidade_id
  WHERE r.granularidade = 'dia' AND r.motivo IS NULL
  $$,
  $$ VALUES ('411111111111111', '2035-03-05'::date) $$,
  '§3.3: na série diária, só o dia que é uma linha extraída inteira tem alcance'
);

-- §3.3: na visão Geral de empresa com mais de uma conta cadastrada →
-- "Não disponível", em cada moeda; as contas mostram o próprio alcance.
SELECT results_eq(
  $$
  SELECT nivel, id_meta, moeda, metrica, valor, motivo
  FROM pg_temp.alcance_a('geral', NULL, '2035-01-01', '2035-01-31', 'periodo')
  WHERE metrica = 'alcance'
  ORDER BY nivel DESC, moeda
  $$,
  $$
  VALUES
    ('geral', NULL, 'BRL', 'alcance', NULL::numeric, 'varias_contas'),
    ('geral', NULL, 'USD', 'alcance', NULL, 'varias_contas'),
    ('conta', '411111111111111', 'BRL', 'alcance', 2000, NULL),
    ('conta', '411111111111112', 'USD', 'alcance', 150, NULL)
  $$,
  '§3.3: o Geral de empresa com duas contas não tem alcance, e cada conta tem o seu'
);
SELECT is_empty(
  $$ SELECT * FROM resultado WHERE nivel = 'geral' AND motivo IS DISTINCT FROM 'varias_contas' $$,
  '§3.3: nenhum período do Geral de empresa com duas contas tem alcance'
);
SELECT results_eq(
  $$
  SELECT nivel, metrica, valor, fim_apurado, motivo
  FROM pg_temp.alcance('empresa_b', 'Empresa Teste B', 'geral', NULL, '2035-01-01', '2035-01-31', 'periodo')
  ORDER BY nivel DESC, metrica
  $$,
  $$
  VALUES
    ('geral', 'alcance', 4000::numeric, '2035-01-31'::date, NULL::text),
    ('geral', 'custo_mil_alcance', 12.5, '2035-01-31', NULL),
    ('geral', 'frequencia', 1.5, '2035-01-31', NULL),
    ('conta', 'alcance', 4000, '2035-01-31', NULL),
    ('conta', 'custo_mil_alcance', 12.5, '2035-01-31', NULL),
    ('conta', 'frequencia', 1.5, '2035-01-31', NULL)
  $$,
  'ADR-0016: o Geral de empresa com uma conta mostra o alcance dela'
);
-- Uma segunda conta, inativa e ainda sem extração, basta para tirar o
-- alcance do Geral.
INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, situacao, execucao_id)
SELECT x.empresa_id, '422222222222222', 'inativa', x.id
FROM normalizado.execucao_carga AS x
JOIN normalizado.empresa AS e ON e.id = x.empresa_id AND e.nome = 'Empresa Teste B';
SELECT results_eq(
  $$
  SELECT nivel, valor, motivo
  FROM pg_temp.alcance('empresa_b', 'Empresa Teste B', 'geral', NULL, '2035-01-01', '2035-01-31', 'periodo')
  WHERE metrica = 'alcance'
  ORDER BY nivel DESC
  $$,
  $$ VALUES ('geral', NULL::numeric, 'varias_contas'), ('conta', 4000, NULL) $$,
  'ADR-0016: no Geral, conta também a conta cadastrada inativa e sem dados'
);

-- ADR-0016: a semana, o mês ou o ano inteiro sem linha de alcance, depois
-- do limite.
SELECT results_eq(
  $$
  SELECT nivel, id_meta, metrica, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2035-03-01', '2035-03-31', 'periodo')
  WHERE metrica = 'alcance'
  ORDER BY nivel DESC
  $$,
  $$
  VALUES
    ('conta', '411111111111111', 'alcance', NULL::numeric, NULL::date, 'nao_extraido'),
    ('campanha', '420000000000000002', 'alcance', NULL, NULL, 'nao_extraido')
  $$,
  'ADR-0016: o mês com entrega e sem alcance extraído ainda não está disponível'
);
SELECT results_eq(
  $$
  SELECT id_meta, valor, motivo
  FROM pg_temp.alcance_a('conta', '411111111111111', '2035-01-08', '2035-01-14', 'periodo')
  WHERE nivel = 'campanha' AND metrica = 'alcance'
  ORDER BY id_meta
  $$,
  $$ VALUES ('420000000000000001', NULL::numeric, 'nao_extraido'), ('420000000000000002', 640, NULL) $$,
  'ADR-0016: a campanha com entrega na semana e sem alcance extraído dela ainda não está disponível'
);
SELECT results_eq(
  $$
  SELECT inicio_periodo, fim_periodo, metrica, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a('campanha', '420000000000000002', '2035-01-01', '2035-01-14', 'semana')
  WHERE nivel = 'campanha'
  ORDER BY inicio_periodo, metrica
  $$,
  $$
  VALUES
    ('2035-01-01'::date, '2035-01-07'::date, 'alcance', 0::numeric, '2035-01-07'::date, NULL::text),
    ('2035-01-01', '2035-01-07', 'custo_mil_alcance', NULL, '2035-01-07', NULL),
    ('2035-01-01', '2035-01-07', 'frequencia', NULL, '2035-01-07', NULL),
    ('2035-01-08', '2035-01-14', 'alcance', 640, '2035-01-14', NULL),
    ('2035-01-08', '2035-01-14', 'custo_mil_alcance', 12.5, '2035-01-14', NULL),
    ('2035-01-08', '2035-01-14', 'frequencia', 1.5625, '2035-01-14', NULL)
  $$,
  'ADR-0016: a semana sem entrega tem alcance zero, e a frequência e o custo ficam sem valor'
);
-- O período em andamento desde o primeiro dia até hoje, sem linha
-- extraída, segue a mesma regra, como "este mês" no dia 1, antes da rotina
-- diária, ou depois de uma extração que falhou. Hoje vem do relógio, no fuso
-- da conta em USD, e a entrega de hoje, da carga horária (ADR-0005).
CREATE TEMPORARY TABLE hoje_teste AS
SELECT calendario.data AS hoje, calendario.inicio_mes
FROM normalizado.calendario AS calendario
WHERE calendario.data = (now() AT TIME ZONE 'America/New_York')::date;
INSERT INTO normalizado.metrica_diaria_anuncio (empresa_id, anuncio_id, data, investimento, impressoes, alcance, execucao_id)
SELECT a.empresa_id, a.id, hoje_teste.hoje, 1.00, 100, 100, a.execucao_id
FROM normalizado.anuncio AS a
CROSS JOIN hoje_teste
WHERE a.id_meta = '450000000000000004';
SELECT results_eq(
  $$
  SELECT nivel, valor, fim_apurado, motivo
  FROM pg_temp.alcance_a(
    'conta', '411111111111112', (SELECT inicio_mes FROM hoje_teste), (SELECT hoje FROM hoje_teste), 'periodo'
  )
  WHERE metrica = 'alcance'
  ORDER BY nivel DESC
  $$,
  $$ VALUES ('conta', NULL::numeric, NULL::date, 'nao_extraido'), ('campanha', NULL, NULL, 'nao_extraido') $$,
  'ADR-0016: "este mês" com entrega e sem linha extraída ainda não foi extraído'
);

-- Como na obter_desempenho, o intervalo sem nenhum dado devolve zero linhas,
-- e a entidade em foco tem todo período do intervalo, para que as duas
-- leituras tenham as mesmas entidades, períodos e moedas.
SELECT is_empty(
  $$ SELECT * FROM pg_temp.alcance_a('conta', '411111111111111', '2035-06-01', '2035-06-30', 'periodo') $$,
  'o intervalo sem entrega da entidade não devolve linhas'
);
SELECT set_eq(
  $$
  SELECT nivel, entidade_id, inicio_periodo, fim_periodo, moeda
  FROM pg_temp.alcance('empresa_a', 'Empresa Teste A', 'conta', '411111111111111', '2035-01-01', '2035-03-31', 'semana')
  $$,
  $$
  SELECT nivel, entidade_id, inicio_periodo, fim_periodo, moeda
  FROM analitico.obter_desempenho(
    (SELECT token FROM credencial_teste WHERE caso = 'empresa_a'),
    (SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Teste A'),
    'conta', (SELECT id FROM entidade_teste WHERE id_meta = '411111111111111'),
    '2035-01-01', '2035-03-31', 'semana'
  )
  $$,
  'as entidades, os períodos e as moedas são os mesmos da obter_desempenho'
);

-- Com valor, toda linha tem o fim apurado e nenhum motivo; sem valor por
-- indisponibilidade, só o motivo, que é um dos quatro do ADR-0016.
SELECT is_empty(
  $$
  SELECT * FROM resultado
  WHERE (motivo IS NULL) <> (fim_apurado IS NOT NULL)
     OR (motivo IS NOT NULL AND valor IS NOT NULL)
     OR fim_apurado NOT BETWEEN inicio_periodo AND fim_periodo
  $$,
  'o fim apurado fica dentro do período e só existe sem motivo'
);
SELECT is_empty(
  $$
  SELECT * FROM resultado
  WHERE motivo NOT IN ('periodo_livre', 'limite_historico', 'varias_contas', 'nao_extraido')
  $$,
  'o motivo é um dos quatro do ADR-0016'
);
SELECT is_empty(
  $$
  SELECT metrica
  FROM pg_temp.alcance_a('conta', '411111111111111', '2035-01-01', '2035-01-31', 'periodo')
  WHERE valor IS NULL
  $$,
  'no mês extraído, nenhuma métrica fica sem valor'
);

SELECT * FROM finish();
ROLLBACK;
