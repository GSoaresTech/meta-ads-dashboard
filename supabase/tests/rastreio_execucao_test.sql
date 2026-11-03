-- Prova o rastreio da execução: a conta e as entidades da Meta guardam a
-- última execução que gravou a linha, sem apontar para execução de outra
-- empresa (RF-09; ADR-0009 §1, Rastreio).
BEGIN;
SELECT plan(38);

CREATE TEMPORARY TABLE tabela_rastreada (tabela text PRIMARY KEY);
INSERT INTO tabela_rastreada VALUES
  ('conta_anuncio'), ('pagina'), ('campanha'), ('conjunto_anuncio'),
  ('janela_atribuicao_conjunto'), ('criativo'), ('anuncio');

SELECT col_type_is('normalizado', tabela, 'execucao_id', 'uuid', format('%s.execucao_id é uuid', tabela))
FROM tabela_rastreada;
SELECT fk_ok(
  'normalizado', tabela, ARRAY['empresa_id', 'execucao_id'], 'normalizado', 'execucao_carga', ARRAY['empresa_id', 'id'],
  format('%s.execucao_id tem FK composta para execucao_carga', tabela)
)
FROM tabela_rastreada;
-- Só a ETL grava entidades, sempre numa execução. A conta nasce no cadastro
-- (RF-43) e fica sem execução até a primeira extração.
SELECT col_not_null('normalizado', tabela, 'execucao_id', format('%s.execucao_id é NOT NULL', tabela))
FROM tabela_rastreada WHERE tabela <> 'conta_anuncio';
SELECT col_is_null('normalizado', 'conta_anuncio', 'execucao_id', 'conta_anuncio.execucao_id é nulo até a primeira extração');

-- Uma conta e uma execução por empresa, com id fixo: a da A termina em a, e a
-- da B, em b.
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

SELECT is(
  (SELECT execucao_id FROM normalizado.conta_anuncio WHERE id_meta = '111111111111111'),
  NULL,
  'a conta cadastrada nasce sem execução'
);

-- A hierarquia da empresa A, gravada pela execução da A.
SELECT lives_ok(
  $$
  INSERT INTO normalizado.pagina (empresa_id, id_meta, execucao_id)
  SELECT id, '300000000000001', '00000000-0000-4000-8000-00000000000a' FROM normalizado.empresa WHERE nome = 'Empresa Teste A';
  INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, objetivo, status, execucao_id)
  SELECT empresa_id, id, '120000000000000101', 'OUTCOME_SALES', 'ACTIVE', '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.conta_anuncio WHERE id_meta = '111111111111111';
  INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, status, execucao_id)
  SELECT empresa_id, id, '120000000000000201', 'ACTIVE', '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.campanha WHERE id_meta = '120000000000000101';
  INSERT INTO normalizado.janela_atribuicao_conjunto (empresa_id, conjunto_anuncio_id, tipo_evento, janela_dias, execucao_id)
  SELECT empresa_id, id, 'CLICK_THROUGH', 7, '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.conjunto_anuncio WHERE id_meta = '120000000000000201';
  INSERT INTO normalizado.criativo (empresa_id, conta_anuncio_id, id_meta, execucao_id)
  SELECT empresa_id, id, '120000000000000301', '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.conta_anuncio WHERE id_meta = '111111111111111';
  INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, status, execucao_id)
  SELECT j.empresa_id, j.id, k.id, '120000000000000401', 'ACTIVE', '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.conjunto_anuncio AS j, normalizado.criativo AS k
  WHERE j.id_meta = '120000000000000201' AND k.id_meta = '120000000000000301';
  $$,
  'entidades gravadas pela execução da própria empresa são aceitas'
);

-- Isolamento: nenhuma linha da empresa A aponta para a execução da empresa B.
SELECT throws_ok(
  format(
    $$
    UPDATE normalizado.%1$I SET execucao_id = '00000000-0000-4000-8000-00000000000b'
    WHERE empresa_id = (SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Teste A')
    $$,
    tabela
  ),
  '23503',
  format('insert or update on table "%1$s" violates foreign key constraint "%1$s_execucao_carga_fkey"', tabela),
  format('%s da empresa A não aponta para execução da empresa B', tabela)
)
FROM tabela_rastreada;
SELECT throws_ok(
  format(
    $$
    UPDATE normalizado.%1$I SET execucao_id = NULL
    WHERE empresa_id = (SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Teste A')
    $$,
    tabela
  ),
  '23502',
  format('null value in column "execucao_id" of relation "%s" violates not-null constraint', tabela),
  format('%s sem execução é recusada', tabela)
)
FROM tabela_rastreada WHERE tabela <> 'conta_anuncio';

-- A etl_carga marca a conta com a execução que a extraiu (ADR-0009 §3).
-- Como etl_carga, as funções do pgTAP não ficam acessíveis: o resultado é
-- guardado num parâmetro da transação e conferido na própria linha, depois
-- de voltar ao postgres.
SET LOCAL ROLE etl_carga;
DO $$
BEGIN
  UPDATE normalizado.conta_anuncio
  SET execucao_id = '00000000-0000-4000-8000-00000000000a', nome = 'Conta Teste',
    fuso_horario = 'America/Sao_Paulo', moeda = 'BRL', atualizado_em = now()
  WHERE id_meta = '111111111111111';
  PERFORM set_config('rastreio_execucao_test.etl', 'aceito', true);
EXCEPTION WHEN OTHERS THEN
  PERFORM set_config('rastreio_execucao_test.etl', SQLSTATE, true);
END
$$;
RESET ROLE;
SELECT is(current_setting('rastreio_execucao_test.etl'), 'aceito', 'etl_carga atualiza a conta sem erro');
SELECT is(
  (SELECT execucao_id FROM normalizado.conta_anuncio WHERE id_meta = '111111111111111'),
  '00000000-0000-4000-8000-00000000000a'::uuid,
  'etl_carga grava na conta a execução que a extraiu'
);

SELECT * FROM finish();
ROLLBACK;
