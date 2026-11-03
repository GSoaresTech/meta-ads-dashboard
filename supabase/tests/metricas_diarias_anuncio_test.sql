-- Prova as métricas e as ações diárias por anúncio: o grão único, as medidas
-- anuláveis e não negativas, a exclusão das ações junto com a métrica e as
-- chaves que impedem apontar para outra empresa (RF-12, RF-17; CLAUDE.md §5;
-- ADR-0009 §1, §2 e §3).
BEGIN;
SELECT plan(74);

-- Estrutura
SELECT col_is_pk(
  'normalizado', 'metrica_diaria_anuncio', ARRAY['empresa_id', 'anuncio_id', 'data'],
  'metrica_diaria_anuncio tem PK (empresa_id, anuncio_id, data), o grão'
);
SELECT col_is_pk(
  'normalizado', 'acao_diaria_anuncio', ARRAY['empresa_id', 'anuncio_id', 'data', 'tipo_acao'],
  'acao_diaria_anuncio tem PK (empresa_id, anuncio_id, data, tipo_acao), o grão'
);
SELECT fk_ok(
  'normalizado', 'metrica_diaria_anuncio', ARRAY['empresa_id', 'anuncio_id'],
  'normalizado', 'anuncio', ARRAY['empresa_id', 'id'],
  'metrica_diaria_anuncio.anuncio_id tem FK composta para anuncio'
);
SELECT fk_ok(
  'normalizado', 'acao_diaria_anuncio', ARRAY['empresa_id', 'anuncio_id', 'data'],
  'normalizado', 'metrica_diaria_anuncio', ARRAY['empresa_id', 'anuncio_id', 'data'],
  'acao_diaria_anuncio tem FK composta para a métrica do mesmo anúncio e dia'
);
SELECT fk_ok(
  'normalizado', tabela, ARRAY['empresa_id', 'execucao_id'], 'normalizado', 'execucao_carga', ARRAY['empresa_id', 'id'],
  format('%s.execucao_id tem FK composta para execucao_carga', tabela)
)
FROM unnest(ARRAY['metrica_diaria_anuncio', 'acao_diaria_anuncio']) AS tabela;
SELECT fk_ok('normalizado', tabela, 'empresa_id', 'normalizado', 'empresa', 'id', format('%s.empresa_id referencia empresa', tabela))
FROM unnest(ARRAY['metrica_diaria_anuncio', 'acao_diaria_anuncio']) AS tabela;
-- Uma data fora do calendário falha na carga, em vez de sumir de um
-- agrupamento (ADR-0009 §1).
SELECT fk_ok('normalizado', tabela, 'data', 'normalizado', 'calendario', 'data', format('%s.data referencia calendario', tabela))
FROM unnest(ARRAY['metrica_diaria_anuncio', 'acao_diaria_anuncio']) AS tabela;
-- Só as ações saem em cascata com o fato; o resto é NO ACTION (ADR-0009 §1).
SELECT results_eq(
  $$
  SELECT conname, confdeltype
  FROM pg_catalog.pg_constraint
  WHERE conrelid IN ('normalizado.metrica_diaria_anuncio'::regclass, 'normalizado.acao_diaria_anuncio'::regclass)
    AND contype = 'f'
  ORDER BY conname
  $$,
  $$
  VALUES
    ('acao_diaria_anuncio_calendario_fkey'::name, 'a'::"char"),
    ('acao_diaria_anuncio_empresa_id_fkey', 'a'),
    ('acao_diaria_anuncio_execucao_carga_fkey', 'a'),
    ('acao_diaria_anuncio_metrica_diaria_anuncio_fkey', 'c'),
    ('metrica_diaria_anuncio_anuncio_fkey', 'a'),
    ('metrica_diaria_anuncio_calendario_fkey', 'a'),
    ('metrica_diaria_anuncio_empresa_id_fkey', 'a'),
    ('metrica_diaria_anuncio_execucao_carga_fkey', 'a')
  $$,
  'só a FK das ações para a métrica é ON DELETE CASCADE'
);
SELECT col_not_null('normalizado', tabela, 'execucao_id', format('%s.execucao_id é NOT NULL', tabela))
FROM unnest(ARRAY['metrica_diaria_anuncio', 'acao_diaria_anuncio']) AS tabela;
-- Métrica-base ausente é NULL, nunca zero (CLAUDE.md §5).
SELECT col_is_null('normalizado', tabela, coluna, format('%s.%s é anulável', tabela, coluna))
FROM (
  VALUES
    ('metrica_diaria_anuncio', 'investimento'),
    ('metrica_diaria_anuncio', 'impressoes'),
    ('metrica_diaria_anuncio', 'alcance'),
    ('acao_diaria_anuncio', 'quantidade'),
    ('acao_diaria_anuncio', 'valor')
) AS medida (tabela, coluna);
SELECT col_hasnt_default('normalizado', tabela, coluna, format('%s.%s não tem DEFAULT', tabela, coluna))
FROM (
  VALUES
    ('metrica_diaria_anuncio', 'investimento'),
    ('metrica_diaria_anuncio', 'impressoes'),
    ('metrica_diaria_anuncio', 'alcance'),
    ('acao_diaria_anuncio', 'quantidade'),
    ('acao_diaria_anuncio', 'valor')
) AS medida (tabela, coluna);
-- Dinheiro em numeric e contagens em bigint (ADR-0009 §1).
SELECT col_type_is('normalizado', tabela, coluna, tipo, format('%s.%s é %s', tabela, coluna, tipo))
FROM (
  VALUES
    ('metrica_diaria_anuncio', 'investimento', 'numeric'),
    ('metrica_diaria_anuncio', 'impressoes', 'bigint'),
    ('metrica_diaria_anuncio', 'alcance', 'bigint'),
    ('acao_diaria_anuncio', 'quantidade', 'bigint'),
    ('acao_diaria_anuncio', 'valor', 'numeric')
) AS medida (tabela, coluna, tipo);
-- Intervalos do painel e substituição da janela (ADR-0009 §2).
SELECT has_index(
  'normalizado', tabela, format('%s_empresa_id_data_idx', tabela), ARRAY['empresa_id', 'data'],
  format('%s tem índice (empresa_id, data)', tabela)
)
FROM unnest(ARRAY['metrica_diaria_anuncio', 'acao_diaria_anuncio']) AS tabela;

