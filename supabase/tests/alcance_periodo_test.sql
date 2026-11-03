-- Prova o alcance por período: exatamente uma entidade por linha, cada uma
-- com sua FK composta, o grão único, o alinhamento da semana ISO, do mês e do
-- ano, as medidas anuláveis e não negativas e as chaves que impedem apontar
-- para outra empresa (RF-04; ADR-0006; ADR-0009 §1, §2 e §3).
BEGIN;
SELECT plan(73);

-- Estrutura. O grão tem as três entidades, duas sempre nulas, e por isso não
-- cabe numa PK; o UNIQUE trata dois NULL como iguais (ADR-0009 §2).
SELECT hasnt_pk('normalizado', 'alcance_periodo', 'alcance_periodo não tem PK: o grão fica no UNIQUE');
SELECT results_eq(
  $$
  SELECT array_agg(a.attname ORDER BY k.ordem), i.indnullsnotdistinct
  FROM pg_catalog.pg_constraint AS c
  JOIN pg_catalog.pg_index AS i ON i.indexrelid = c.conindid
  CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k (attnum, ordem)
  JOIN pg_catalog.pg_attribute AS a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
  WHERE c.conname = 'alcance_periodo_grao_key' AND c.contype = 'u'
  GROUP BY i.indnullsnotdistinct
  $$,
  $$
  VALUES (
    ARRAY['empresa_id', 'conta_anuncio_id', 'campanha_id', 'anuncio_id', 'tipo_periodo', 'inicio_periodo']::name[],
    true
  )
  $$,
  'alcance_periodo tem UNIQUE NULLS NOT DISTINCT no grão'
);
SELECT fk_ok(
  'normalizado', 'alcance_periodo', ARRAY['empresa_id', coluna], 'normalizado', pai, ARRAY['empresa_id', 'id'],
  format('alcance_periodo.%s tem FK composta para %s', coluna, pai)
)
FROM (
  VALUES
    ('conta_anuncio_id', 'conta_anuncio'),
    ('campanha_id', 'campanha'),
    ('anuncio_id', 'anuncio'),
    ('execucao_id', 'execucao_carga')
) AS fk (coluna, pai);
SELECT fk_ok('normalizado', 'alcance_periodo', 'empresa_id', 'normalizado', 'empresa', 'id', 'alcance_periodo.empresa_id referencia empresa');
SELECT fk_ok(
  'normalizado', 'alcance_periodo', coluna, 'normalizado', 'calendario', 'data',
  format('alcance_periodo.%s referencia calendario', coluna)
)
FROM unnest(ARRAY['inicio_periodo', 'fim_periodo']) AS coluna;
-- Sem ações, nenhuma FK é ON DELETE CASCADE (ADR-0009 §1).
SELECT is_empty(
  $$
  SELECT conname FROM pg_catalog.pg_constraint
  WHERE conrelid = 'normalizado.alcance_periodo'::regclass AND contype = 'f' AND confdeltype <> 'a'
  $$,
  'toda FK de alcance_periodo é NO ACTION'
);
SELECT col_not_null('normalizado', 'alcance_periodo', coluna, format('alcance_periodo.%s é NOT NULL', coluna))
FROM unnest(ARRAY['empresa_id', 'tipo_periodo', 'inicio_periodo', 'fim_periodo', 'execucao_id']) AS coluna;
-- As entidades são anuláveis uma a uma, e o CHECK de num_nonnulls exige uma
-- só. Com MATCH SIMPLE, a FK de uma entidade nula não é conferida.
SELECT col_is_null('normalizado', 'alcance_periodo', coluna, format('alcance_periodo.%s é anulável', coluna))
FROM unnest(ARRAY['conta_anuncio_id', 'campanha_id', 'anuncio_id', 'alcance', 'impressoes']) AS coluna;
-- Métrica-base ausente é NULL, nunca zero (CLAUDE.md §5).
SELECT col_hasnt_default('normalizado', 'alcance_periodo', coluna, format('alcance_periodo.%s não tem DEFAULT', coluna))
FROM unnest(ARRAY['alcance', 'impressoes']) AS coluna;
SELECT col_type_is('normalizado', 'alcance_periodo', coluna, 'bigint', format('alcance_periodo.%s é bigint', coluna))
FROM unnest(ARRAY['alcance', 'impressoes']) AS coluna;

