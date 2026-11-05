-- Prova a resolução da credencial de acesso: o banco recebe o token, calcula
-- o hash SHA-256 e devolve só o escopo e a empresa de uma credencial não
-- revogada, de empresa ativa (ADR-0004; ADR-0009 §4; RF-45, RF-46, RF-48;
-- RNF-14).
BEGIN;
SELECT plan(14);

-- Atributos: a função interna roda com os privilégios de quem chama, e a de
-- analitico, com os do postgres, para que o painel_leitor resolva sem ler a
-- tabela (ADR-0009 §3 e §4).
SELECT has_function(
  'normalizado', 'resolver_credencial', ARRAY['text'],
  'normalizado.resolver_credencial(text) existe'
);
SELECT has_function(
  'analitico', 'resolver_acesso', ARRAY['text'],
  'analitico.resolver_acesso(text) existe'
);
SELECT results_eq(
  $$
  SELECT p.oid::regprocedure::text, p.provolatile = 's', p.prosecdef, p.proconfig::text = '{"search_path=\"\""}'
  FROM pg_catalog.pg_proc AS p
  WHERE p.oid IN ('normalizado.resolver_credencial(text)'::regprocedure, 'analitico.resolver_acesso(text)'::regprocedure)
  ORDER BY 1
  $$,
  $$
  VALUES ('analitico.resolver_acesso(text)', true, true, true),
         ('normalizado.resolver_credencial(text)', true, false, true)
  $$,
  'as duas são STABLE e com search_path vazio; só a de analitico é SECURITY DEFINER'
);
-- Nenhuma das duas devolve o hash nem o token.
SELECT results_eq(
  $$
  SELECT pg_get_function_result(p.oid)
  FROM pg_catalog.pg_proc AS p
  WHERE p.oid IN ('normalizado.resolver_credencial(text)'::regprocedure, 'analitico.resolver_acesso(text)'::regprocedure)
  $$,
  $$ VALUES ('TABLE(escopo text, empresa_id uuid)'), ('TABLE(escopo text, empresa_id uuid)') $$,
  'a resolução devolve só o escopo e a empresa'
);
SELECT ok(
  has_function_privilege('painel_leitor', 'analitico.resolver_acesso(text)', 'EXECUTE'),
  'painel_leitor executa analitico.resolver_acesso'
);
SELECT ok(
  NOT has_function_privilege('etl_carga', 'analitico.resolver_acesso(text)', 'EXECUTE')
    AND NOT has_function_privilege('etl_carga', 'normalizado.resolver_credencial(text)', 'EXECUTE'),
  'etl_carga não resolve credenciais'
);

-- Duas empresas ativas e uma inativa. Os tokens, no formato do ADR-0004,
-- são sorteados a cada execução, para que nenhum fique no repositório.
INSERT INTO normalizado.empresa (nome, situacao)
VALUES ('Empresa Teste A', 'ativa'), ('Empresa Teste B', 'ativa'), ('Empresa Teste Inativa', 'inativa');

CREATE TEMPORARY TABLE caso (
  caso text PRIMARY KEY,
  token text,
  escopo text,
  empresa text,
  revogada boolean NOT NULL DEFAULT false
);
INSERT INTO caso (caso, token, escopo, empresa, revogada)
SELECT v.caso, translate(encode(extensions.gen_random_bytes(32), 'base64'), '+/=', '-_'), v.escopo, v.empresa, v.revogada
FROM (
  VALUES
    ('empresa_a', 'empresa', 'Empresa Teste A', false),
    ('empresa_b', 'empresa', 'Empresa Teste B', false),
    ('operador', 'operador', NULL, false),
    ('empresa_a_revogada', 'empresa', 'Empresa Teste A', true),
    ('operador_revogado', 'operador', NULL, true),
    ('empresa_inativa', 'empresa', 'Empresa Teste Inativa', false),
    -- Um token no formato certo, sem credencial gravada.
    ('desconhecida', NULL, NULL, false)
) AS v (caso, escopo, empresa, revogada);

