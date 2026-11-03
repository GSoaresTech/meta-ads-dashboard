-- Prova as quebras diárias por campanha e as ações delas: o grão único, com
-- subcategoria nula na região, as medidas anuláveis e não negativas, a
-- exclusão das ações junto com a linha de quebra e as chaves que impedem
-- apontar para outra empresa (RF-03; ADR-0009 §1, §2 e §3).
BEGIN;
SELECT plan(91);

-- Estrutura. Alto volume e sem referência externa: bigint identity
-- (ADR-0009 §1).
SELECT col_is_pk('normalizado', 'quebra_diaria_campanha', 'id', 'id é a PK de quebra_diaria_campanha');
SELECT col_type_is('normalizado', 'quebra_diaria_campanha', 'id', 'bigint', 'id de quebra_diaria_campanha é bigint');
SELECT is(
  (SELECT attidentity::text FROM pg_catalog.pg_attribute WHERE attrelid = 'normalizado.quebra_diaria_campanha'::regclass AND attname = 'id'),
  'a',
  'id de quebra_diaria_campanha é GENERATED ALWAYS AS IDENTITY'
);
SELECT col_is_unique(
  'normalizado', 'quebra_diaria_campanha', ARRAY['empresa_id', 'id'],
  'quebra_diaria_campanha tem UNIQUE (empresa_id, id), alvo da FK composta das ações'
);
-- O grão tem coluna anulável e por isso não cabe numa PK; o UNIQUE trata
-- dois NULL como iguais (ADR-0009 §2).
SELECT results_eq(
  $$
  SELECT array_agg(a.attname ORDER BY k.ordem), i.indnullsnotdistinct
  FROM pg_catalog.pg_constraint AS c
  JOIN pg_catalog.pg_index AS i ON i.indexrelid = c.conindid
  CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k (attnum, ordem)
  JOIN pg_catalog.pg_attribute AS a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
  WHERE c.conname = 'quebra_diaria_campanha_grao_key' AND c.contype = 'u'
  GROUP BY i.indnullsnotdistinct
  $$,
  $$VALUES (ARRAY['empresa_id', 'campanha_id', 'data', 'tipo_quebra', 'categoria', 'subcategoria']::name[], true)$$,
  'quebra_diaria_campanha tem UNIQUE NULLS NOT DISTINCT no grão'
);
SELECT col_is_pk(
  'normalizado', 'acao_quebra_diaria_campanha', ARRAY['empresa_id', 'quebra_diaria_campanha_id', 'tipo_acao'],
  'acao_quebra_diaria_campanha tem PK (empresa_id, quebra_diaria_campanha_id, tipo_acao), o grão'
);
SELECT fk_ok(
  'normalizado', 'quebra_diaria_campanha', ARRAY['empresa_id', 'campanha_id'],
  'normalizado', 'campanha', ARRAY['empresa_id', 'id'],
  'quebra_diaria_campanha.campanha_id tem FK composta para campanha'
);
SELECT fk_ok(
  'normalizado', 'acao_quebra_diaria_campanha', ARRAY['empresa_id', 'quebra_diaria_campanha_id'],
  'normalizado', 'quebra_diaria_campanha', ARRAY['empresa_id', 'id'],
  'acao_quebra_diaria_campanha tem FK composta para a linha de quebra'
);
SELECT fk_ok(
  'normalizado', tabela, ARRAY['empresa_id', 'execucao_id'], 'normalizado', 'execucao_carga', ARRAY['empresa_id', 'id'],
  format('%s.execucao_id tem FK composta para execucao_carga', tabela)
)
FROM unnest(ARRAY['quebra_diaria_campanha', 'acao_quebra_diaria_campanha']) AS tabela;
SELECT fk_ok('normalizado', tabela, 'empresa_id', 'normalizado', 'empresa', 'id', format('%s.empresa_id referencia empresa', tabela))
FROM unnest(ARRAY['quebra_diaria_campanha', 'acao_quebra_diaria_campanha']) AS tabela;
SELECT fk_ok(
  'normalizado', 'quebra_diaria_campanha', 'data', 'normalizado', 'calendario', 'data',
  'quebra_diaria_campanha.data referencia calendario'
);
-- Só as ações saem em cascata com o fato; o resto é NO ACTION (ADR-0009 §1).
SELECT results_eq(
  $$
  SELECT conname, confdeltype
  FROM pg_catalog.pg_constraint
  WHERE conrelid IN ('normalizado.quebra_diaria_campanha'::regclass, 'normalizado.acao_quebra_diaria_campanha'::regclass)
    AND contype = 'f'
  ORDER BY conname
  $$,
  $$
  VALUES
    ('acao_quebra_diaria_campanha_empresa_id_fkey'::name, 'a'::"char"),
    ('acao_quebra_diaria_campanha_execucao_carga_fkey', 'a'),
    ('acao_quebra_diaria_campanha_quebra_diaria_campanha_fkey', 'c'),
    ('quebra_diaria_campanha_calendario_fkey', 'a'),
    ('quebra_diaria_campanha_campanha_fkey', 'a'),
    ('quebra_diaria_campanha_empresa_id_fkey', 'a'),
    ('quebra_diaria_campanha_execucao_carga_fkey', 'a')
  $$,
  'só a FK das ações para a linha de quebra é ON DELETE CASCADE'
);
-- As FKs são MATCH SIMPLE: um pai nulo dispensaria a conferência.
SELECT col_not_null('normalizado', tabela, coluna, format('%s.%s é NOT NULL', tabela, coluna))
FROM (
  VALUES
    ('quebra_diaria_campanha', 'empresa_id'),
    ('quebra_diaria_campanha', 'campanha_id'),
    ('quebra_diaria_campanha', 'data'),
    ('quebra_diaria_campanha', 'tipo_quebra'),
    ('quebra_diaria_campanha', 'categoria'),
    ('quebra_diaria_campanha', 'execucao_id'),
    ('acao_quebra_diaria_campanha', 'execucao_id')
) AS t (tabela, coluna);
-- Métrica-base ausente é NULL, nunca zero (CLAUDE.md §5).
SELECT col_is_null('normalizado', tabela, coluna, format('%s.%s é anulável', tabela, coluna))
FROM (
  VALUES
    ('quebra_diaria_campanha', 'subcategoria'),
    ('quebra_diaria_campanha', 'investimento'),
    ('quebra_diaria_campanha', 'impressoes'),
    ('quebra_diaria_campanha', 'alcance'),
    ('acao_quebra_diaria_campanha', 'quantidade'),
    ('acao_quebra_diaria_campanha', 'valor')
) AS t (tabela, coluna);
SELECT col_hasnt_default('normalizado', tabela, coluna, format('%s.%s não tem DEFAULT', tabela, coluna))
FROM (
  VALUES
    ('quebra_diaria_campanha', 'investimento'),
    ('quebra_diaria_campanha', 'impressoes'),
    ('quebra_diaria_campanha', 'alcance'),
    ('acao_quebra_diaria_campanha', 'quantidade'),
    ('acao_quebra_diaria_campanha', 'valor')
) AS t (tabela, coluna);
SELECT col_type_is('normalizado', tabela, coluna, tipo, format('%s.%s é %s', tabela, coluna, tipo))
FROM (
  VALUES
    ('quebra_diaria_campanha', 'investimento', 'numeric'),
    ('quebra_diaria_campanha', 'impressoes', 'bigint'),
    ('quebra_diaria_campanha', 'alcance', 'bigint'),
    ('acao_quebra_diaria_campanha', 'quantidade', 'bigint'),
    ('acao_quebra_diaria_campanha', 'valor', 'numeric')
) AS t (tabela, coluna, tipo);
SELECT has_index(
  'normalizado', 'quebra_diaria_campanha', 'quebra_diaria_campanha_empresa_id_data_idx', ARRAY['empresa_id', 'data'],
  'quebra_diaria_campanha tem índice (empresa_id, data)'
);