-- Uma hierarquia e uma execução por empresa, com id fixo: a da A termina em
-- a, e a da B, em b. Os IDs da Meta terminam em 1 na A e em 2 na B.
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
SELECT c.empresa_id, c.id, '12000000000000010' || v.sufixo, 'OUTCOME_AWARENESS', 'ACTIVE', x.id
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

-- Uma inclusão com a empresa (%1$L), o ID da Meta da conta (%2$L), da
-- campanha (%3$L) e do anúncio (%4$L), cada um nulo quando a linha não é
-- daquela entidade, o tipo de período (%5$L), o início (%6$L), o fim (%7$L),
-- o alcance (%8$s), as impressões (%9$s) e a execução (%10$L).
CREATE TEMPORARY TABLE modelo_insercao (sql text NOT NULL);
INSERT INTO modelo_insercao VALUES ($$
  INSERT INTO normalizado.alcance_periodo
    (empresa_id, conta_anuncio_id, campanha_id, anuncio_id, tipo_periodo, inicio_periodo, fim_periodo, alcance, impressoes, execucao_id)
  SELECT e.id,
    (SELECT id FROM normalizado.conta_anuncio WHERE id_meta = %2$L),
    (SELECT id FROM normalizado.campanha WHERE id_meta = %3$L),
    (SELECT id FROM normalizado.anuncio WHERE id_meta = %4$L),
    %5$L, %6$L, %7$L, %8$s, %9$s, %10$L
  FROM normalizado.empresa AS e WHERE e.nome = %1$L
$$);

-- Períodos aceitos: semana ISO de segunda a domingo, inclusive a que cruza o
-- ano; mês e ano de calendário; e os períodos em andamento, extraídos só até
-- o dia da extração (ADR-0006).
SELECT lives_ok(
  format(sql, 'Empresa Teste A', conta, campanha, anuncio, tipo_periodo, inicio, fim, '5000', '12000', '00000000-0000-4000-8000-00000000000a'),
  descricao
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    ('111111111111111', NULL, NULL, 'semana', '2026-03-02', '2026-03-08', 'semana da conta, de segunda a domingo, é aceita'),
    ('111111111111111', NULL, NULL, 'semana', '2025-12-29', '2026-01-04', 'semana ISO que cruza o ano é aceita'),
    ('111111111111111', NULL, NULL, 'semana', '2026-11-02', '2026-11-03', 'semana em andamento, até o dia da extração, é aceita'),
    (NULL, '120000000000000101', NULL, 'semana', '2026-03-02', '2026-03-08', 'a mesma semana da campanha é aceita'),
    (NULL, '120000000000000101', NULL, 'mes', '2026-03-01', '2026-03-31', 'mês da campanha é aceito'),
    (NULL, '120000000000000101', NULL, 'mes', '2026-02-01', '2026-02-28', 'mês de fevereiro é aceito'),
    (NULL, '120000000000000101', NULL, 'mes', '2026-11-01', '2026-11-03', 'mês em andamento é aceito'),
    (NULL, NULL, '120000000000000401', 'ano', '2025-01-01', '2025-12-31', 'ano do anúncio é aceito'),
    (NULL, NULL, '120000000000000401', 'ano', '2026-01-01', '2026-11-03', 'ano em andamento é aceito')
) AS caso (conta, campanha, anuncio, tipo_periodo, inicio, fim, descricao);
SELECT lives_ok(
  format(sql, 'Empresa Teste A', NULL, NULL, '120000000000000401', 'mes', '2026-03-01', '2026-03-31', 'NULL', 'NULL', '00000000-0000-4000-8000-00000000000a'),
  'linha com as medidas ausentes é aceita, com NULL (CLAUDE.md §5)'
)
FROM modelo_insercao;
SELECT results_eq(
  $$
  SELECT alcance, impressoes FROM normalizado.alcance_periodo
  WHERE anuncio_id IS NOT NULL AND tipo_periodo = 'mes'
  $$,
  $$VALUES (NULL::bigint, NULL::bigint)$$,
  'medidas ausentes ficam NULL, não zero'
);
SELECT lives_ok(
  format(sql, 'Empresa Teste B', '222222222222222', NULL, NULL, 'semana', '2026-03-02', '2026-03-08', '0', '0', '00000000-0000-4000-8000-00000000000b'),
  'semana da conta da B, com medidas zeradas, é aceita'
)
FROM modelo_insercao;