INSERT INTO normalizado.credencial_acesso (hash, escopo, empresa_id, revogado_em)
SELECT sha256(convert_to(c.token, 'UTF8')), c.escopo, e.id, CASE WHEN c.revogada THEN now() END
FROM caso AS c
LEFT JOIN normalizado.empresa AS e ON e.nome = c.empresa
WHERE c.escopo IS NOT NULL;

-- Entradas que não são um token: nula, vazia e o próprio hash da credencial
-- da empresa A, em hex e em base64. O painel nunca envia o hash, e o banco
-- sempre calcula o hash do que recebe.
INSERT INTO caso (caso, token)
SELECT 'nula', NULL
UNION ALL
SELECT 'vazia', ''
UNION ALL
SELECT 'hash_hex_a', encode(sha256(convert_to(token, 'UTF8')), 'hex') FROM caso WHERE caso = 'empresa_a'
UNION ALL
SELECT 'hash_base64_a', encode(sha256(convert_to(token, 'UTF8')), 'base64') FROM caso WHERE caso = 'empresa_a';

-- O painel_leitor resolve cada caso. Ele não tem as funções do pgTAP nem
-- SELECT nas tabelas; o resultado fica numa tabela temporária, conferida
-- depois de voltar ao postgres.
CREATE TEMPORARY TABLE resolvido (caso text NOT NULL, escopo text, empresa_id uuid);
GRANT SELECT ON caso TO painel_leitor;
GRANT INSERT ON resolvido TO painel_leitor;

SET LOCAL ROLE painel_leitor;
INSERT INTO resolvido (caso, escopo, empresa_id)
SELECT c.caso, r.escopo, r.empresa_id
FROM caso AS c
CROSS JOIN LATERAL analitico.resolver_acesso(c.token) AS r;
RESET ROLE;

SELECT results_eq(
  $$
  SELECT r.escopo, e.nome
  FROM resolvido AS r
  LEFT JOIN normalizado.empresa AS e ON e.id = r.empresa_id
  WHERE r.caso = 'empresa_a'
  $$,
  $$ VALUES ('empresa', 'Empresa Teste A') $$,
  'a credencial da empresa A resolve só para a empresa A'
);
SELECT is_empty(
  $$
  SELECT r.caso
  FROM resolvido AS r
  JOIN normalizado.empresa AS e ON e.id = r.empresa_id
  WHERE r.caso = 'empresa_a' AND e.nome = 'Empresa Teste B'
  $$,
  'a credencial da empresa A não resolve para a empresa B'
);
SELECT results_eq(
  $$
  SELECT r.escopo, e.nome
  FROM resolvido AS r
  LEFT JOIN normalizado.empresa AS e ON e.id = r.empresa_id
  WHERE r.caso = 'empresa_b'
  $$,
  $$ VALUES ('empresa', 'Empresa Teste B') $$,
  'a credencial da empresa B resolve só para a empresa B'
);
SELECT results_eq(
  $$ SELECT escopo, empresa_id FROM resolvido WHERE caso = 'operador' $$,
  $$ VALUES ('operador', NULL::uuid) $$,
  'a credencial do operador resolve para o escopo operador, sem empresa'
);
SELECT is_empty(
  $$ SELECT caso FROM resolvido WHERE caso IN ('empresa_a_revogada', 'operador_revogado') $$,
  'uma credencial revogada não resolve, de empresa ou de operador (RF-45)'
);
SELECT is_empty(
  $$ SELECT caso FROM resolvido WHERE caso = 'empresa_inativa' $$,
  'a credencial de empresa inativa não resolve (RF-48)'
);
SELECT is_empty(
  $$ SELECT caso FROM resolvido WHERE caso IN ('desconhecida', 'nula', 'vazia', 'hash_hex_a', 'hash_base64_a') $$,
  'token desconhecido, nulo, vazio ou o próprio hash não resolve'
);
-- Os casos acima, juntos, cobrem tudo o que foi resolvido.
SELECT is(
  (SELECT count(*) FROM resolvido),
  3::bigint,
  'só as três credenciais válidas resolvem, uma linha cada'
);

SELECT * FROM finish();
ROLLBACK;