-- Uma campanha e uma execução por empresa, com id fixo: a da A termina em a,
-- e a da B, em b. A campanha da A é 120000000000000101, e a da B,
-- 120000000000000102.
INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A'), ('Empresa Teste B');
INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)
SELECT id, CASE nome WHEN 'Empresa Teste A' THEN '111111111111111' ELSE '222222222222222' END
FROM normalizado.empresa
WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');
INSERT INTO normalizado.execucao_carga (id, empresa_id, tipo)
SELECT CASE nome WHEN 'Empresa Teste A' THEN '00000000-0000-4000-8000-00000000000a' ELSE '00000000-0000-4000-8000-00000000000b' END::uuid,
  id, 'diaria'
FROM normalizado.empresa
WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');
INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, objetivo, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, 'OUTCOME_SALES', 'ACTIVE', x.id
FROM normalizado.conta_anuncio AS c
JOIN normalizado.execucao_carga AS x USING (empresa_id)
JOIN (
  VALUES ('111111111111111', '120000000000000101'), ('222222222222222', '120000000000000102')
) AS v (conta, id_meta) ON v.conta = c.id_meta;

-- Uma inclusão por tabela. Na quebra, a campanha (%1$L), a data (%2$L), a
-- execução (%3$L), o tipo de quebra, a categoria, a subcategoria e as
-- medidas. Na ação, a categoria da linha de quebra (%1$L), a execução
-- (%2$L), o tipo de ação e as medidas.
CREATE TEMPORARY TABLE modelo_insercao (tabela text PRIMARY KEY, sql text NOT NULL);
INSERT INTO modelo_insercao VALUES
  ('quebra_diaria_campanha', $$
    INSERT INTO normalizado.quebra_diaria_campanha
      (empresa_id, campanha_id, data, tipo_quebra, categoria, subcategoria, investimento, impressoes, alcance, execucao_id)
    SELECT empresa_id, id, %2$L, %4$L, %5$L, %6$L, %7$s, %8$s, %9$s, %3$L FROM normalizado.campanha WHERE id_meta = %1$L
  $$),
  ('acao_quebra_diaria_campanha', $$
    INSERT INTO normalizado.acao_quebra_diaria_campanha (empresa_id, quebra_diaria_campanha_id, tipo_acao, quantidade, valor, execucao_id)
    SELECT empresa_id, id, %3$L, %4$s, %5$s, %2$L FROM normalizado.quebra_diaria_campanha WHERE categoria = %1$L
  $$);

