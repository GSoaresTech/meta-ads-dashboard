-- Prova o controle de execuções e a camada bruta: os domínios, a falha com
-- mensagem, a resposta bruta com data de referência e sem token, e as chaves
-- que impedem apontar para outra empresa (RF-07, RF-09, RF-20; ADR-0009 §1,
-- §2 e §3). Que o registro de início sobrevive ao rollback da carga exige
-- duas transações confirmadas em separado, o que um arquivo pgTAP, todo
-- dentro de uma transação, não consegue; essa prova está em
-- tests/test_controle_execucoes.py.
BEGIN;
SELECT plan(121);

-- Estrutura
SELECT col_is_pk('normalizado', 'execucao_carga', 'id', 'id é a PK de execucao_carga');
SELECT col_type_is('normalizado', 'execucao_carga', 'id', 'uuid', 'id de execucao_carga é uuid');
SELECT col_default_is('normalizado', 'execucao_carga', 'id', 'gen_random_uuid()', 'id de execucao_carga vem de gen_random_uuid()');
SELECT col_is_unique('normalizado', 'execucao_carga', ARRAY['empresa_id', 'id'], 'execucao_carga tem UNIQUE (empresa_id, id), alvo das FKs compostas');
SELECT col_default_is('normalizado', 'execucao_carga', 'iniciado_em', 'now()', 'iniciado_em vem de now()');
SELECT col_is_pk(
  'normalizado', 'contagem_linhas_execucao', ARRAY['empresa_id', 'execucao_id', 'tabela'],
  'contagem_linhas_execucao tem PK (empresa_id, execucao_id, tabela)'
);
SELECT col_is_pk(
  'normalizado', 'fatia_historica', ARRAY['empresa_id', 'conta_anuncio_id', 'mes_referencia'],
  'fatia_historica tem PK (empresa_id, conta_anuncio_id, mes_referencia)'
);
-- Alto volume e sem referência externa: bigint identity (ADR-0009 §1).
SELECT col_is_pk(esquema, tabela, 'id', format('id é a PK de %s', tabela))
FROM (VALUES ('normalizado', 'aviso_execucao'), ('bruto', 'resposta_api')) AS t (esquema, tabela);
SELECT col_type_is(esquema, tabela, 'id', 'bigint', format('id de %s é bigint', tabela))
FROM (VALUES ('normalizado', 'aviso_execucao'), ('bruto', 'resposta_api')) AS t (esquema, tabela);
SELECT is(
  (SELECT attidentity::text FROM pg_catalog.pg_attribute WHERE attrelid = format('%I.%I', esquema, tabela)::regclass AND attname = 'id'),
  'a',
  format('id de %s é GENERATED ALWAYS AS IDENTITY', tabela)
)
FROM (VALUES ('normalizado', 'aviso_execucao'), ('bruto', 'resposta_api')) AS t (esquema, tabela);

