-- Prova quem executa as funções dos três esquemas (ADR-0009 §3 e §4). Toda
-- função nasce executável por PUBLIC (R-31), então cada migration que cria
-- uma função precisa revogar esse padrão; estas consultas percorrem o
-- catálogo para pegar a função que esquecer.
BEGIN;
SELECT plan(4);

CREATE TEMPORARY VIEW funcao_dos_esquemas AS
SELECT p.oid, n.nspname AS esquema, p.proowner, p.proacl
FROM pg_catalog.pg_proc AS p
JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
WHERE n.nspname IN ('bruto', 'normalizado', 'analitico');

-- PUBLIC não é um papel, então has_function_privilege não o consulta: a ACL é
-- lida direto, com o padrão do Postgres quando ela é nula.
SELECT is_empty(
  $$
  SELECT f.oid::regprocedure
  FROM funcao_dos_esquemas AS f
  CROSS JOIN LATERAL aclexplode(coalesce(f.proacl, acldefault('f', f.proowner))) AS a
  WHERE a.grantee = 0
    AND a.privilege_type = 'EXECUTE'
  $$,
  'nenhuma função dos três esquemas é executável por PUBLIC'
);

SELECT is_empty(
  $$
  SELECT papel, f.oid::regprocedure
  FROM funcao_dos_esquemas AS f
  CROSS JOIN unnest(ARRAY['anon', 'authenticated', 'service_role']) AS papel
  WHERE has_function_privilege(papel, f.oid, 'EXECUTE')
  $$,
  'nenhuma função dos três esquemas é executável por anon, authenticated ou service_role'
);

SELECT is_empty(
  $$
  SELECT f.oid::regprocedure
  FROM funcao_dos_esquemas AS f
  WHERE f.esquema IN ('bruto', 'normalizado')
    AND has_function_privilege('painel_leitor', f.oid, 'EXECUTE')
  $$,
  'painel_leitor não executa nenhuma função de bruto nem de normalizado'
);

-- As funções SECURITY DEFINER rodam com os privilégios do dono (R-31), que
-- precisa ser o postgres (R-36).
SELECT is_empty(
  $$
  SELECT f.oid::regprocedure, f.proowner::regrole
  FROM funcao_dos_esquemas AS f
  WHERE f.proowner <> 'postgres'::regrole
  $$,
  'o dono de toda função dos três esquemas é o postgres'
);

SELECT * FROM finish();
ROLLBACK;