-- As três quebras do RF-03: idade+gênero e plataforma+posicionamento têm
-- subcategoria, e região não.
SELECT lives_ok(
  format(
    sql, '120000000000000101', '2026-03-02', '00000000-0000-4000-8000-00000000000a',
    tipo_quebra, categoria, subcategoria, '50.10', '3000', '2500'
  ),
  format('quebra %s com %s e %s é aceita', tipo_quebra, categoria, coalesce(subcategoria, 'subcategoria nula'))
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    ('idade_genero', '25-34', 'female'),
    ('plataforma_posicionamento', 'instagram', 'instagram_stories'),
    ('regiao', 'São Paulo (state)', NULL)
) AS quebra (tipo_quebra, categoria, subcategoria)
WHERE tabela = 'quebra_diaria_campanha';
SELECT lives_ok(
  format(
    sql, '120000000000000102', '2026-03-02', '00000000-0000-4000-8000-00000000000b',
    'regiao', 'Rio de Janeiro (state)', NULL, 'NULL', 'NULL', 'NULL'
  ),
  'quebra com todas as medidas ausentes é aceita, com NULL (CLAUDE.md §5)'
)
FROM modelo_insercao WHERE tabela = 'quebra_diaria_campanha';
SELECT results_eq(
  $$
  SELECT investimento, impressoes, alcance
  FROM normalizado.quebra_diaria_campanha WHERE categoria = 'Rio de Janeiro (state)'
  $$,
  $$VALUES (NULL::numeric, NULL::bigint, NULL::bigint)$$,
  'medidas ausentes ficam NULL, não zero'
);
SELECT lives_ok(
  format(sql, categoria, execucao_id, tipo_acao, quantidade, valor),
  format('ação %s da quebra %s é aceita', tipo_acao, categoria)
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    ('25-34', '00000000-0000-4000-8000-00000000000a', 'offsite_conversion.fb_pixel_purchase', '2', '180.00'),
    ('25-34', '00000000-0000-4000-8000-00000000000a', 'link_click', '40', 'NULL'),
    ('instagram', '00000000-0000-4000-8000-00000000000a', 'link_click', '15', 'NULL'),
    ('Rio de Janeiro (state)', '00000000-0000-4000-8000-00000000000b', 'link_click', '3', 'NULL')
) AS acao (categoria, execucao_id, tipo_acao, quantidade, valor)
WHERE tabela = 'acao_quebra_diaria_campanha';

