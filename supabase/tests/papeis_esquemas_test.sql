-- Prova os esquemas, os papéis próprios e o acesso de cada papel aos esquemas
-- (ADR-0009 §3). Os privilégios por tabela e por função são provados em
-- privilegios_tabelas_test.sql e privilegios_funcoes_test.sql.
BEGIN;
SELECT plan(15);

SELECT schema_owner_is('bruto', 'postgres', 'bruto existe e é do postgres');
SELECT schema_owner_is('normalizado', 'postgres', 'normalizado existe e é do postgres');
SELECT schema_owner_is('analitico', 'postgres', 'analitico existe e é do postgres');

-- Sem bypassrls, o RLS vale para os dois papéis (R-30). Com replication, um
-- slot lógico leria as mudanças de toda tabela sem passar pelo RLS.
SELECT results_eq(
  $$
  SELECT rolname, rolcanlogin, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls,
         rolreplication
  FROM pg_catalog.pg_roles
  WHERE rolname IN ('etl_carga', 'painel_leitor')
  ORDER BY rolname
  $$,
  $$
  VALUES ('etl_carga'::name, true, false, false, false, false, false),
         ('painel_leitor', true, false, false, false, false, false)
  $$,
  'etl_carga e painel_leitor conectam e não têm atributos privilegiados'
);

SELECT is_empty(
  $$
  SELECT m.rolname, r.rolname
  FROM pg_catalog.pg_auth_members AS am
  JOIN pg_catalog.pg_roles AS m ON m.oid = am.member
  JOIN pg_catalog.pg_roles AS r ON r.oid = am.roleid
  WHERE m.rolname IN ('etl_carga', 'painel_leitor')
  $$,
  'etl_carga e painel_leitor não são membros de nenhum papel'
);

-- has_*_privilege só enxerga herança: um membro com SET ROLE escaparia dos
-- testes de tabela e de função.
SELECT is_empty(
  $$
  SELECT m.rolname, r.rolname
  FROM pg_catalog.pg_auth_members AS am
  JOIN pg_catalog.pg_roles AS m ON m.oid = am.member
  JOIN pg_catalog.pg_roles AS r ON r.oid = am.roleid
  WHERE r.rolname IN ('etl_carga', 'painel_leitor')
    AND m.rolname <> 'postgres'
  $$,
  'só o postgres é membro de etl_carga e de painel_leitor'
);

-- O postgres troca de papel nos testes, mas não herda nada deles (R-34).
SELECT ok(
  pg_catalog.pg_has_role('postgres', 'etl_carga', 'SET')
    AND pg_catalog.pg_has_role('postgres', 'painel_leitor', 'SET'),
  'postgres pode fazer SET ROLE para etl_carga e painel_leitor'
);
SELECT ok(
  NOT pg_catalog.pg_has_role('postgres', 'etl_carga', 'USAGE')
    AND NOT pg_catalog.pg_has_role('postgres', 'painel_leitor', 'USAGE'),
  'postgres não herda os privilégios de etl_carga nem de painel_leitor'
);

SELECT ok(
  has_schema_privilege('etl_carga', 'bruto', 'USAGE')
    AND has_schema_privilege('etl_carga', 'normalizado', 'USAGE'),
  'etl_carga tem USAGE em bruto e normalizado'
);
SELECT ok(
  NOT has_schema_privilege('etl_carga', 'analitico', 'USAGE'),
  'etl_carga não tem USAGE em analitico'
);
SELECT ok(
  has_schema_privilege('painel_leitor', 'analitico', 'USAGE'),
  'painel_leitor tem USAGE em analitico'
);
SELECT ok(
  NOT has_schema_privilege('painel_leitor', 'bruto', 'USAGE')
    AND NOT has_schema_privilege('painel_leitor', 'normalizado', 'USAGE'),
  'painel_leitor não tem USAGE em bruto nem em normalizado'
);

-- Os esquemas ficam fora da Data API e não recebem grant para os papéis dela
-- (R-29).
SELECT is_empty(
  $$
  SELECT papel, esquema
  FROM unnest(ARRAY['anon', 'authenticated', 'service_role']) AS papel
  CROSS JOIN unnest(ARRAY['bruto', 'normalizado', 'analitico']) AS esquema
  WHERE has_schema_privilege(papel, esquema, 'USAGE')
  $$,
  'anon, authenticated e service_role não têm USAGE em nenhum dos três esquemas'
);

SELECT is_empty(
  $$
  SELECT papel, esquema
  FROM unnest(ARRAY['etl_carga', 'painel_leitor']) AS papel
  CROSS JOIN unnest(ARRAY['bruto', 'normalizado', 'analitico']) AS esquema
  WHERE has_schema_privilege(papel, esquema, 'CREATE')
  $$,
  'etl_carga e painel_leitor não criam objetos nos três esquemas'
);

-- Com o pg_net instalado, os papéis próprios leriam a fila de requisições
-- pelo que PUBLIC recebe (R-30). A consulta passa também quando o esquema
-- net não existe.
SELECT is_empty(
  $$
  SELECT papel
  FROM pg_catalog.pg_namespace AS n
  CROSS JOIN unnest(ARRAY['etl_carga', 'painel_leitor']) AS papel
  WHERE n.nspname = 'net'
    AND has_schema_privilege(papel, n.oid, 'USAGE')
  $$,
  'etl_carga e painel_leitor não têm USAGE no esquema net'
);

SELECT * FROM finish();
ROLLBACK;