SELECT fk_ok(esquema, filha, ARRAY['empresa_id', coluna], 'normalizado', pai, ARRAY['empresa_id', 'id'], format('%s.%s tem FK composta para %s', filha, coluna, pai))
FROM (
  VALUES
    ('normalizado', 'contagem_linhas_execucao', 'execucao_id', 'execucao_carga'),
    ('normalizado', 'aviso_execucao', 'execucao_id', 'execucao_carga'),
    ('normalizado', 'aviso_execucao', 'campanha_id', 'campanha'),
    ('normalizado', 'fatia_historica', 'conta_anuncio_id', 'conta_anuncio'),
    ('normalizado', 'fatia_historica', 'execucao_id', 'execucao_carga'),
    ('bruto', 'resposta_api', 'execucao_id', 'execucao_carga'),
    ('bruto', 'resposta_api', 'conta_anuncio_id', 'conta_anuncio')
) AS fk (esquema, filha, coluna, pai);
SELECT fk_ok(esquema, tabela, 'empresa_id', 'normalizado', 'empresa', 'id', format('%s.empresa_id referencia empresa', tabela))
FROM (
  VALUES
    ('normalizado', 'execucao_carga'),
    ('normalizado', 'contagem_linhas_execucao'),
    ('normalizado', 'aviso_execucao'),
    ('normalizado', 'fatia_historica'),
    ('bruto', 'resposta_api')
) AS t (esquema, tabela);
-- As FKs são MATCH SIMPLE: um pai ou uma empresa nulos dispensariam a
-- conferência. Só a campanha do aviso é opcional. Em contagem e fatia, a PK
-- já exige empresa_id. Sem o início, o CHECK do fim deixaria de valer.
SELECT col_not_null(esquema, tabela, coluna, format('%s.%s é NOT NULL', tabela, coluna))
FROM (
  VALUES
    ('normalizado', 'execucao_carga', 'empresa_id'),
    ('normalizado', 'execucao_carga', 'iniciado_em'),
    ('normalizado', 'aviso_execucao', 'empresa_id'),
    ('normalizado', 'aviso_execucao', 'criado_em'),
    ('bruto', 'resposta_api', 'empresa_id'),
    ('bruto', 'resposta_api', 'recebido_em'),
    ('normalizado', 'contagem_linhas_execucao', 'execucao_id'),
    ('normalizado', 'aviso_execucao', 'execucao_id'),
    ('normalizado', 'fatia_historica', 'conta_anuncio_id'),
    ('normalizado', 'fatia_historica', 'execucao_id'),
    ('bruto', 'resposta_api', 'execucao_id'),
    ('bruto', 'resposta_api', 'conta_anuncio_id')
) AS t (esquema, tabela, coluna);
SELECT col_is_null('normalizado', 'aviso_execucao', 'campanha_id', 'aviso_execucao.campanha_id é opcional');

-- Área do operador (RF-51), carga parada (RNF-13) e retenção do bruto (RF-21).
SELECT has_index(
  'normalizado', 'execucao_carga', 'execucao_carga_empresa_id_iniciado_em_idx', ARRAY['empresa_id', 'iniciado_em'],
  'execucao_carga tem índice (empresa_id, iniciado_em)'
);
SELECT has_index(
  'bruto', 'resposta_api', 'resposta_api_data_referencia_idx', ARRAY['data_referencia'],
  'resposta_api tem índice (data_referencia), para a retenção'
);

-- Dados de teste: uma conta por empresa e, logo abaixo, uma execução de cada
-- empresa com id fixo, a da A terminando em a e a da B em b.
INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A'), ('Empresa Teste B');
INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)
SELECT id, CASE nome WHEN 'Empresa Teste A' THEN '111111111111111' ELSE '222222222222222' END
FROM normalizado.empresa
WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');

-- Execução
SELECT lives_ok(
  $$
  INSERT INTO normalizado.execucao_carga (id, empresa_id, tipo)
  SELECT e.id::uuid, p.id, 'diaria'
  FROM normalizado.empresa AS p
  JOIN (
    VALUES
      ('00000000-0000-4000-8000-00000000000a', 'Empresa Teste A'),
      ('00000000-0000-4000-8000-00000000000b', 'Empresa Teste B')
  ) AS e (id, nome) USING (nome)
  $$,
  'registro de início só com empresa e tipo é aceito'
);
SELECT results_eq(
  $$
  SELECT status, terminado_em IS NULL, erro IS NULL, iniciado_em = now()
  FROM normalizado.execucao_carga WHERE id = '00000000-0000-4000-8000-00000000000a'
  $$,
  $$VALUES ('em_andamento', true, true, true)$$,
  'a execução nasce em andamento, com início, sem fim e sem erro'
);
-- Uma campanha por empresa, gravada pela execução da própria empresa.
INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, objetivo, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, 'OUTCOME_SALES', 'ACTIVE', v.execucao_id::uuid
FROM normalizado.conta_anuncio AS c
JOIN (
  VALUES
    ('111111111111111', '120000000000000101', '00000000-0000-4000-8000-00000000000a'),
    ('222222222222222', '120000000000000102', '00000000-0000-4000-8000-00000000000b')
) AS v (conta, id_meta, execucao_id) ON v.conta = c.id_meta;
SELECT lives_ok(
  format(
    $$
    INSERT INTO normalizado.execucao_carga (empresa_id, tipo, status, terminado_em, erro)
    SELECT id, %L, %L, now(), %L FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
    $$,
    tipo, status, erro
  ),
  format('execução %s com status %s é aceita', tipo, status)
)
FROM (
  VALUES
    ('horaria', 'sucesso', NULL),
    ('diaria', 'ignorada', NULL),
    ('historica', 'falha', 'Erro de teste da API.')
) AS caso (tipo, status, erro);