-- Grão único: uma segunda linha no mesmo grão é recusada, inclusive na
-- região, em que a subcategoria nula conta como igual.
SELECT throws_ok(
  format(
    sql, '120000000000000101', '2026-03-02', '00000000-0000-4000-8000-00000000000a',
    tipo_quebra, categoria, subcategoria, '1', '1', '1'
  ),
  '23505',
  'duplicate key value violates unique constraint "quebra_diaria_campanha_grao_key"',
  format('segunda linha de %s com %s no mesmo dia é recusada', tipo_quebra, categoria)
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    ('idade_genero', '25-34', 'female'),
    ('plataforma_posicionamento', 'instagram', 'instagram_stories'),
    ('regiao', 'São Paulo (state)', NULL)
) AS quebra (tipo_quebra, categoria, subcategoria)
WHERE tabela = 'quebra_diaria_campanha';
SELECT throws_ok(
  format(sql, '25-34', '00000000-0000-4000-8000-00000000000a', 'link_click', '1', 'NULL'),
  '23505',
  'duplicate key value violates unique constraint "acao_quebra_diaria_campanha_pkey"',
  'segunda ação do mesmo tipo na mesma linha de quebra é recusada'
)
FROM modelo_insercao WHERE tabela = 'acao_quebra_diaria_campanha';
SELECT lives_ok(
  format(
    sql, '120000000000000101', '2026-03-02', '00000000-0000-4000-8000-00000000000a',
    tipo_quebra, categoria, subcategoria, '1', '1', '1'
  ),
  format('outra linha de %s, com %s, no mesmo dia é aceita', tipo_quebra, descricao)
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    ('idade_genero', '25-34', 'male', 'a mesma idade e outro gênero'),
    ('plataforma_posicionamento', 'facebook', 'instagram_stories', 'o mesmo posicionamento e outra plataforma'),
    ('regiao', 'Minas Gerais (state)', NULL, 'outra região')
) AS quebra (tipo_quebra, categoria, subcategoria, descricao)
WHERE tabela = 'quebra_diaria_campanha';

-- Valores negativos são recusados em toda medida.
SELECT throws_ok(
  format(
    m.sql,
    VARIADIC ARRAY['120000000000000101', '2026-03-03', '00000000-0000-4000-8000-00000000000a', 'regiao', 'Bahia (state)', NULL]
      || caso.valores
  ),
  '23514',
  format('new row for relation "%s" violates check constraint "%s_%s_check"', m.tabela, m.tabela, caso.coluna),
  format('%s.%s negativo é recusado', m.tabela, caso.coluna)
)
FROM modelo_insercao AS m
JOIN (
  VALUES
    ('quebra_diaria_campanha', 'investimento', ARRAY['-0.01', '1', '1']),
    ('quebra_diaria_campanha', 'impressoes', ARRAY['1', '-1', '1']),
    ('quebra_diaria_campanha', 'alcance', ARRAY['1', '1', '-1'])
) AS caso (tabela, coluna, valores) USING (tabela);
SELECT throws_ok(
  format(m.sql, VARIADIC ARRAY['25-34', '00000000-0000-4000-8000-00000000000a', 'landing_page_view'] || caso.valores),
  '23514',
  format('new row for relation "%s" violates check constraint "%s_%s_check"', m.tabela, m.tabela, caso.coluna),
  format('%s.%s negativo é recusado', m.tabela, caso.coluna)
)
FROM modelo_insercao AS m
JOIN (
  VALUES
    ('acao_quebra_diaria_campanha', 'quantidade', ARRAY['-1', 'NULL']),
    ('acao_quebra_diaria_campanha', 'valor', ARRAY['NULL', '-0.01'])
) AS caso (tabela, coluna, valores) USING (tabela);
SELECT throws_ok(
  format(sql, '25-34', '00000000-0000-4000-8000-00000000000a', 'landing_page_view', 'NULL', 'NULL'),
  '23514',
  'new row for relation "acao_quebra_diaria_campanha" violates check constraint "acao_quebra_diaria_campanha_medida_check"',
  'ação sem quantidade nem valor é recusada'
)
FROM modelo_insercao WHERE tabela = 'acao_quebra_diaria_campanha';
SELECT throws_ok(
  format(sql, '25-34', '00000000-0000-4000-8000-00000000000a', tipo_acao, '1', 'NULL'),
  '23514',
  'new row for relation "acao_quebra_diaria_campanha" violates check constraint "acao_quebra_diaria_campanha_tipo_acao_check"',
  format('tipo de ação %L fora do formato é recusado', tipo_acao)
)
FROM modelo_insercao
CROSS JOIN unnest(ARRAY['', 'LINK_CLICK', 'link click']) AS tipo_acao
WHERE tabela = 'acao_quebra_diaria_campanha';