-- Uma hierarquia e uma execução por empresa, com id fixo: a da A termina em
-- a, e a da B, em b. O anúncio da A é 120000000000000401, e o da B,
-- 120000000000000402.
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
SELECT c.empresa_id, c.id, '12000000000000010' || v.sufixo, 'OUTCOME_SALES', 'ACTIVE', x.id
FROM normalizado.conta_anuncio AS c
JOIN normalizado.execucao_carga AS x USING (empresa_id)
JOIN (VALUES ('111111111111111', '1'), ('222222222222222', '2')) AS v (conta, sufixo) ON v.conta = c.id_meta;
INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, status, execucao_id)
SELECT empresa_id, id, '12000000000000020' || right(id_meta, 1), 'ACTIVE', execucao_id
FROM normalizado.campanha WHERE id_meta IN ('120000000000000101', '120000000000000102');
INSERT INTO normalizado.criativo (empresa_id, conta_anuncio_id, id_meta, execucao_id)
SELECT empresa_id, conta_anuncio_id, '12000000000000030' || right(id_meta, 1), execucao_id
FROM normalizado.campanha WHERE id_meta IN ('120000000000000101', '120000000000000102');
INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, status, execucao_id)
SELECT j.empresa_id, j.id, k.id, '12000000000000040' || right(j.id_meta, 1), 'ACTIVE', j.execucao_id
FROM normalizado.conjunto_anuncio AS j
JOIN normalizado.criativo AS k ON k.empresa_id = j.empresa_id
WHERE j.id_meta IN ('120000000000000201', '120000000000000202');
SELECT results_eq(
  $$SELECT id_meta FROM normalizado.anuncio WHERE id_meta LIKE '120%' ORDER BY id_meta$$,
  $$VALUES ('120000000000000401'), ('120000000000000402')$$,
  'um anúncio por empresa'
);