-- Domínios fechados; NULL também é recusado, porque um CHECK avaliado como
-- NULL passa (ADR-0009 §1).
SELECT throws_ok(
  format(
    $$
    INSERT INTO normalizado.execucao_carga (empresa_id, tipo)
    SELECT id, %L FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
    $$,
    tipo
  ),
  '23514',
  'new row for relation "execucao_carga" violates check constraint "execucao_carga_tipo_check"',
  format('tipo %L fora do domínio é recusado', tipo)
)
FROM unnest(ARRAY['semanal', 'Diaria', 'histórica', '']) AS tipo;
SELECT throws_ok(
  $$
  INSERT INTO normalizado.execucao_carga (empresa_id, tipo)
  SELECT id, NULL FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
  $$,
  '23502', NULL, 'execução sem tipo é recusada'
);
SELECT throws_ok(
  format(
    $$
    UPDATE normalizado.execucao_carga SET status = %L, terminado_em = now(), erro = 'Erro de teste.'
    WHERE id = '00000000-0000-4000-8000-00000000000a'
    $$,
    status
  ),
  '23514',
  'new row for relation "execucao_carga" violates check constraint "execucao_carga_status_check"',
  format('status %L fora do domínio é recusado em execucao_carga', status)
)
FROM unnest(ARRAY['cancelada', 'SUCESSO', 'concluida', '']) AS status;
SELECT throws_ok(
  $$
  UPDATE normalizado.execucao_carga SET status = NULL WHERE id = '00000000-0000-4000-8000-00000000000a'
  $$,
  '23502', NULL, 'execução sem status é recusada'
);

-- Fim da execução
SELECT throws_ok(
  $$
  UPDATE normalizado.execucao_carga SET terminado_em = now() WHERE id = '00000000-0000-4000-8000-00000000000a'
  $$,
  '23514',
  'new row for relation "execucao_carga" violates check constraint "execucao_carga_terminado_em_check"',
  'execução em andamento com fim é recusada'
);
SELECT throws_ok(
  format(
    $$
    UPDATE normalizado.execucao_carga SET status = %L, erro = 'Erro de teste.'
    WHERE id = '00000000-0000-4000-8000-00000000000a'
    $$,
    status
  ),
  '23514',
  'new row for relation "execucao_carga" violates check constraint "execucao_carga_terminado_em_check"',
  format('execução %s sem fim é recusada', status)
)
FROM unnest(ARRAY['sucesso', 'falha', 'ignorada']) AS status;
SELECT throws_ok(
  $$
  UPDATE normalizado.execucao_carga SET status = 'sucesso', terminado_em = iniciado_em - interval '1 second'
  WHERE id = '00000000-0000-4000-8000-00000000000a'
  $$,
  '23514',
  'new row for relation "execucao_carga" violates check constraint "execucao_carga_terminado_em_iniciado_em_check"',
  'execução que termina antes de começar é recusada'
);

-- Toda falha tem mensagem de erro não vazia (RF-20).
SELECT throws_ok(
  $$
  UPDATE normalizado.execucao_carga SET status = 'falha', terminado_em = now()
  WHERE id = '00000000-0000-4000-8000-00000000000a'
  $$,
  '23514',
  'new row for relation "execucao_carga" violates check constraint "execucao_carga_falha_erro_check"',
  'falha sem mensagem de erro é recusada'
);
SELECT throws_ok(
  format(
    $$
    UPDATE normalizado.execucao_carga SET status = 'falha', terminado_em = now(), erro = %L
    WHERE id = '00000000-0000-4000-8000-00000000000a'
    $$,
    erro
  ),
  '23514',
  'new row for relation "execucao_carga" violates check constraint "execucao_carga_erro_check"',
  format('falha com mensagem de erro %L é recusada', erro)
)
FROM unnest(ARRAY['', ' ', ' Erro de teste.']) AS erro;
SELECT lives_ok(
  $$
  UPDATE normalizado.execucao_carga SET status = 'falha', terminado_em = now(), erro = 'Erro de teste da carga.'
  WHERE id = '00000000-0000-4000-8000-00000000000b'
  $$,
  'registro de fim de uma falha com mensagem é aceito'
);