-- Tipo de quebra: domínio fechado, e NULL também é recusado, porque um CHECK
-- avaliado como NULL passa (ADR-0009 §1).
SELECT throws_ok(
  format(
    sql, '120000000000000101', '2026-03-03', '00000000-0000-4000-8000-00000000000a',
    tipo_quebra, '25-34', 'female', '1', '1', '1'
  ),
  '23514',
  'new row for relation "quebra_diaria_campanha" violates check constraint "quebra_diaria_campanha_tipo_quebra_check"',
  format('tipo de quebra %L fora do domínio é recusado', tipo_quebra)
)
FROM modelo_insercao
CROSS JOIN unnest(ARRAY['idade', 'age_gender', 'IDADE_GENERO', '']) AS tipo_quebra
WHERE tabela = 'quebra_diaria_campanha';
SELECT throws_ok(
  format(
    sql, '120000000000000101', '2026-03-03', '00000000-0000-4000-8000-00000000000a',
    NULL, '25-34', 'female', '1', '1', '1'
  ),
  '23502', NULL, 'quebra sem tipo é recusada'
)
FROM modelo_insercao WHERE tabela = 'quebra_diaria_campanha';

-- Subcategoria: só região não tem (ADR-0009 §2).
SELECT throws_ok(
  format(
    sql, '120000000000000101', '2026-03-03', '00000000-0000-4000-8000-00000000000a',
    tipo_quebra, categoria, subcategoria, '1', '1', '1'
  ),
  '23514',
  'new row for relation "quebra_diaria_campanha" violates check constraint "quebra_diaria_campanha_regiao_subcategoria_check"',
  descricao
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    ('regiao', 'Bahia (state)', 'female', 'região com subcategoria é recusada'),
    ('idade_genero', '25-34', NULL, 'idade+gênero sem subcategoria é recusada'),
    ('plataforma_posicionamento', 'instagram', NULL, 'plataforma+posicionamento sem subcategoria é recusada')
) AS caso (tipo_quebra, categoria, subcategoria, descricao)
WHERE tabela = 'quebra_diaria_campanha';

-- Categoria: domínio aberto, com o valor da API; região é texto livre. Só o
-- texto aparado e não vazio (ADR-0009 §1).
SELECT throws_ok(
  format(
    sql, '120000000000000101', '2026-03-03', '00000000-0000-4000-8000-00000000000a',
    tipo_quebra, categoria, subcategoria, '1', '1', '1'
  ),
  '23514',
  format('new row for relation "quebra_diaria_campanha" violates check constraint "quebra_diaria_campanha_%s_check"', coluna),
  format('%s %L é recusada', coluna, CASE coluna WHEN 'categoria' THEN categoria ELSE subcategoria END)
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    ('regiao', '', NULL, 'categoria'),
    ('regiao', ' Bahia (state)', NULL, 'categoria'),
    ('idade_genero', '25-34', '', 'subcategoria'),
    ('idade_genero', '25-34', 'female ', 'subcategoria')
) AS caso (tipo_quebra, categoria, subcategoria, coluna)
WHERE tabela = 'quebra_diaria_campanha';
SELECT throws_ok(
  format(
    sql, '120000000000000101', '2026-03-03', '00000000-0000-4000-8000-00000000000a',
    'regiao', NULL, NULL, '1', '1', '1'
  ),
  '23502', NULL, 'quebra sem categoria é recusada'
)
FROM modelo_insercao WHERE tabela = 'quebra_diaria_campanha';