-- Grão único: uma segunda linha da mesma entidade, tipo e início é
-- recusada. Nas linhas de campanha e de anúncio, a conta nula conta como
-- igual.
SELECT throws_ok(
  format(sql, 'Empresa Teste A', conta, campanha, anuncio, tipo_periodo, inicio, fim, '1', '1', '00000000-0000-4000-8000-00000000000a'),
  '23505',
  'duplicate key value violates unique constraint "alcance_periodo_grao_key"',
  descricao
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    ('111111111111111', NULL, NULL, 'semana', '2026-03-02', '2026-03-08', 'segunda linha da mesma semana da conta é recusada'),
    (NULL, '120000000000000101', NULL, 'semana', '2026-03-02', '2026-03-07', 'segunda linha da mesma semana da campanha é recusada, mesmo com outro fim'),
    (NULL, '120000000000000101', NULL, 'mes', '2026-03-01', '2026-03-31', 'segunda linha do mesmo mês da campanha é recusada'),
    (NULL, NULL, '120000000000000401', 'ano', '2026-01-01', '2026-11-04', 'segunda linha do mesmo ano do anúncio é recusada')
) AS caso (conta, campanha, anuncio, tipo_periodo, inicio, fim, descricao);

-- Exatamente uma entidade por linha (ADR-0009 §2).
SELECT throws_ok(
  format(sql, 'Empresa Teste A', conta, campanha, anuncio, 'semana', '2026-03-09', '2026-03-15', '1', '1', '00000000-0000-4000-8000-00000000000a'),
  '23514',
  'new row for relation "alcance_periodo" violates check constraint "alcance_periodo_entidade_check"',
  descricao
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    (NULL, NULL, NULL, 'linha sem entidade é recusada'),
    ('111111111111111', '120000000000000101', NULL, 'linha com conta e campanha é recusada'),
    (NULL, '120000000000000101', '120000000000000401', 'linha com campanha e anúncio é recusada'),
    ('111111111111111', '120000000000000101', '120000000000000401', 'linha com as três entidades é recusada')
) AS caso (conta, campanha, anuncio, descricao);