-- Contagem de linhas
SELECT lives_ok(
  $$
  INSERT INTO normalizado.contagem_linhas_execucao (empresa_id, execucao_id, tabela, linhas)
  SELECT empresa_id, id, tabela, linhas
  FROM normalizado.execucao_carga,
    (VALUES ('campanha', 0), ('metrica_diaria_anuncio', 1500)) AS c (tabela, linhas)
  WHERE id = '00000000-0000-4000-8000-00000000000a'
  $$,
  'contagens de linhas da execução são aceitas, inclusive zero'
);
SELECT throws_ok(
  format(
    $$
    INSERT INTO normalizado.contagem_linhas_execucao (empresa_id, execucao_id, tabela, linhas)
    SELECT empresa_id, id, %L, %s FROM normalizado.execucao_carga WHERE id = '00000000-0000-4000-8000-00000000000a'
    $$,
    tabela, linhas
  ),
  erro, NULL, descricao
)
FROM (
  VALUES
    ('anuncio', '-1', '23514', 'contagem negativa é recusada'),
    ('anuncio', 'NULL', '23502', 'contagem sem linhas é recusada'),
    ('', '1', '23514', 'contagem com tabela vazia é recusada'),
    (' anuncio', '1', '23514', 'contagem com tabela não aparada é recusada'),
    ('campanha', '1', '23505', 'segunda contagem da mesma tabela na execução é recusada')
) AS caso (tabela, linhas, erro, descricao);

-- Avisos do RF-15 e do RF-16
SELECT lives_ok(
  $$
  INSERT INTO normalizado.aviso_execucao (empresa_id, execucao_id, tipo, campanha_id)
  SELECT x.empresa_id, x.id, a.tipo, c.id
  FROM normalizado.execucao_carga AS x
  JOIN normalizado.campanha AS c ON c.empresa_id = x.empresa_id,
    (VALUES ('objetivo_nao_classificado'), ('divergencia_resultado')) AS a (tipo)
  WHERE x.id = '00000000-0000-4000-8000-00000000000a'
  $$,
  'avisos dos dois tipos, com a campanha pelo id interno, são aceitos'
);
SELECT lives_ok(
  $$
  INSERT INTO normalizado.aviso_execucao (empresa_id, execucao_id, tipo)
  SELECT empresa_id, id, 'objetivo_nao_classificado'
  FROM normalizado.execucao_carga WHERE id = '00000000-0000-4000-8000-00000000000a'
  $$,
  'aviso sem campanha é aceito'
);
SELECT throws_ok(
  format(
    $$
    INSERT INTO normalizado.aviso_execucao (empresa_id, execucao_id, tipo)
    SELECT empresa_id, id, %L FROM normalizado.execucao_carga WHERE id = '00000000-0000-4000-8000-00000000000a'
    $$,
    tipo
  ),
  '23514',
  'new row for relation "aviso_execucao" violates check constraint "aviso_execucao_tipo_check"',
  format('tipo de aviso %L fora do domínio é recusado', tipo)
)
FROM unnest(ARRAY['objetivo_desconhecido', 'DIVERGENCIA_RESULTADO', '']) AS tipo;
SELECT throws_ok(
  $$
  INSERT INTO normalizado.aviso_execucao (empresa_id, execucao_id, tipo)
  SELECT empresa_id, id, NULL FROM normalizado.execucao_carga WHERE id = '00000000-0000-4000-8000-00000000000a'
  $$,
  '23502', NULL, 'aviso sem tipo é recusado'
);