-- Datas do calendário, que vai de 2023 a 2035 (ADR-0009 §2).
SELECT throws_ok(
  format(
    sql, '120000000000000101', '2036-01-01', '00000000-0000-4000-8000-00000000000a',
    'regiao', 'Bahia (state)', NULL, '1', '1', '1'
  ),
  '23503',
  'insert or update on table "quebra_diaria_campanha" violates foreign key constraint "quebra_diaria_campanha_calendario_fkey"',
  'quebra com data fora do calendário é recusada'
)
FROM modelo_insercao WHERE tabela = 'quebra_diaria_campanha';

-- Isolamento: nenhuma linha da empresa A aponta para campanha, linha de
-- quebra ou execução da empresa B (ADR-0009 §1).
SELECT throws_ok(
  $$
  INSERT INTO normalizado.quebra_diaria_campanha (empresa_id, campanha_id, data, tipo_quebra, categoria, investimento, execucao_id)
  SELECT e.id, c.id, '2026-03-03', 'regiao', 'Bahia (state)', 1, '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.empresa AS e, normalizado.campanha AS c
  WHERE e.nome = 'Empresa Teste A' AND c.id_meta = '120000000000000102'
  $$,
  '23503',
  'insert or update on table "quebra_diaria_campanha" violates foreign key constraint "quebra_diaria_campanha_campanha_fkey"',
  'quebra da empresa A não aponta para campanha da empresa B'
);
SELECT throws_ok(
  format(
    sql, '120000000000000101', '2026-03-03', '00000000-0000-4000-8000-00000000000b',
    'regiao', 'Bahia (state)', NULL, '1', '1', '1'
  ),
  '23503',
  'insert or update on table "quebra_diaria_campanha" violates foreign key constraint "quebra_diaria_campanha_execucao_carga_fkey"',
  'quebra da empresa A não aponta para execução da empresa B'
)
FROM modelo_insercao WHERE tabela = 'quebra_diaria_campanha';
SELECT throws_ok(
  $$
  INSERT INTO normalizado.acao_quebra_diaria_campanha (empresa_id, quebra_diaria_campanha_id, tipo_acao, quantidade, execucao_id)
  SELECT e.id, q.id, 'video_view', 1, '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.empresa AS e, normalizado.quebra_diaria_campanha AS q
  WHERE e.nome = 'Empresa Teste A' AND q.categoria = 'Rio de Janeiro (state)'
  $$,
  '23503',
  'insert or update on table "acao_quebra_diaria_campanha" violates foreign key constraint "acao_quebra_diaria_campanha_quebra_diaria_campanha_fkey"',
  'ação da empresa A não aponta para linha de quebra da empresa B'
);
SELECT throws_ok(
  format(sql, '25-34', '00000000-0000-4000-8000-00000000000b', 'video_view', '1', 'NULL'),
  '23503',
  'insert or update on table "acao_quebra_diaria_campanha" violates foreign key constraint "acao_quebra_diaria_campanha_execucao_carga_fkey"',
  'ação da empresa A não aponta para execução da empresa B'
)
FROM modelo_insercao WHERE tabela = 'acao_quebra_diaria_campanha';

-- Exclusão: a campanha com quebras não sai (NO ACTION), e a linha de quebra
-- leva as ações dela, sem tocar nas de outra linha.
SELECT throws_ok(
  $$DELETE FROM normalizado.campanha WHERE id_meta = '120000000000000101'$$,
  '23503', NULL,
  'campanha com quebras não é apagada'
);
SELECT lives_ok(
  $$DELETE FROM normalizado.quebra_diaria_campanha WHERE categoria = '25-34' AND subcategoria = 'female'$$,
  'linha de quebra é apagada'
);
SELECT results_eq(
  $$
  SELECT q.categoria, x.tipo_acao, x.quantidade
  FROM normalizado.acao_quebra_diaria_campanha AS x
  JOIN normalizado.quebra_diaria_campanha AS q ON q.id = x.quebra_diaria_campanha_id
  ORDER BY q.categoria
  $$,
  $$
  VALUES
    ('instagram', 'link_click', 15::bigint),
    ('Rio de Janeiro (state)', 'link_click', 3::bigint)
  $$,
  'as ações da linha apagada saem junto, e as de outras linhas ficam'
);
SELECT is(
  (SELECT count(*) FROM normalizado.acao_quebra_diaria_campanha),
  2::bigint,
  'nenhuma ação fica sem linha de quebra'
);