-- Alinhamento dos períodos (ADR-0009 §2).
SELECT throws_ok(
  format(sql, 'Empresa Teste A', '111111111111111', NULL, NULL, tipo_periodo, inicio, fim, '1', '1', '00000000-0000-4000-8000-00000000000a'),
  '23514',
  format('new row for relation "alcance_periodo" violates check constraint "%s"', restricao),
  descricao
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    ('semana', '2026-03-03', '2026-03-09', 'alcance_periodo_semana_check', 'semana que começa numa terça-feira é recusada'),
    ('semana', '2026-03-08', '2026-03-14', 'alcance_periodo_semana_check', 'semana que começa num domingo é recusada'),
    ('semana', '2026-03-09', '2026-03-16', 'alcance_periodo_semana_check', 'semana de oito dias é recusada'),
    ('mes', '2026-03-02', '2026-03-31', 'alcance_periodo_mes_check', 'mês que não começa no dia 1 é recusado'),
    ('mes', '2026-03-01', '2026-04-01', 'alcance_periodo_mes_check', 'mês que termina no mês seguinte é recusado'),
    ('mes', '2026-03-01', '2027-03-31', 'alcance_periodo_mes_check', 'mês que termina no mesmo mês de outro ano é recusado'),
    ('ano', '2026-02-01', '2026-12-31', 'alcance_periodo_ano_check', 'ano que não começa em janeiro é recusado'),
    ('ano', '2026-01-02', '2026-12-31', 'alcance_periodo_ano_check', 'ano que não começa no dia 1 é recusado'),
    ('ano', '2026-01-01', '2027-01-01', 'alcance_periodo_ano_check', 'ano que termina no ano seguinte é recusado'),
    ('semana', '2026-03-09', '2026-03-08', 'alcance_periodo_fim_periodo_check', 'semana que termina antes de começar é recusada'),
    ('mes', '2026-04-01', '2026-03-31', 'alcance_periodo_fim_periodo_check', 'mês que termina antes de começar é recusado')
) AS caso (tipo_periodo, inicio, fim, restricao, descricao);

-- Tipo de período: domínio fechado, e NULL também é recusado, porque um
-- CHECK avaliado como NULL passa (ADR-0009 §1).
SELECT throws_ok(
  format(sql, 'Empresa Teste A', '111111111111111', NULL, NULL, tipo_periodo, '2026-03-09', '2026-03-15', '1', '1', '00000000-0000-4000-8000-00000000000a'),
  '23514',
  'new row for relation "alcance_periodo" violates check constraint "alcance_periodo_tipo_periodo_check"',
  format('tipo de período %L fora do domínio é recusado', tipo_periodo)
)
FROM modelo_insercao
CROSS JOIN unnest(ARRAY['dia', 'semana_iso', 'SEMANA', '']) AS tipo_periodo;
SELECT throws_ok(
  format(sql, 'Empresa Teste A', '111111111111111', NULL, NULL, NULL, '2026-03-09', '2026-03-15', '1', '1', '00000000-0000-4000-8000-00000000000a'),
  '23502', NULL, 'linha sem tipo de período é recusada'
)
FROM modelo_insercao;

-- Valores negativos são recusados em toda medida.
SELECT throws_ok(
  format(sql, 'Empresa Teste A', '111111111111111', NULL, NULL, 'semana', '2026-03-09', '2026-03-15', alcance, impressoes, '00000000-0000-4000-8000-00000000000a'),
  '23514',
  format('new row for relation "alcance_periodo" violates check constraint "alcance_periodo_%s_check"', coluna),
  format('alcance_periodo.%s negativo é recusado', coluna)
)
FROM modelo_insercao
CROSS JOIN (VALUES ('alcance', '-1', '1'), ('impressoes', '1', '-1')) AS caso (coluna, alcance, impressoes);

-- Início e fim no calendário, que vai de 2023 a 2035 (ADR-0009 §2).
SELECT throws_ok(
  format(sql, 'Empresa Teste A', '111111111111111', NULL, NULL, tipo_periodo, inicio, fim, '1', '1', '00000000-0000-4000-8000-00000000000a'),
  '23503',
  format('insert or update on table "alcance_periodo" violates foreign key constraint "%s"', restricao),
  descricao
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    ('ano', '2036-01-01', '2036-12-31', 'alcance_periodo_inicio_periodo_fkey', 'início fora do calendário é recusado'),
    ('semana', '2035-12-31', '2036-01-06', 'alcance_periodo_fim_periodo_fkey', 'fim fora do calendário é recusado')
) AS caso (tipo_periodo, inicio, fim, restricao, descricao);