-- Fatias da carga histórica (RF-07)
SELECT lives_ok(
  $$
  INSERT INTO normalizado.fatia_historica (empresa_id, conta_anuncio_id, mes_referencia, execucao_id)
  SELECT c.empresa_id, c.id, m.mes::date, '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.conta_anuncio AS c,
    (VALUES ('2025-01-01'), ('2025-02-01')) AS m (mes)
  WHERE c.id_meta = '111111111111111'
  $$,
  'fatias mensais da conta são aceitas'
);
SELECT is(
  ARRAY(SELECT DISTINCT status FROM normalizado.fatia_historica WHERE execucao_id = '00000000-0000-4000-8000-00000000000a'),
  ARRAY['pendente'],
  'a fatia nasce pendente'
);
SELECT lives_ok(
  format(
    $$
    UPDATE normalizado.fatia_historica SET status = %L
    WHERE mes_referencia = '2025-01-01'
    $$,
    status
  ),
  format('status %s é aceito em fatia_historica', status)
)
FROM unnest(ARRAY['falha', 'concluida']) AS status;
SELECT throws_ok(
  format(
    $$
    UPDATE normalizado.fatia_historica SET status = %L WHERE mes_referencia = '2025-02-01'
    $$,
    status
  ),
  '23514',
  'new row for relation "fatia_historica" violates check constraint "fatia_historica_status_check"',
  format('status %L fora do domínio é recusado em fatia_historica', status)
)
FROM unnest(ARRAY['concluída', 'em_andamento', 'PENDENTE', '']) AS status;
SELECT throws_ok(
  $$UPDATE normalizado.fatia_historica SET status = NULL WHERE mes_referencia = '2025-02-01'$$,
  '23502', NULL, 'fatia sem status é recusada'
);
SELECT throws_ok(
  format(
    $$
    INSERT INTO normalizado.fatia_historica (empresa_id, conta_anuncio_id, mes_referencia, execucao_id)
    SELECT empresa_id, id, %L, '00000000-0000-4000-8000-00000000000a'
    FROM normalizado.conta_anuncio WHERE id_meta = '111111111111111'
    $$,
    mes
  ),
  '23514',
  'new row for relation "fatia_historica" violates check constraint "fatia_historica_mes_referencia_check"',
  format('mês de referência %s, fora do dia 1, é recusado', mes)
)
FROM unnest(ARRAY['2025-03-02', '2025-03-31']) AS mes;
SELECT throws_ok(
  $$
  INSERT INTO normalizado.fatia_historica (empresa_id, conta_anuncio_id, mes_referencia, execucao_id)
  SELECT empresa_id, id, '2025-01-01', '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.conta_anuncio WHERE id_meta = '111111111111111'
  $$,
  '23505', NULL, 'segunda fatia do mesmo mês na conta é recusada'
);

-- Resposta bruta (RF-09)
SELECT lives_ok(
  $$
  INSERT INTO bruto.resposta_api (empresa_id, execucao_id, conta_anuncio_id, endpoint, parametros, data_referencia, resposta)
  SELECT c.empresa_id, '00000000-0000-4000-8000-00000000000a', c.id, 'act_111111111111111/insights',
    '{"level": "ad", "time_increment": 1, "time_range": {"since": "2025-01-01", "until": "2025-01-31"}}',
    '2025-01-31', '{"data": []}'
  FROM normalizado.conta_anuncio AS c WHERE c.id_meta = '111111111111111'
  $$,
  'resposta bruta com parâmetros sem token é aceita'
);
SELECT results_eq(
  $$SELECT recebido_em = now(), id IS NOT NULL FROM bruto.resposta_api WHERE execucao_id = '00000000-0000-4000-8000-00000000000a'$$,
  $$VALUES (true, true)$$,
  'a resposta bruta recebe id e instante de recebimento'
);
-- Uma inclusão por caso, com as expressões SQL do endpoint (%1$s), dos
-- parâmetros (%2$s), da data de referência (%3$s) e da resposta (%4$s). A
-- expressão omitida no caso fica com um valor válido.
CREATE TEMPORARY TABLE caso_resposta (
  endpoint text, parametros text, data_referencia text, resposta text,
  erro text NOT NULL, mensagem text NOT NULL, descricao text NOT NULL
);
INSERT INTO caso_resposta VALUES
  (NULL, NULL, 'NULL', NULL, '23502',
   'null value in column "data_referencia" of relation "resposta_api" violates not-null constraint',
   'resposta bruta sem data de referência é recusada'),
  ('NULL', NULL, NULL, NULL, '23502',
   'null value in column "endpoint" of relation "resposta_api" violates not-null constraint',
   'resposta bruta sem endpoint é recusada'),
  (NULL, 'NULL', NULL, NULL, '23502',
   'null value in column "parametros" of relation "resposta_api" violates not-null constraint',
   'resposta bruta sem parâmetros é recusada'),
  (NULL, NULL, NULL, 'NULL', '23502',
   'null value in column "resposta" of relation "resposta_api" violates not-null constraint',
   'resposta bruta sem resposta é recusada'),
  (NULL, $${"access_token": "token-ficticio"}$$, NULL, NULL, '23514',
   'new row for relation "resposta_api" violates check constraint "resposta_api_parametros_access_token_check"',
   'resposta bruta com access_token nos parâmetros é recusada'),
  (NULL, $${"fields": "id,name", "access_token": "token-ficticio", "limit": 500}$$, NULL, NULL, '23514',
   'new row for relation "resposta_api" violates check constraint "resposta_api_parametros_access_token_check"',
   'resposta bruta com access_token entre outros parâmetros é recusada'),
  (NULL, $$"access_token=token-ficticio"$$, NULL, NULL, '23514',
   'new row for relation "resposta_api" violates check constraint "resposta_api_parametros_objeto_check"',
   'parâmetros em texto, que escapariam da conferência do token, são recusados'),
  (NULL, $$["fields"]$$, NULL, NULL, '23514',
   'new row for relation "resposta_api" violates check constraint "resposta_api_parametros_objeto_check"',
   'parâmetros em lista são recusados'),
  (NULL, 'null', NULL, NULL, '23514',
   'new row for relation "resposta_api" violates check constraint "resposta_api_parametros_objeto_check"',
   'parâmetros null do JSON são recusados'),
  ($$''$$, NULL, NULL, NULL, '23514',
   'new row for relation "resposta_api" violates check constraint "resposta_api_endpoint_check"',
   'endpoint vazio é recusado'),
  ($$' act_111111111111111/ads'$$, NULL, NULL, NULL, '23514',
   'new row for relation "resposta_api" violates check constraint "resposta_api_endpoint_check"',
   'endpoint não aparado é recusado');
