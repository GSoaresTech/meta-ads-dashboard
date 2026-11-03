-- Prova o acesso às tabelas dos três esquemas (ADR-0009 §3). As consultas
-- percorrem o catálogo, e não uma lista de tabelas, para valer também para
-- cada tabela que as migrations seguintes criarem.
BEGIN;
SELECT plan(5);

-- Tabelas, views, views materializadas e tabelas estrangeiras: tudo o que
-- devolve linhas num SELECT. Um privilégio de coluna também permite ler, por
-- isso has_any_column_privilege.
CREATE TEMPORARY VIEW relacao_dos_esquemas AS
SELECT c.oid, c.relkind, c.relowner, c.relrowsecurity
FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname IN ('bruto', 'normalizado', 'analitico')
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f');

SELECT is_empty(
  $$
  SELECT papel, r.oid::regclass
  FROM relacao_dos_esquemas AS r
  CROSS JOIN unnest(ARRAY['anon', 'authenticated', 'service_role']) AS papel
  WHERE has_any_column_privilege(papel, r.oid, 'SELECT, INSERT, UPDATE, REFERENCES')
     OR has_table_privilege(papel, r.oid, 'DELETE, TRUNCATE, TRIGGER, MAINTAIN')
  $$,
  'anon, authenticated e service_role não leem nem escrevem nenhuma tabela ou view'
);

-- O painel lê só por funções de analitico (ADR-0004).
SELECT is_empty(
  $$
  SELECT r.oid::regclass
  FROM relacao_dos_esquemas AS r
  WHERE has_any_column_privilege('painel_leitor', r.oid, 'SELECT, INSERT, UPDATE, REFERENCES')
     OR has_table_privilege('painel_leitor', r.oid, 'DELETE, TRUNCATE, TRIGGER, MAINTAIN')
  $$,
  'painel_leitor não tem SELECT nem outro privilégio em nenhuma tabela ou view'
);

SELECT is_empty(
  $$
  SELECT r.oid::regclass
  FROM relacao_dos_esquemas AS r
  WHERE r.relkind IN ('r', 'p')
    AND NOT r.relrowsecurity
  $$,
  'toda tabela de bruto, normalizado e analitico tem RLS habilitado'
);

-- Sem política, o RLS nega tudo a quem não é dono nem tem bypassrls. A única
-- política permitida libera a etl_carga, limitada pelos grants.
SELECT is_empty(
  $$
  SELECT format('%I.%I: %s', p.schemaname, p.tablename, p.policyname)
  FROM pg_catalog.pg_policies AS p
  WHERE p.schemaname IN ('bruto', 'normalizado', 'analitico')
    AND p.roles <> ARRAY['etl_carga']::name[]
  $$,
  'toda política dos três esquemas vale só para etl_carga'
);

-- Um dono diferente ignoraria o RLS e os grants que as migrations definem
-- (R-36).
SELECT is_empty(
  $$
  SELECT r.oid::regclass, r.relowner::regrole
  FROM relacao_dos_esquemas AS r
  WHERE r.relowner <> 'postgres'::regrole
  $$,
  'o dono de toda tabela e view dos três esquemas é o postgres'
);

SELECT * FROM finish();
ROLLBACK;
