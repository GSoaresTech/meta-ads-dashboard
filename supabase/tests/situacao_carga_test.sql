-- Prova a leitura da situação da carga pelo painel: o instante da última
-- carga bem-sucedida da empresa e o isolamento entre empresas (RF-28; RNF-14;
-- ADR-0009 §4).
BEGIN;
SELECT plan(15);

-- Atributos: o painel_leitor só executa, e a função roda com os privilégios
-- do postgres, com search_path vazio (ADR-0009 §3 e §4).
SELECT has_function(
  'analitico', 'obter_situacao_carga', ARRAY['text', 'uuid'],
  'analitico.obter_situacao_carga existe com a assinatura do ADR-0009 §4'
);
SELECT results_eq(
  $$
  SELECT p.provolatile = 's', p.prosecdef, p.proconfig::text = '{"search_path=\"\""}'
  FROM pg_catalog.pg_proc AS p
  WHERE p.oid = 'analitico.obter_situacao_carga(text, uuid)'::regprocedure
  $$,
  $$ VALUES (true, true, true) $$,
  'a função é STABLE, SECURITY DEFINER e com search_path vazio'
);
SELECT is(
  pg_get_function_result('analitico.obter_situacao_carga(text, uuid)'::regprocedure),
  'TABLE(ultima_carga_em timestamp with time zone)',
  'uma linha com o instante da última carga bem-sucedida'
);
SELECT ok(
  has_function_privilege('painel_leitor', 'analitico.obter_situacao_carga(text, uuid)', 'EXECUTE'),
  'painel_leitor executa analitico.obter_situacao_carga'
);
SELECT ok(
  NOT has_function_privilege('etl_carga', 'analitico.obter_situacao_carga(text, uuid)', 'EXECUTE'),
  'etl_carga não executa analitico.obter_situacao_carga'
);

INSERT INTO normalizado.empresa (nome)
VALUES ('Empresa Teste A'), ('Empresa Teste B'), ('Empresa Teste Sem Carga'), ('Empresa Teste Inativa');

-- Na empresa A, a histórica começa antes da horária e termina depois dela: o
-- instante que vale é o do fim. Depois das duas, só há execuções que não
-- confirmaram dados. A empresa B tem uma carga bem-sucedida mais recente que
-- todas as da A.
INSERT INTO normalizado.execucao_carga (empresa_id, tipo, status, iniciado_em, terminado_em, erro)
SELECT e.id, v.tipo, v.status, v.iniciado_em::timestamptz, v.terminado_em::timestamptz, v.erro
FROM (
  VALUES
    ('Empresa Teste A', 'diaria', 'sucesso', '2026-11-13 06:43+00', '2026-11-13 06:55+00', NULL),
    ('Empresa Teste A', 'historica', 'sucesso', '2026-11-13 10:00+00', '2026-11-13 10:50+00', NULL),
    ('Empresa Teste A', 'horaria', 'sucesso', '2026-11-13 10:17+00', '2026-11-13 10:20+00', NULL),
    ('Empresa Teste A', 'horaria', 'falha', '2026-11-13 11:17+00', '2026-11-13 11:19+00', 'erro de teste'),
    ('Empresa Teste A', 'horaria', 'ignorada', '2026-11-13 12:17+00', '2026-11-13 12:32+00', NULL),
    ('Empresa Teste A', 'horaria', 'em_andamento', '2026-11-13 13:17+00', NULL, NULL),
    ('Empresa Teste B', 'horaria', 'sucesso', '2026-11-13 14:17+00', '2026-11-13 14:20+00', NULL),
    ('Empresa Teste Sem Carga', 'horaria', 'falha', '2026-11-13 10:17+00', '2026-11-13 10:18+00', 'erro de teste')
) AS v (empresa, tipo, status, iniciado_em, terminado_em, erro)
JOIN normalizado.empresa AS e ON e.nome = v.empresa;