SELECT throws_ok(
  format(
    $$
    INSERT INTO bruto.resposta_api (empresa_id, execucao_id, conta_anuncio_id, endpoint, parametros, data_referencia, resposta)
    SELECT empresa_id, '00000000-0000-4000-8000-00000000000a', id, %1$s, %2$s, %3$s, %4$s
    FROM normalizado.conta_anuncio WHERE id_meta = '111111111111111'
    $$,
    coalesce(endpoint, $$'act_111111111111111/ads'$$),
    -- Os parâmetros do caso são JSON, não SQL; 'NULL' é o NULL do SQL.
    CASE parametros WHEN 'NULL' THEN 'NULL' ELSE quote_literal(coalesce(parametros, '{"fields": "id,name"}')) || '::jsonb' END,
    coalesce(data_referencia, $$'2025-01-31'$$),
    coalesce(resposta, $$'{"data": []}'$$)
  ),
  erro, mensagem, descricao
)
FROM caso_resposta;

-- Isolamento: uma linha da empresa A não aponta para a execução, a conta ou a
-- campanha da empresa B (ADR-0009 §1).
SELECT throws_ok(
  sql,
  '23503',
  format('insert or update on table "%s" violates foreign key constraint "%s"', tabela, restricao),
  descricao
)
FROM (
  VALUES
    ('contagem_linhas_execucao', 'contagem_linhas_execucao_execucao_carga_fkey', $$
      INSERT INTO normalizado.contagem_linhas_execucao (empresa_id, execucao_id, tabela, linhas)
      SELECT id, '00000000-0000-4000-8000-00000000000b', 'anuncio', 1
      FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
    $$, 'contagem da empresa A não aponta para execução da empresa B'),
    ('aviso_execucao', 'aviso_execucao_execucao_carga_fkey', $$
      INSERT INTO normalizado.aviso_execucao (empresa_id, execucao_id, tipo)
      SELECT id, '00000000-0000-4000-8000-00000000000b', 'divergencia_resultado'
      FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
    $$, 'aviso da empresa A não aponta para execução da empresa B'),
    ('aviso_execucao', 'aviso_execucao_campanha_fkey', $$
      INSERT INTO normalizado.aviso_execucao (empresa_id, execucao_id, tipo, campanha_id)
      SELECT x.empresa_id, x.id, 'divergencia_resultado', c.id
      FROM normalizado.execucao_carga AS x, normalizado.campanha AS c
      WHERE x.id = '00000000-0000-4000-8000-00000000000a' AND c.id_meta = '120000000000000102'
    $$, 'aviso da empresa A não aponta para campanha da empresa B'),
    ('fatia_historica', 'fatia_historica_conta_anuncio_fkey', $$
      INSERT INTO normalizado.fatia_historica (empresa_id, conta_anuncio_id, mes_referencia, execucao_id)
      SELECT x.empresa_id, c.id, '2025-04-01', x.id
      FROM normalizado.execucao_carga AS x, normalizado.conta_anuncio AS c
      WHERE x.id = '00000000-0000-4000-8000-00000000000a' AND c.id_meta = '222222222222222'
    $$, 'fatia da empresa A não aponta para conta da empresa B'),
    ('fatia_historica', 'fatia_historica_execucao_carga_fkey', $$
      INSERT INTO normalizado.fatia_historica (empresa_id, conta_anuncio_id, mes_referencia, execucao_id)
      SELECT empresa_id, id, '2025-04-01', '00000000-0000-4000-8000-00000000000b'
      FROM normalizado.conta_anuncio WHERE id_meta = '111111111111111'
    $$, 'fatia da empresa A não aponta para execução da empresa B'),
    ('resposta_api', 'resposta_api_execucao_carga_fkey', $$
      INSERT INTO bruto.resposta_api (empresa_id, execucao_id, conta_anuncio_id, endpoint, parametros, data_referencia, resposta)
      SELECT empresa_id, '00000000-0000-4000-8000-00000000000b', id, 'act_111111111111111/ads', '{}', '2025-01-31', '{}'
      FROM normalizado.conta_anuncio WHERE id_meta = '111111111111111'
    $$, 'resposta bruta da empresa A não aponta para execução da empresa B'),
    ('resposta_api', 'resposta_api_conta_anuncio_fkey', $$
      INSERT INTO bruto.resposta_api (empresa_id, execucao_id, conta_anuncio_id, endpoint, parametros, data_referencia, resposta)
      SELECT x.empresa_id, x.id, c.id, 'act_222222222222222/ads', '{}', '2025-01-31', '{}'
      FROM normalizado.execucao_carga AS x, normalizado.conta_anuncio AS c
      WHERE x.id = '00000000-0000-4000-8000-00000000000a' AND c.id_meta = '222222222222222'
    $$, 'resposta bruta da empresa A não aponta para conta da empresa B')
) AS caso (tabela, restricao, sql, descricao);

