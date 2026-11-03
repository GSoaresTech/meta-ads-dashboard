-- Prova a tabela de credenciais de acesso ao painel: links de empresa e
-- credencial do operador, guardados só pelo hash SHA-256 (ADR-0004; ADR-0009
-- §2; RNF-15).
BEGIN;
SELECT plan(20);

-- Um token como o do ADR-0004: 32 bytes aleatórios em base64url, gerado a
-- cada execução para que nenhum token fique escrito no repositório.
SELECT set_config(
  'credencial_test.token',
  rtrim(translate(encode(extensions.gen_random_bytes(32), 'base64'), '+/', '-_'), '='),
  true
);

INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A');

-- As colunas e os tipos ficam fixados: uma coluna nova em que o token caiba
-- precisa passar por este teste.
SELECT results_eq(
  $$
  SELECT a.attname::text COLLATE "default", format_type(a.atttypid, a.atttypmod), a.attnotnull
  FROM pg_catalog.pg_attribute AS a
  WHERE a.attrelid = 'normalizado.credencial_acesso'::regclass
    AND a.attnum > 0
    AND NOT a.attisdropped
  ORDER BY a.attnum
  $$,
  $$
  VALUES ('id', 'uuid', true),
         ('hash', 'bytea', true),
         ('escopo', 'text', true),
         ('empresa_id', 'uuid', false),
         ('criado_em', 'timestamp with time zone', true),
         ('revogado_em', 'timestamp with time zone', false)
  $$,
  'credencial_acesso tem só id, hash, escopo, empresa_id, criado_em e revogado_em'
);
SELECT col_is_pk('normalizado', 'credencial_acesso', 'id', 'id é a PK de credencial_acesso');
SELECT col_default_is('normalizado', 'credencial_acesso', 'id', 'gen_random_uuid()', 'id de credencial_acesso vem de gen_random_uuid()');
SELECT col_is_unique('normalizado', 'credencial_acesso', 'hash', 'hash é único');
SELECT fk_ok('normalizado', 'credencial_acesso', 'empresa_id', 'normalizado', 'empresa', 'id', 'credencial_acesso.empresa_id referencia empresa');

SELECT lives_ok(
  $$
  INSERT INTO normalizado.credencial_acesso (hash, escopo)
  VALUES (sha256(convert_to(current_setting('credencial_test.token'), 'UTF8')), 'operador')
  $$,
  'credencial de operador com o hash SHA-256 do token é aceita'
);
SELECT lives_ok(
  $$
  INSERT INTO normalizado.credencial_acesso (hash, escopo, empresa_id)
  SELECT sha256(convert_to('outro ' || current_setting('credencial_test.token'), 'UTF8')), 'empresa', id
  FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
  $$,
  'credencial de empresa com o hash SHA-256 do token é aceita'
);

-- Escopo
SELECT throws_ok(
  $$
  INSERT INTO normalizado.credencial_acesso (hash, escopo)
  VALUES (sha256(convert_to('sem escopo', 'UTF8')), NULL)
  $$,
  '23502', NULL, 'credencial sem escopo é recusada'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.credencial_acesso (hash, escopo)
  VALUES (sha256(convert_to('empresa sem id', 'UTF8')), 'empresa')
  $$,
  '23514', NULL, 'credencial de empresa sem empresa_id é recusada'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.credencial_acesso (hash, escopo, empresa_id)
  SELECT sha256(convert_to('operador com id', 'UTF8')), 'operador', id
  FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
  $$,
  '23514', NULL, 'credencial de operador com empresa_id é recusada'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.credencial_acesso (hash, escopo)
  VALUES (sha256(convert_to('escopo token', 'UTF8')), current_setting('credencial_test.token'))
  $$,
  '23514', NULL, 'escopo fora do domínio, como o próprio token, é recusado'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.credencial_acesso (hash, escopo, empresa_id)
  VALUES (sha256(convert_to('empresa inexistente', 'UTF8')), 'empresa', gen_random_uuid())
  $$,
  '23503', NULL, 'credencial de empresa inexistente é recusada'
);

-- Hash: exatamente os 32 bytes do SHA-256.
SELECT throws_ok(
  $$
  INSERT INTO normalizado.credencial_acesso (hash, escopo)
  VALUES (convert_to(current_setting('credencial_test.token'), 'UTF8'), 'operador')
  $$,
  '23514', NULL, 'o token em texto puro no lugar do hash é recusado'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.credencial_acesso (hash, escopo)
  VALUES (sha256(convert_to(current_setting('credencial_test.token'), 'UTF8')), 'operador')
  $$,
  '23505', NULL, 'hash duplicado é recusado'
);
SELECT throws_ok(
  $$INSERT INTO normalizado.credencial_acesso (hash, escopo) VALUES (NULL, 'operador')$$,
  '23502', NULL, 'credencial sem hash é recusada'
);

SELECT throws_ok(
  $$
  INSERT INTO normalizado.credencial_acesso (hash, escopo, criado_em, revogado_em)
  VALUES (sha256(convert_to('revogada antes', 'UTF8')), 'operador', '2026-11-03 12:00-03', '2026-11-03 11:59-03')
  $$,
  '23514', NULL, 'revogação anterior à criação é recusada'
);

-- RNF-15: nenhuma coluna guarda o token, nem como texto, nem como os bytes
-- do texto, nem como os 32 bytes aleatórios que ele codifica. Esses 32 bytes
-- cabem na coluna hash, e só o teste da função que gera a credencial prova
-- que ela grava o SHA-256 do token.
SELECT is_empty(
  $$
  SELECT c.id
  FROM normalizado.credencial_acesso AS c
  WHERE strpos(c::text, current_setting('credencial_test.token')) > 0
     OR strpos(c::text, encode(convert_to(current_setting('credencial_test.token'), 'UTF8'), 'hex')) > 0
     OR strpos(
          c::text,
          encode(
            decode(translate(current_setting('credencial_test.token'), '-_', '+/') || '=', 'base64'),
            'hex'
          )
        ) > 0
  $$,
  'nenhuma linha de credencial_acesso contém o token, em texto ou em bytes, nem os bytes que ele codifica'
);
SELECT is_empty(
  $$
  SELECT format('%I.%I.%I', n.nspname, c.relname, a.attname)
  FROM pg_catalog.pg_attribute AS a
  JOIN pg_catalog.pg_class AS c ON c.oid = a.attrelid
  JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
  WHERE n.nspname IN ('bruto', 'normalizado', 'analitico')
    AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
    AND a.attnum > 0
    AND NOT a.attisdropped
    AND a.attname ~* 'token'
  $$,
  'nenhuma tabela ou view dos três esquemas tem coluna de token'
);

-- Só as funções de analitico leem credenciais (ADR-0009 §3): nenhum papel
-- próprio tem privilégio na tabela, e não há política.
SELECT ok(
  NOT has_any_column_privilege('etl_carga', 'normalizado.credencial_acesso', 'SELECT, INSERT, UPDATE, REFERENCES')
    AND NOT has_table_privilege('etl_carga', 'normalizado.credencial_acesso', 'DELETE, TRUNCATE, TRIGGER, MAINTAIN'),
  'etl_carga não tem privilégio em credencial_acesso'
);
SELECT is_empty(
  $$
  SELECT policyname
  FROM pg_catalog.pg_policies
  WHERE schemaname = 'normalizado' AND tablename = 'credencial_acesso'
  $$,
  'credencial_acesso não tem política'
);

SELECT * FROM finish();
ROLLBACK;