-- Credenciais geradas pela função do banco, a cada execução, para que nenhum
-- token fique no repositório. A da empresa inativa nasce antes da desativação.
CREATE TEMPORARY TABLE credencial_teste (caso text PRIMARY KEY, token text NOT NULL);
INSERT INTO credencial_teste (caso, token)
SELECT v.caso, normalizado.gerar_credencial(v.escopo, e.id)
FROM (
  VALUES
    ('empresa_a', 'empresa', 'Empresa Teste A'),
    ('empresa_a_revogada', 'empresa', 'Empresa Teste A'),
    ('empresa_b', 'empresa', 'Empresa Teste B'),
    ('sem_carga', 'empresa', 'Empresa Teste Sem Carga'),
    ('empresa_inativa', 'empresa', 'Empresa Teste Inativa'),
    ('operador', 'operador', NULL)
) AS v (caso, escopo, empresa)
LEFT JOIN normalizado.empresa AS e ON e.nome = v.empresa;
UPDATE normalizado.empresa SET situacao = 'inativa' WHERE nome = 'Empresa Teste Inativa';
UPDATE normalizado.credencial_acesso
SET revogado_em = now()
WHERE hash = (SELECT sha256(convert_to(token, 'UTF8')) FROM credencial_teste WHERE caso = 'empresa_a_revogada');

CREATE FUNCTION pg_temp.situacao(p_caso text, p_empresa text)
RETURNS TABLE (ultima_carga_em timestamptz)
LANGUAGE sql STABLE AS $$
  SELECT * FROM analitico.obter_situacao_carga(
    (SELECT token FROM credencial_teste WHERE caso = p_caso),
    (SELECT id FROM normalizado.empresa WHERE nome = p_empresa)
  )
$$;

-- RF-28: o fim da última execução bem-sucedida, de qualquer tipo. A falha, a
-- ignorada e a em andamento, mais recentes, não confirmaram dados.
SELECT results_eq(
  $$ SELECT * FROM pg_temp.situacao('empresa_a', 'Empresa Teste A') $$,
  $$ VALUES ('2026-11-13 10:50+00'::timestamptz) $$,
  'a empresa lê o fim da última carga bem-sucedida, e não o início nem uma execução sem sucesso'
);
SELECT results_eq(
  $$ SELECT * FROM pg_temp.situacao('empresa_b', 'Empresa Teste B') $$,
  $$ VALUES ('2026-11-13 14:20+00'::timestamptz) $$,
  'cada empresa lê só as próprias execuções'
);
SELECT results_eq(
  $$ SELECT * FROM pg_temp.situacao('sem_carga', 'Empresa Teste Sem Carga') $$,
  $$ VALUES (NULL::timestamptz) $$,
  'a empresa sem carga bem-sucedida lê uma linha com o instante nulo'
);
SELECT results_eq(
  $$ SELECT * FROM pg_temp.situacao('operador', 'Empresa Teste A') $$,
  $$ VALUES ('2026-11-13 10:50+00'::timestamptz) $$,
  'o operador lê a situação de qualquer empresa'
);

-- RNF-14: sem acesso, zero linhas, sem erro (ADR-0009 §4).
SELECT is_empty(
  $$ SELECT * FROM pg_temp.situacao('empresa_a', 'Empresa Teste B') $$,
  'a credencial da empresa A não lê a situação da empresa B'
);
SELECT is_empty(
  $$ SELECT * FROM pg_temp.situacao('empresa_b', 'Empresa Teste A') $$,
  'a credencial da empresa B não lê a situação da empresa A'
);
SELECT is_empty(
  format(
    $$ SELECT * FROM analitico.obter_situacao_carga(%L, %L) $$,
    token,
    (SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Teste A')
  ),
  descricao
)
FROM (
  VALUES
    ('token que não é de nenhuma credencial', 'a credencial inexistente não devolve nada'),
    (NULL, 'a credencial nula não devolve nada')
) AS caso (token, descricao);
SELECT is_empty(
  format($$ SELECT * FROM pg_temp.situacao(%L, %L) $$, caso, empresa),
  descricao
)
FROM (
  VALUES
    ('empresa_a_revogada', 'Empresa Teste A', 'a credencial revogada não devolve nada'),
    ('empresa_inativa', 'Empresa Teste Inativa', 'a credencial de empresa inativa não devolve nada')
) AS caso (caso, empresa, descricao);

SELECT * FROM finish();
ROLLBACK;