-- Privilégios da etl_carga (ADR-0009 §3). Cada privilégio é conferido
-- sozinho, porque has_table_privilege com uma lista devolve verdadeiro se o
-- papel tiver qualquer um deles.
SELECT is(
  ARRAY(
    SELECT privilegio
    FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN']) AS privilegio
    WHERE has_table_privilege('etl_carga', tabela, privilegio)
       OR (privilegio IN ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES')
           AND has_any_column_privilege('etl_carga', tabela, privilegio))
  ),
  esperado,
  format('etl_carga tem só %s em %s', array_to_string(esperado, ', '), tabela)
)
FROM (
  VALUES
    ('normalizado.execucao_carga', ARRAY['SELECT', 'INSERT', 'UPDATE']),
    ('normalizado.fatia_historica', ARRAY['SELECT', 'INSERT', 'UPDATE']),
    ('normalizado.contagem_linhas_execucao', ARRAY['SELECT', 'INSERT']),
    ('normalizado.aviso_execucao', ARRAY['SELECT', 'INSERT']),
    ('bruto.resposta_api', ARRAY['SELECT', 'INSERT', 'DELETE'])
) AS caso (tabela, esperado);
SELECT policies_are(esquema, tabela, ARRAY['etl_carga_acessa'], format('%s tem só a política da etl_carga', tabela))
FROM (
  VALUES
    ('normalizado', 'execucao_carga'),
    ('normalizado', 'contagem_linhas_execucao'),
    ('normalizado', 'aviso_execucao'),
    ('normalizado', 'fatia_historica'),
    ('bruto', 'resposta_api')
) AS t (esquema, tabela);