-- Uma inclusão por tabela, com o anúncio (%1$L), a data (%2$L), a execução
-- (%3$L) e as medidas como parâmetros.
CREATE TEMPORARY TABLE modelo_insercao (tabela text PRIMARY KEY, sql text NOT NULL);
INSERT INTO modelo_insercao VALUES
  ('metrica_diaria_anuncio', $$
    INSERT INTO normalizado.metrica_diaria_anuncio (empresa_id, anuncio_id, data, investimento, impressoes, alcance, execucao_id)
    SELECT empresa_id, id, %2$L, %4$s, %5$s, %6$s, %3$L FROM normalizado.anuncio WHERE id_meta = %1$L
  $$),
  ('acao_diaria_anuncio', $$
    INSERT INTO normalizado.acao_diaria_anuncio (empresa_id, anuncio_id, data, tipo_acao, quantidade, valor, execucao_id)
    SELECT empresa_id, id, %2$L, %4$L, %5$s, %6$s, %3$L FROM normalizado.anuncio WHERE id_meta = %1$L
  $$);

SELECT lives_ok(
  format(sql, '120000000000000401', '2026-03-02', '00000000-0000-4000-8000-00000000000a', '150.37', '12000', '8000'),
  'métrica do anúncio da A no dia é aceita'
)
FROM modelo_insercao WHERE tabela = 'metrica_diaria_anuncio';
SELECT lives_ok(
  format(sql, '120000000000000401', '2026-03-03', '00000000-0000-4000-8000-00000000000a', 'NULL', 'NULL', 'NULL'),
  'métrica com todas as medidas ausentes é aceita, com NULL (CLAUDE.md §5)'
)
FROM modelo_insercao WHERE tabela = 'metrica_diaria_anuncio';
SELECT lives_ok(
  format(sql, '120000000000000402', '2026-03-02', '00000000-0000-4000-8000-00000000000b', '0', '0', '0'),
  'métrica com medidas zeradas é aceita'
)
FROM modelo_insercao WHERE tabela = 'metrica_diaria_anuncio';
SELECT results_eq(
  $$
  SELECT investimento, impressoes, alcance
  FROM normalizado.metrica_diaria_anuncio WHERE data = '2026-03-03'
  $$,
  $$VALUES (NULL::numeric, NULL::bigint, NULL::bigint)$$,
  'medidas ausentes ficam NULL, não zero'
);
SELECT lives_ok(
  format(sql, '120000000000000401', '2026-03-02', '00000000-0000-4000-8000-00000000000a', tipo_acao, quantidade, valor),
  format('ação %s do anúncio no dia é aceita', tipo_acao)
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    ('offsite_conversion.fb_pixel_purchase', '3', '450.90'),
    ('link_click', '120', 'NULL'),
    ('onsite_conversion.messaging_conversation_started_7d', '5', 'NULL'),
    ('omni_purchase', 'NULL', '450.90'),
    ('lead', '0', '0')
) AS acao (tipo_acao, quantidade, valor)
WHERE tabela = 'acao_diaria_anuncio';

-- Grão único: uma segunda linha no mesmo grão é recusada, inclusive com
-- outra execução da mesma empresa.
INSERT INTO normalizado.execucao_carga (id, empresa_id, tipo)
SELECT '00000000-0000-4000-8000-0000000000a2', id, 'horaria' FROM normalizado.empresa WHERE nome = 'Empresa Teste A';
SELECT throws_ok(
  format(sql, '120000000000000401', '2026-03-02', '00000000-0000-4000-8000-0000000000a2', '1', '1', '1'),
  '23505',
  'duplicate key value violates unique constraint "metrica_diaria_anuncio_pkey"',
  'segunda métrica do mesmo anúncio no mesmo dia é recusada'
)
FROM modelo_insercao WHERE tabela = 'metrica_diaria_anuncio';
SELECT throws_ok(
  format(sql, '120000000000000401', '2026-03-02', '00000000-0000-4000-8000-0000000000a2', 'link_click', '1', 'NULL'),
  '23505',
  'duplicate key value violates unique constraint "acao_diaria_anuncio_pkey"',
  'segunda ação do mesmo tipo no mesmo anúncio e dia é recusada'
)
FROM modelo_insercao WHERE tabela = 'acao_diaria_anuncio';

