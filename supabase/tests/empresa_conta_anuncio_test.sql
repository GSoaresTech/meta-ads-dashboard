-- Prova as tabelas de empresas e contas de anúncio, a base do multiempresa
-- (ADR-0002; ADR-0009 §2 e §3).
BEGIN;
SELECT plan(39);

SELECT col_is_pk('normalizado', 'empresa', 'id', 'id é a PK de empresa');
SELECT col_type_is('normalizado', 'empresa', 'id', 'uuid', 'id de empresa é uuid');
SELECT col_default_is('normalizado', 'empresa', 'id', 'gen_random_uuid()', 'id de empresa vem de gen_random_uuid()');
SELECT col_is_pk('normalizado', 'conta_anuncio', 'id', 'id é a PK de conta_anuncio');
SELECT col_default_is('normalizado', 'conta_anuncio', 'id', 'gen_random_uuid()', 'id de conta_anuncio vem de gen_random_uuid()');
SELECT col_type_is('normalizado', 'conta_anuncio', 'id_meta', 'text', 'id_meta é text, nunca número (CLAUDE.md §5)');
SELECT col_is_unique('normalizado', 'conta_anuncio', ARRAY['empresa_id', 'id'], 'conta_anuncio tem UNIQUE (empresa_id, id), alvo das FKs compostas');
SELECT fk_ok('normalizado', 'conta_anuncio', 'empresa_id', 'normalizado', 'empresa', 'id', 'conta_anuncio.empresa_id referencia empresa');

-- Empresa
SELECT lives_ok(
  $$INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A'), ('Empresa Teste B')$$,
  'empresa com nome é aceita, ativa por padrão'
);
SELECT is(
  (SELECT situacao FROM normalizado.empresa WHERE nome = 'Empresa Teste A'),
  'ativa',
  'empresa nasce ativa'
);
SELECT throws_ok(
  $$INSERT INTO normalizado.empresa (nome) VALUES (' Empresa Teste ')$$,
  '23514', NULL, 'nome de empresa não aparado é recusado'
);
SELECT throws_ok(
  $$INSERT INTO normalizado.empresa (nome) VALUES ('')$$,
  '23514', NULL, 'nome de empresa vazio é recusado'
);
SELECT throws_ok(
  $$INSERT INTO normalizado.empresa (nome, situacao) VALUES ('Empresa Teste C', 'suspensa')$$,
  '23514', NULL, 'situação de empresa fora do domínio é recusada'
);
SELECT throws_ok(
  $$INSERT INTO normalizado.empresa (nome, situacao) VALUES ('Empresa Teste C', NULL)$$,
  '23502', NULL, 'empresa sem situação é recusada'
);

-- Conta de anúncio: o cadastro informa só o ID (RF-43); nome, fuso e moeda
-- chegam com a primeira extração.
SELECT lives_ok(
  $$
  INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)
  SELECT id, '111111111111111' FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
  $$,
  'conta só com empresa e id_meta é aceita'
);
SELECT lives_ok(
  $$
  INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, nome, fuso_horario, moeda)
  SELECT id, '222222222222222222', 'Conta Teste', 'America/Sao_Paulo', 'BRL'
  FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
  $$,
  'conta com nome, fuso IANA e moeda ISO 4217 é aceita'
);

SELECT throws_ok(
  $$
  INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)
  SELECT id, '111111111111111' FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
  $$,
  '23505', NULL, 'id_meta duplicado na mesma empresa é recusado'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)
  SELECT id, '111111111111111' FROM normalizado.empresa WHERE nome = 'Empresa Teste B'
  $$,
  '23505', NULL, 'id_meta duplicado em outra empresa é recusado'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)
  SELECT id, 'act_333333333333333' FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
  $$,
  '23514', NULL, 'id_meta não numérico, como o id com act_, é recusado'
);
SELECT throws_ok(
  $$INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta) VALUES (gen_random_uuid(), '333333333333333')$$,
  '23503', NULL, 'conta de empresa inexistente é recusada'
);

-- Moeda: três letras maiúsculas, o formato da ISO 4217.
SELECT throws_ok(
  format(
    $$
    INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, fuso_horario, moeda)
    SELECT id, '333333333333333', 'America/Sao_Paulo', %L
    FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
    $$,
    moeda
  ),
  '23514', NULL, format('moeda inválida %L é recusada', moeda)
)
FROM unnest(ARRAY['brl', 'BR', 'BRLX', 'R$', 'BR1']) AS moeda;