-- Como etl_carga, as funções do pgTAP não ficam acessíveis: o resultado é
-- guardado num parâmetro da transação e comparado depois de voltar ao
-- postgres. Uma política que escondesse as linhas faria os UPDATEs e o DELETE
-- terminarem sem erro e sem efeito, por isso o resultado é conferido nas
-- próprias linhas. As colunas identity não exigem grant na sequência.
SET LOCAL ROLE etl_carga;
DO $$
DECLARE
  v_execucao_id uuid;
BEGIN
  INSERT INTO normalizado.execucao_carga (empresa_id, tipo)
  SELECT empresa_id, 'historica' FROM normalizado.conta_anuncio WHERE id_meta = '222222222222222'
  RETURNING id INTO v_execucao_id;
  INSERT INTO normalizado.fatia_historica (empresa_id, conta_anuncio_id, mes_referencia, execucao_id)
  SELECT empresa_id, id, '2025-05-01', v_execucao_id FROM normalizado.conta_anuncio WHERE id_meta = '222222222222222';
  INSERT INTO bruto.resposta_api (empresa_id, execucao_id, conta_anuncio_id, endpoint, parametros, data_referencia, resposta)
  SELECT empresa_id, v_execucao_id, id, 'act_222222222222222/insights', '{"level": "ad"}', '2025-05-31', '{"data": []}'
  FROM normalizado.conta_anuncio WHERE id_meta = '222222222222222';
  INSERT INTO bruto.resposta_api (empresa_id, execucao_id, conta_anuncio_id, endpoint, parametros, data_referencia, resposta)
  SELECT empresa_id, v_execucao_id, id, 'act_222222222222222/ads', '{"fields": "id"}', '2025-04-30', '{"data": []}'
  FROM normalizado.conta_anuncio WHERE id_meta = '222222222222222';
  INSERT INTO normalizado.aviso_execucao (empresa_id, execucao_id, tipo, campanha_id)
  SELECT empresa_id, v_execucao_id, 'objetivo_nao_classificado', id FROM normalizado.campanha WHERE id_meta = '120000000000000102';
  UPDATE normalizado.fatia_historica SET status = 'concluida' WHERE execucao_id = v_execucao_id;
  DELETE FROM bruto.resposta_api WHERE execucao_id = v_execucao_id AND data_referencia < '2025-05-01';
  UPDATE normalizado.execucao_carga SET status = 'sucesso', terminado_em = now() WHERE id = v_execucao_id;
  INSERT INTO normalizado.contagem_linhas_execucao (empresa_id, execucao_id, tabela, linhas)
  SELECT empresa_id, id, 'resposta_api', 1 FROM normalizado.execucao_carga WHERE id = v_execucao_id;
  PERFORM set_config('controle_execucoes_test.execucao_id', v_execucao_id::text, true);
  PERFORM set_config('controle_execucoes_test.etl', 'aceito', true);
EXCEPTION WHEN OTHERS THEN
  PERFORM set_config('controle_execucoes_test.etl', SQLSTATE, true);
END
$$;
RESET ROLE;
SELECT is(current_setting('controle_execucoes_test.etl'), 'aceito', 'etl_carga grava o controle de execuções e o bruto sem erro');
SELECT results_eq(
  format(
    $$
    SELECT 'execucao_carga', status FROM normalizado.execucao_carga WHERE id = %1$L
    UNION ALL SELECT 'fatia_historica', status FROM normalizado.fatia_historica WHERE execucao_id = %1$L
    UNION ALL SELECT 'resposta_api', data_referencia::text FROM bruto.resposta_api WHERE execucao_id = %1$L
    UNION ALL SELECT 'aviso_execucao', tipo FROM normalizado.aviso_execucao WHERE execucao_id = %1$L
    UNION ALL SELECT 'contagem_linhas_execucao', linhas::text FROM normalizado.contagem_linhas_execucao WHERE execucao_id = %1$L
    $$,
    current_setting('controle_execucoes_test.execucao_id')
  ),
  $$
  VALUES ('execucao_carga', 'sucesso'), ('fatia_historica', 'concluida'), ('resposta_api', '2025-05-31'),
    ('aviso_execucao', 'objetivo_nao_classificado'), ('contagem_linhas_execucao', '1')
  $$,
  'etl_carga registra a execução, as fatias, os avisos e as contagens, e apaga respostas brutas'
);

SELECT * FROM finish();
ROLLBACK;