-- Valores negativos são recusados em toda medida.
SELECT throws_ok(
  format(m.sql, VARIADIC ARRAY['120000000000000401', '2026-03-04', '00000000-0000-4000-8000-00000000000a'] || caso.valores),
  '23514',
  format('new row for relation "%s" violates check constraint "%s_%s_check"', m.tabela, m.tabela, caso.coluna),
  format('%s.%s negativo é recusado', m.tabela, caso.coluna)
)
FROM modelo_insercao AS m
JOIN (
  VALUES
    ('metrica_diaria_anuncio', 'investimento', ARRAY['-0.01', '1', '1']),
    ('metrica_diaria_anuncio', 'impressoes', ARRAY['1', '-1', '1']),
    ('metrica_diaria_anuncio', 'alcance', ARRAY['1', '1', '-1'])
) AS caso (tabela, coluna, valores) USING (tabela);
SELECT throws_ok(
  format(m.sql, VARIADIC ARRAY['120000000000000401', '2026-03-02', '00000000-0000-4000-8000-00000000000a'] || caso.valores),
  '23514',
  format('new row for relation "%s" violates check constraint "%s_%s_check"', m.tabela, m.tabela, caso.coluna),
  format('%s.%s negativo é recusado', m.tabela, caso.coluna)
)
FROM modelo_insercao AS m
JOIN (
  VALUES
    ('acao_diaria_anuncio', 'quantidade', ARRAY['landing_page_view', '-1', 'NULL']),
    ('acao_diaria_anuncio', 'valor', ARRAY['landing_page_view', 'NULL', '-0.01'])
) AS caso (tabela, coluna, valores) USING (tabela);

-- Uma ação sem quantidade nem valor não diz nada; a ausência de ocorrência é
-- a ausência da linha (CLAUDE.md §5).
SELECT throws_ok(
  format(sql, '120000000000000401', '2026-03-02', '00000000-0000-4000-8000-00000000000a', 'landing_page_view', 'NULL', 'NULL'),
  '23514',
  'new row for relation "acao_diaria_anuncio" violates check constraint "acao_diaria_anuncio_medida_check"',
  'ação sem quantidade nem valor é recusada'
)
FROM modelo_insercao WHERE tabela = 'acao_diaria_anuncio';

-- Tipo de ação: domínio aberto, só o formato dos tipos da Meta (R-21).
SELECT throws_ok(
  format(sql, '120000000000000401', '2026-03-02', '00000000-0000-4000-8000-00000000000a', tipo_acao, '1', 'NULL'),
  '23514',
  'new row for relation "acao_diaria_anuncio" violates check constraint "acao_diaria_anuncio_tipo_acao_check"',
  format('tipo de ação %L fora do formato é recusado', tipo_acao)
)
FROM modelo_insercao
CROSS JOIN unnest(ARRAY['', ' link_click', 'Link Click', 'LINK_CLICK', 'link_click.', '.link_click', 'link..click']) AS tipo_acao
WHERE tabela = 'acao_diaria_anuncio';
SELECT throws_ok(
  format(sql, '120000000000000401', '2026-03-02', '00000000-0000-4000-8000-00000000000a', NULL, '1', 'NULL'),
  '23502', NULL, 'ação sem tipo é recusada'
)
FROM modelo_insercao WHERE tabela = 'acao_diaria_anuncio';
SELECT lives_ok(
  format(sql, '120000000000000401', '2026-03-02', '00000000-0000-4000-8000-00000000000a', 'offsite_conversion.custom.120000000000000999', '2', '30'),
  'tipo de ação de conversão personalizada, com ID numérico, é aceito'
)
FROM modelo_insercao WHERE tabela = 'acao_diaria_anuncio';