-- Privilégios da etl_carga (ADR-0009 §3): a substituição da janela apaga e
-- inclui, sem UPDATE. Cada privilégio é conferido sozinho, porque
-- has_table_privilege com uma lista devolve verdadeiro se o papel tiver
-- qualquer um deles.
SELECT is(
  ARRAY(
    SELECT privilegio
    FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN']) AS privilegio
    WHERE has_table_privilege('etl_carga', format('normalizado.%I', tabela), privilegio)
       OR (privilegio IN ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES')
           AND has_any_column_privilege('etl_carga', format('normalizado.%I', tabela), privilegio))
  ),
  ARRAY['SELECT', 'INSERT', 'DELETE'],
  format('etl_carga tem só SELECT, INSERT, DELETE em %s', tabela)
)
FROM unnest(ARRAY['quebra_diaria_campanha', 'acao_quebra_diaria_campanha']) AS tabela;
SELECT policies_are('normalizado', tabela, ARRAY['etl_carga_acessa'], format('%s tem só a política da etl_carga', tabela))
FROM unnest(ARRAY['quebra_diaria_campanha', 'acao_quebra_diaria_campanha']) AS tabela;

-- Como etl_carga, as funções do pgTAP não ficam acessíveis: o resultado é
-- guardado num parâmetro da transação e conferido nas próprias linhas,
-- depois de voltar ao postgres. A linha de quebra recebe o id da identity,
-- que as ações usam.
SET LOCAL ROLE etl_carga;
DO $$
DECLARE
  v_quebra_id bigint;
BEGIN
  DELETE FROM normalizado.quebra_diaria_campanha
  WHERE execucao_id = '00000000-0000-4000-8000-00000000000b';
  INSERT INTO normalizado.quebra_diaria_campanha
    (empresa_id, campanha_id, data, tipo_quebra, categoria, investimento, impressoes, execucao_id)
  SELECT empresa_id, id, '2026-03-02', 'regiao', 'Rio de Janeiro (state)', 12.5, 800, '00000000-0000-4000-8000-00000000000b'
  FROM normalizado.campanha WHERE id_meta = '120000000000000102'
  RETURNING id INTO v_quebra_id;
  INSERT INTO normalizado.acao_quebra_diaria_campanha (empresa_id, quebra_diaria_campanha_id, tipo_acao, quantidade, execucao_id)
  SELECT empresa_id, id, 'landing_page_view', 9, execucao_id
  FROM normalizado.quebra_diaria_campanha WHERE id = v_quebra_id;
  PERFORM set_config('quebras_diarias_campanha_test.etl', 'aceito', true);
EXCEPTION WHEN OTHERS THEN
  PERFORM set_config('quebras_diarias_campanha_test.etl', SQLSTATE, true);
END
$$;
RESET ROLE;
SELECT is(current_setting('quebras_diarias_campanha_test.etl'), 'aceito', 'etl_carga substitui as quebras e as ações sem erro');
SELECT results_eq(
  $$
  SELECT q.categoria, q.investimento, q.impressoes, q.alcance, x.tipo_acao, x.quantidade
  FROM normalizado.quebra_diaria_campanha AS q
  JOIN normalizado.acao_quebra_diaria_campanha AS x ON x.quebra_diaria_campanha_id = q.id
  WHERE q.execucao_id = '00000000-0000-4000-8000-00000000000b'
  $$,
  $$VALUES ('Rio de Janeiro (state)', 12.5::numeric, 800::bigint, NULL::bigint, 'landing_page_view', 9::bigint)$$,
  'a substituição da etl_carga deixa só as linhas novas, sem a ação antiga'
);

SELECT * FROM finish();
ROLLBACK;
