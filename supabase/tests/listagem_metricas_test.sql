-- Prova a leitura do catálogo de métricas pelo painel: os parâmetros, o acesso
-- e o conteúdo de que a tela precisa para rotular e formatar cada métrica e
-- avaliar a variação dela (RF-27; RF-30; RNF-14; ADR-0007; ADR-0009 §4).
BEGIN;
SELECT plan(14);

-- Atributos: o painel_leitor só executa, e a função roda com os privilégios
-- do postgres, com search_path vazio (ADR-0009 §3 e §4).
SELECT has_function(
  'analitico', 'listar_metricas', ARRAY['text'],
  'analitico.listar_metricas existe com a assinatura do ADR-0009 §4'
);
SELECT results_eq(
  $$
  SELECT p.provolatile = 's', p.prosecdef, p.proconfig::text = '{"search_path=\"\""}'
  FROM pg_catalog.pg_proc AS p
  WHERE p.oid = 'analitico.listar_metricas(text)'::regprocedure
  $$,
  $$ VALUES (true, true, true) $$,
  'a função é STABLE, SECURITY DEFINER e com search_path vazio'
);
SELECT is(
  pg_get_function_result('analitico.listar_metricas(text)'::regprocedure),
  'TABLE(codigo text, rotulo text, explicacao text, unidade text, sentido_melhora text)',
  'uma linha por métrica, com o rótulo, a explicação, a unidade e o sentido de melhora'
);
SELECT ok(
  has_function_privilege('painel_leitor', 'analitico.listar_metricas(text)', 'EXECUTE'),
  'painel_leitor executa analitico.listar_metricas'
);
SELECT ok(
  NOT has_function_privilege('etl_carga', 'analitico.listar_metricas(text)', 'EXECUTE'),
  'etl_carga não executa analitico.listar_metricas'
);

INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A'), ('Empresa Teste Inativa');

-- Credenciais geradas pela função do banco, a cada execução, para que nenhum
-- token fique no repositório. A da empresa inativa nasce antes da desativação.
CREATE TEMPORARY TABLE credencial_teste (caso text PRIMARY KEY, token text NOT NULL);
INSERT INTO credencial_teste (caso, token)
SELECT v.caso, normalizado.gerar_credencial(v.escopo, e.id)
FROM (
  VALUES
    ('empresa_a', 'empresa', 'Empresa Teste A'),
    ('empresa_a_revogada', 'empresa', 'Empresa Teste A'),
    ('empresa_inativa', 'empresa', 'Empresa Teste Inativa'),
    ('operador', 'operador', NULL)
) AS v (caso, escopo, empresa)
LEFT JOIN normalizado.empresa AS e ON e.nome = v.empresa;
UPDATE normalizado.empresa SET situacao = 'inativa' WHERE nome = 'Empresa Teste Inativa';
UPDATE normalizado.credencial_acesso
SET revogado_em = now()
WHERE hash = (SELECT sha256(convert_to(token, 'UTF8')) FROM credencial_teste WHERE caso = 'empresa_a_revogada');

CREATE FUNCTION pg_temp.metricas(p_caso text)
RETURNS TABLE (codigo text, rotulo text, explicacao text, unidade text, sentido_melhora text)
LANGUAGE sql STABLE AS $$
  SELECT * FROM analitico.listar_metricas((SELECT token FROM credencial_teste WHERE caso = p_caso))
$$;

-- O catálogo é global, sem empresa_id: toda credencial válida lê o mesmo
-- conteúdo, e a tela lê o que estiver na tabela.
SELECT set_eq(
  $$ SELECT * FROM pg_temp.metricas('empresa_a') $$,
  $$ SELECT codigo, rotulo, explicacao, unidade, sentido_melhora FROM normalizado.metrica $$,
  'a credencial da empresa lê todo o catálogo'
);
SELECT set_eq(
  $$ SELECT * FROM pg_temp.metricas('operador') $$,
  $$ SELECT codigo, rotulo, explicacao, unidade, sentido_melhora FROM normalizado.metrica $$,
  'a credencial do operador lê todo o catálogo'
);
SELECT results_eq(
  $$ SELECT rotulo, explicacao, unidade FROM pg_temp.metricas('empresa_a') WHERE codigo = 'investimento' $$,
  $$ VALUES ('Investimento', 'Quanto foi gasto em anúncios no período.', 'moeda') $$,
  'o investimento sai com o rótulo de negócio, a explicação e a unidade'
);
-- RF-27: a tela avalia a variação pelo sentido do catálogo.
SELECT results_eq(
  $$ SELECT codigo, sentido_melhora FROM pg_temp.metricas('empresa_a') WHERE codigo IN ('compras', 'custo_compra') ORDER BY codigo $$,
  $$ VALUES ('compras', 'alta'), ('custo_compra', 'queda') $$,
  'RF-27: o custo sai com a queda como melhora, e o resultado, com a alta'
);

-- A ordem é a do rótulo, a mesma em toda chamada, para que os cartões da tela
-- não mudem de lugar.
SELECT results_eq(
  $$ SELECT rotulo FROM pg_temp.metricas('empresa_a') $$,
  $$ SELECT rotulo FROM normalizado.metrica ORDER BY rotulo $$,
  'as métricas saem em ordem de rótulo'
);

-- RNF-14: sem acesso, zero linhas, sem erro (ADR-0009 §4). O catálogo não tem
-- dado de empresa, e a regra da credencial é a mesma das demais funções.
SELECT is_empty(
  format($$ SELECT * FROM analitico.listar_metricas(%L) $$, token),
  descricao
)
FROM (
  VALUES
    ('token que não é de nenhuma credencial', 'a credencial inexistente não devolve nada'),
    (NULL, 'a credencial nula não devolve nada')
) AS caso (token, descricao);
SELECT is_empty(
  format($$ SELECT * FROM pg_temp.metricas(%L) $$, caso),
  descricao
)
FROM (
  VALUES
    ('empresa_a_revogada', 'a credencial revogada não devolve nada'),
    ('empresa_inativa', 'a credencial de empresa inativa não devolve nada')
) AS caso (caso, descricao);

SELECT * FROM finish();
ROLLBACK;