-- Toda ação pertence a uma métrica do mesmo anúncio e dia.
SELECT throws_ok(
  format(sql, '120000000000000401', '2026-03-05', '00000000-0000-4000-8000-00000000000a', 'link_click', '1', 'NULL'),
  '23503',
  'insert or update on table "acao_diaria_anuncio" violates foreign key constraint "acao_diaria_anuncio_metrica_diaria_anuncio_fkey"',
  'ação sem a métrica do mesmo anúncio e dia é recusada'
)
FROM modelo_insercao WHERE tabela = 'acao_diaria_anuncio';
-- O calendário vai de 2023 a 2035 (ADR-0009 §2).
SELECT throws_ok(
  format(sql, '120000000000000401', '2036-01-01', '00000000-0000-4000-8000-00000000000a', '1', '1', '1'),
  '23503',
  'insert or update on table "metrica_diaria_anuncio" violates foreign key constraint "metrica_diaria_anuncio_calendario_fkey"',
  'métrica com data fora do calendário é recusada'
)
FROM modelo_insercao WHERE tabela = 'metrica_diaria_anuncio';
SELECT throws_ok(
  format(sql, '120000000000000401', NULL, '00000000-0000-4000-8000-00000000000a', '1', '1', '1'),
  '23502', NULL, 'métrica sem data é recusada'
)
FROM modelo_insercao WHERE tabela = 'metrica_diaria_anuncio';
SELECT throws_ok(
  format(sql, '120000000000000401', '2026-03-04', NULL, '1', '1', '1'),
  '23502', NULL, 'métrica sem execução é recusada'
)
FROM modelo_insercao WHERE tabela = 'metrica_diaria_anuncio';

-- Isolamento: nenhuma linha da empresa A aponta para anúncio, métrica ou
-- execução da empresa B (ADR-0009 §1).
SELECT throws_ok(
  $$
  INSERT INTO normalizado.metrica_diaria_anuncio (empresa_id, anuncio_id, data, investimento, execucao_id)
  SELECT e.id, a.id, '2026-03-04', 1, '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.empresa AS e, normalizado.anuncio AS a
  WHERE e.nome = 'Empresa Teste A' AND a.id_meta = '120000000000000402'
  $$,
  '23503',
  'insert or update on table "metrica_diaria_anuncio" violates foreign key constraint "metrica_diaria_anuncio_anuncio_fkey"',
  'métrica da empresa A não aponta para anúncio da empresa B'
);
SELECT throws_ok(
  format(sql, '120000000000000401', '2026-03-04', '00000000-0000-4000-8000-00000000000b', '1', '1', '1'),
  '23503',
  'insert or update on table "metrica_diaria_anuncio" violates foreign key constraint "metrica_diaria_anuncio_execucao_carga_fkey"',
  'métrica da empresa A não aponta para execução da empresa B'
)
FROM modelo_insercao WHERE tabela = 'metrica_diaria_anuncio';
SELECT throws_ok(
  $$
  INSERT INTO normalizado.acao_diaria_anuncio (empresa_id, anuncio_id, data, tipo_acao, quantidade, execucao_id)
  SELECT e.id, m.anuncio_id, m.data, 'link_click', 1, '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.empresa AS e, normalizado.metrica_diaria_anuncio AS m
  JOIN normalizado.anuncio AS a ON a.id = m.anuncio_id
  WHERE e.nome = 'Empresa Teste A' AND a.id_meta = '120000000000000402'
  $$,
  '23503',
  'insert or update on table "acao_diaria_anuncio" violates foreign key constraint "acao_diaria_anuncio_metrica_diaria_anuncio_fkey"',
  'ação da empresa A não aponta para métrica da empresa B'
);
SELECT throws_ok(
  format(sql, '120000000000000401', '2026-03-02', '00000000-0000-4000-8000-00000000000b', 'video_view', '1', 'NULL'),
  '23503',
  'insert or update on table "acao_diaria_anuncio" violates foreign key constraint "acao_diaria_anuncio_execucao_carga_fkey"',
  'ação da empresa A não aponta para execução da empresa B'
)
FROM modelo_insercao WHERE tabela = 'acao_diaria_anuncio';

-- Exclusão: o anúncio com métricas não sai (NO ACTION), e a métrica leva as
-- ações dela, sem tocar nas de outro dia nem nas de outro anúncio.
SELECT throws_ok(
  $$DELETE FROM normalizado.anuncio WHERE id_meta = '120000000000000401'$$,
  '23503', NULL,
  'anúncio com métricas não é apagado'
);
INSERT INTO normalizado.metrica_diaria_anuncio (empresa_id, anuncio_id, data, investimento, execucao_id)
SELECT empresa_id, id, '2026-03-04', 10, '00000000-0000-4000-8000-00000000000a'
FROM normalizado.anuncio WHERE id_meta = '120000000000000401';
INSERT INTO normalizado.acao_diaria_anuncio (empresa_id, anuncio_id, data, tipo_acao, quantidade, execucao_id)
SELECT empresa_id, anuncio_id, data, 'link_click',
  CASE execucao_id WHEN '00000000-0000-4000-8000-00000000000a' THEN 7 ELSE 4 END, execucao_id