-- Fuso: o formato pelo CHECK e a existência na base IANA pelo trigger. O
-- trigger BEFORE roda antes dos CHECKs e também recusaria um nome malformado,
-- então o teste do formato desliga o trigger para provar o CHECK sozinho, e
-- os do trigger conferem a mensagem dele.
ALTER TABLE normalizado.conta_anuncio DISABLE TRIGGER conta_anuncio_valida_fuso_horario;
SELECT throws_ok(
  $$
  INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, fuso_horario, moeda)
  SELECT id, '333333333333333', 'America/Sao Paulo', 'BRL'
  FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
  $$,
  '23514',
  'new row for relation "conta_anuncio" violates check constraint "conta_anuncio_fuso_horario_check"',
  'fuso malformado é recusado pelo CHECK de formato'
);
ALTER TABLE normalizado.conta_anuncio ENABLE TRIGGER conta_anuncio_valida_fuso_horario;
SELECT throws_ok(
  $$
  INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, fuso_horario, moeda)
  SELECT id, '333333333333333', 'America/Atlantida', 'BRL'
  FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
  $$,
  '23514', 'fuso horário fora da base IANA', 'fuso bem formado e fora da base IANA é recusado'
);
-- O AT TIME ZONE do Postgres aceita especificações POSIX, que não são IANA.
SELECT throws_ok(
  $$
  INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, fuso_horario, moeda)
  SELECT id, '333333333333333', 'XYZ+3', 'BRL'
  FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
  $$,
  '23514', 'fuso horário fora da base IANA', 'especificação POSIX de fuso é recusada'
);
SELECT throws_ok(
  $$
  UPDATE normalizado.conta_anuncio SET fuso_horario = 'America/Atlantida'
  WHERE id_meta = '222222222222222222'
  $$,
  '23514', 'fuso horário fora da base IANA', 'atualização para fuso fora da base IANA é recusada'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, fuso_horario)
  SELECT id, '333333333333333', 'America/Sao_Paulo'
  FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
  $$,
  '23514', NULL, 'fuso sem moeda é recusado'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, nome)
  SELECT id, '333333333333333', ''
  FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
  $$,
  '23514', NULL, 'nome de conta vazio é recusado'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, situacao)
  SELECT id, '333333333333333', 'encerrada'
  FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
  $$,
  '23514', NULL, 'situação de conta fora do domínio é recusada'
);

-- Privilégios da etl_carga (ADR-0009 §3): lê empresas e contas, e na conta
-- só atualiza o que vem da extração.
SELECT ok(
  has_table_privilege('etl_carga', 'normalizado.empresa', 'SELECT')
    AND NOT has_any_column_privilege('etl_carga', 'normalizado.empresa', 'INSERT, UPDATE, REFERENCES')
    AND NOT has_table_privilege('etl_carga', 'normalizado.empresa', 'DELETE, TRUNCATE, TRIGGER, MAINTAIN'),
  'etl_carga tem só SELECT em empresa'
);
SELECT ok(
  has_table_privilege('etl_carga', 'normalizado.conta_anuncio', 'SELECT')
    AND NOT has_any_column_privilege('etl_carga', 'normalizado.conta_anuncio', 'INSERT, REFERENCES')
    AND NOT has_table_privilege('etl_carga', 'normalizado.conta_anuncio', 'UPDATE, DELETE, TRUNCATE, TRIGGER, MAINTAIN'),
  'etl_carga lê conta_anuncio e não insere nem apaga'
);
SELECT is(
  ARRAY(
    SELECT a.attname::text
    FROM pg_catalog.pg_attribute AS a
    WHERE a.attrelid = 'normalizado.conta_anuncio'::regclass
      AND a.attnum > 0
      AND NOT a.attisdropped
      AND has_column_privilege('etl_carga', a.attrelid, a.attnum, 'UPDATE')
    ORDER BY a.attname
  ),
  ARRAY['atualizado_em', 'execucao_id', 'fuso_horario', 'moeda', 'nome'],
  'etl_carga atualiza só nome, fuso_horario, moeda, execucao_id e atualizado_em de conta_anuncio'
);
SELECT policies_are('normalizado', 'empresa', ARRAY['etl_carga_acessa'], 'empresa tem só a política da etl_carga');
SELECT policies_are('normalizado', 'conta_anuncio', ARRAY['etl_carga_acessa'], 'conta_anuncio tem só a política da etl_carga');

-- Como etl_carga, as funções do pgTAP não ficam acessíveis: o resultado é
-- guardado num parâmetro da transação e comparado depois de voltar ao
-- postgres. O trigger de fuso vale também para a etl_carga, que grava o fuso.
SET LOCAL ROLE etl_carga;
DO $$
BEGIN
  UPDATE normalizado.conta_anuncio
  SET fuso_horario = 'America/New_York', moeda = 'USD', nome = 'Conta Teste EUA'
  WHERE id_meta = '222222222222222222';
  PERFORM set_config('empresa_conta_test.valido', 'aceito', true);
EXCEPTION WHEN OTHERS THEN
  PERFORM set_config('empresa_conta_test.valido', SQLSTATE, true);
END
$$;
DO $$
BEGIN
  UPDATE normalizado.conta_anuncio
  SET fuso_horario = 'America/Atlantida'
  WHERE id_meta = '222222222222222222';
  PERFORM set_config('empresa_conta_test.invalido', 'aceito', true);
EXCEPTION WHEN OTHERS THEN
  PERFORM set_config('empresa_conta_test.invalido', SQLSTATE, true);
END
$$;
RESET ROLE;

-- Sem a política, o RLS esconderia a linha e o UPDATE terminaria sem erro e
-- sem efeito; por isso o resultado é conferido na própria linha.
SELECT results_eq(
  $$
  SELECT current_setting('empresa_conta_test.valido'), nome, fuso_horario, moeda
  FROM normalizado.conta_anuncio
  WHERE id_meta = '222222222222222222'
  $$,
  $$VALUES ('aceito', 'Conta Teste EUA', 'America/New_York', 'USD')$$,
  'etl_carga atualiza nome, fuso e moeda de uma conta'
);
SELECT is(
  current_setting('empresa_conta_test.invalido'),
  '23514',
  'etl_carga não grava fuso fora da base IANA'
);

SELECT * FROM finish();
ROLLBACK;