-- Isolamento: nenhuma linha da empresa A aponta para conta, campanha,
-- anúncio ou execução da empresa B (ADR-0009 §1).
SELECT throws_ok(
  format(sql, 'Empresa Teste A', conta, campanha, anuncio, 'semana', '2026-03-09', '2026-03-15', '1', '1', execucao),
  '23503',
  format('insert or update on table "alcance_periodo" violates foreign key constraint "%s"', restricao),
  descricao
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    ('222222222222222', NULL, NULL, '00000000-0000-4000-8000-00000000000a', 'alcance_periodo_conta_anuncio_fkey', 'linha da empresa A não aponta para conta da empresa B'),
    (NULL, '120000000000000102', NULL, '00000000-0000-4000-8000-00000000000a', 'alcance_periodo_campanha_fkey', 'linha da empresa A não aponta para campanha da empresa B'),
    (NULL, NULL, '120000000000000402', '00000000-0000-4000-8000-00000000000a', 'alcance_periodo_anuncio_fkey', 'linha da empresa A não aponta para anúncio da empresa B'),
    ('111111111111111', NULL, NULL, '00000000-0000-4000-8000-00000000000b', 'alcance_periodo_execucao_carga_fkey', 'linha da empresa A não aponta para execução da empresa B')
) AS caso (conta, campanha, anuncio, execucao, restricao, descricao);

-- Exclusão: a entidade com alcance não sai (NO ACTION).
SELECT throws_ok(
  $$DELETE FROM normalizado.anuncio WHERE id_meta = '120000000000000401'$$,
  '23503', NULL,
  'anúncio com alcance por período não é apagado'
);

-- Privilégios da etl_carga (ADR-0009 §3): a substituição dos períodos apaga
-- e inclui, sem UPDATE. Cada privilégio é conferido sozinho, porque
-- has_table_privilege com uma lista devolve verdadeiro se o papel tiver
-- qualquer um deles.
SELECT is(
  ARRAY(
    SELECT privilegio
    FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN']) AS privilegio
    WHERE has_table_privilege('etl_carga', 'normalizado.alcance_periodo', privilegio)
       OR (privilegio IN ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES')
           AND has_any_column_privilege('etl_carga', 'normalizado.alcance_periodo', privilegio))
  ),
  ARRAY['SELECT', 'INSERT', 'DELETE'],
  'etl_carga tem só SELECT, INSERT, DELETE em alcance_periodo'
);
SELECT policies_are('normalizado', 'alcance_periodo', ARRAY['etl_carga_acessa'], 'alcance_periodo tem só a política da etl_carga');

-- Como etl_carga, as funções do pgTAP não ficam acessíveis: o resultado é
-- guardado num parâmetro da transação e conferido nas próprias linhas,
-- depois de voltar ao postgres.
SET LOCAL ROLE etl_carga;
DO $$
BEGIN
  DELETE FROM normalizado.alcance_periodo
  WHERE execucao_id = '00000000-0000-4000-8000-00000000000b';
  INSERT INTO normalizado.alcance_periodo (empresa_id, conta_anuncio_id, tipo_periodo, inicio_periodo, fim_periodo, alcance, impressoes, execucao_id)
  SELECT empresa_id, id, 'mes', '2026-03-01', '2026-03-31', 4200, 9800, '00000000-0000-4000-8000-00000000000b'
  FROM normalizado.conta_anuncio WHERE id_meta = '222222222222222';
  PERFORM set_config('alcance_periodo_test.etl', 'aceito', true);
EXCEPTION WHEN OTHERS THEN
  PERFORM set_config('alcance_periodo_test.etl', SQLSTATE, true);
END
$$;
RESET ROLE;
SELECT is(current_setting('alcance_periodo_test.etl'), 'aceito', 'etl_carga substitui o alcance por período sem erro');
SELECT results_eq(
  $$
  SELECT tipo_periodo, inicio_periodo, fim_periodo, alcance, impressoes
  FROM normalizado.alcance_periodo
  WHERE execucao_id = '00000000-0000-4000-8000-00000000000b'
  $$,
  $$VALUES ('mes', '2026-03-01'::date, '2026-03-31'::date, 4200::bigint, 9800::bigint)$$,
  'a substituição da etl_carga deixa só a linha nova'
);

SELECT * FROM finish();
ROLLBACK;