FROM normalizado.metrica_diaria_anuncio
WHERE data = '2026-03-04' OR execucao_id = '00000000-0000-4000-8000-00000000000b';
SELECT lives_ok(
  $$
  DELETE FROM normalizado.metrica_diaria_anuncio
  WHERE data = '2026-03-02'
    AND anuncio_id = (SELECT id FROM normalizado.anuncio WHERE id_meta = '120000000000000401')
  $$,
  'métrica do anúncio da A no dia é apagada'
);
SELECT results_eq(
  $$
  SELECT a.id_meta, x.data, x.tipo_acao, x.quantidade
  FROM normalizado.acao_diaria_anuncio AS x
  JOIN normalizado.anuncio AS a ON a.id = x.anuncio_id
  ORDER BY a.id_meta, x.data
  $$,
  $$
  VALUES
    ('120000000000000401', '2026-03-04'::date, 'link_click', 7::bigint),
    ('120000000000000402', '2026-03-02'::date, 'link_click', 4::bigint)
  $$,
  'as ações da métrica apagada saem junto, e as de outro dia e de outro anúncio ficam'
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
FROM unnest(ARRAY['metrica_diaria_anuncio', 'acao_diaria_anuncio']) AS tabela;
SELECT policies_are('normalizado', tabela, ARRAY['etl_carga_acessa'], format('%s tem só a política da etl_carga', tabela))
FROM unnest(ARRAY['metrica_diaria_anuncio', 'acao_diaria_anuncio']) AS tabela;

-- Como etl_carga, as funções do pgTAP não ficam acessíveis: o resultado é
-- guardado num parâmetro da transação e conferido nas próprias linhas,
-- depois de voltar ao postgres. Uma política que escondesse as linhas faria
-- o DELETE terminar sem erro e sem efeito.
SET LOCAL ROLE etl_carga;
DO $$
BEGIN
  DELETE FROM normalizado.metrica_diaria_anuncio
  WHERE execucao_id = '00000000-0000-4000-8000-00000000000b';
  INSERT INTO normalizado.metrica_diaria_anuncio (empresa_id, anuncio_id, data, investimento, impressoes, alcance, execucao_id)
  SELECT empresa_id, id, '2026-03-02', 20.5, 900, 700, '00000000-0000-4000-8000-00000000000b'
  FROM normalizado.anuncio WHERE id_meta = '120000000000000402';
  INSERT INTO normalizado.acao_diaria_anuncio (empresa_id, anuncio_id, data, tipo_acao, quantidade, valor, execucao_id)
  SELECT empresa_id, anuncio_id, data, 'omni_purchase', 1, 99.9, execucao_id
  FROM normalizado.metrica_diaria_anuncio WHERE execucao_id = '00000000-0000-4000-8000-00000000000b';
  PERFORM set_config('metricas_diarias_anuncio_test.etl', 'aceito', true);
EXCEPTION WHEN OTHERS THEN
  PERFORM set_config('metricas_diarias_anuncio_test.etl', SQLSTATE, true);
END
$$;
RESET ROLE;
SELECT is(current_setting('metricas_diarias_anuncio_test.etl'), 'aceito', 'etl_carga substitui as métricas e as ações sem erro');
SELECT results_eq(
  $$
  SELECT m.investimento, m.impressoes, m.alcance, x.tipo_acao, x.quantidade, x.valor
  FROM normalizado.metrica_diaria_anuncio AS m
  JOIN normalizado.acao_diaria_anuncio AS x USING (empresa_id, anuncio_id, data)
  WHERE m.execucao_id = '00000000-0000-4000-8000-00000000000b'
  $$,
  $$VALUES (20.5::numeric, 900::bigint, 700::bigint, 'omni_purchase', 1::bigint, 99.9::numeric)$$,
  'a substituição da etl_carga deixa só as linhas novas, sem a ação antiga'
);

SELECT * FROM finish();
ROLLBACK;
