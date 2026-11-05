-- Prova a sobrescrita do resultado principal por campanha: uma linha por
-- campanha, com resultado e KPI do catálogo de métricas, presa à campanha da
-- mesma empresa e só lida pela ETL (RF-49; ADR-0007; ADR-0009 §1, §2 e §3).
BEGIN;
SELECT plan(21);

-- Estrutura
SELECT has_table('normalizado', 'sobrescrita_resultado_campanha', 'a tabela sobrescrita_resultado_campanha existe');
SELECT col_is_pk(
  'normalizado', 'sobrescrita_resultado_campanha', ARRAY['empresa_id', 'campanha_id'],
  'sobrescrita_resultado_campanha tem PK (empresa_id, campanha_id), uma linha por campanha'
);
SELECT fk_ok(
  'normalizado', 'sobrescrita_resultado_campanha', ARRAY['empresa_id', 'campanha_id'],
  'normalizado', 'campanha', ARRAY['empresa_id', 'id'],
  'sobrescrita_resultado_campanha.campanha_id tem FK composta para campanha'
);
SELECT fk_ok(
  'normalizado', 'sobrescrita_resultado_campanha', 'empresa_id', 'normalizado', 'empresa', 'id',
  'sobrescrita_resultado_campanha.empresa_id referencia empresa'
);
SELECT fk_ok(
  'normalizado', 'sobrescrita_resultado_campanha', coluna, 'normalizado', 'metrica', 'codigo',
  format('sobrescrita_resultado_campanha.%s referencia o catálogo de métricas', coluna)
)
FROM unnest(ARRAY['metrica_resultado', 'metrica_kpi']) AS coluna;
-- A sobrescrita define os dois: uma linha sem um deles não diria o que
-- exibir no lugar do catálogo.
SELECT col_not_null('normalizado', 'sobrescrita_resultado_campanha', coluna, format('sobrescrita_resultado_campanha.%s é NOT NULL', coluna))
FROM unnest(ARRAY['empresa_id', 'campanha_id', 'metrica_resultado', 'metrica_kpi', 'criado_em', 'atualizado_em']) AS coluna;

-- Uma campanha por empresa. A da A é 120000000000000201, e a da B,
-- 120000000000000202.
INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A'), ('Empresa Teste B');
INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)
SELECT id, CASE nome WHEN 'Empresa Teste A' THEN '111111111111111' ELSE '222222222222222' END
FROM normalizado.empresa
WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');
INSERT INTO normalizado.execucao_carga (empresa_id, tipo)
SELECT id, 'diaria' FROM normalizado.empresa WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');
INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, objetivo, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, 'OUTCOME_ENGAGEMENT', 'ACTIVE', x.id
FROM normalizado.conta_anuncio AS c
JOIN normalizado.execucao_carga AS x USING (empresa_id)
JOIN (
  VALUES ('111111111111111', '120000000000000201'), ('222222222222222', '120000000000000202')
) AS v (conta, id_meta) ON v.conta = c.id_meta;

-- A inclusão da sobrescrita com a empresa de %1$L, a campanha %2$L e as
-- métricas %3$L e %4$L.
CREATE TEMPORARY TABLE modelo_insercao (sql text NOT NULL);
INSERT INTO modelo_insercao VALUES ($$
  INSERT INTO normalizado.sobrescrita_resultado_campanha (empresa_id, campanha_id, metrica_resultado, metrica_kpi)
  SELECT e.id, c.id, %3$L, %4$L
  FROM normalizado.empresa AS e
  CROSS JOIN normalizado.campanha AS c
  WHERE e.nome = %1$L AND c.id_meta = %2$L
$$);

SELECT lives_ok(
  format(sql, 'Empresa Teste A', '120000000000000201', 'conversas_iniciadas', 'custo_conversa'),
  'sobrescrita da campanha com métricas do catálogo é aceita'
)
FROM modelo_insercao;
SELECT throws_ok(
  format(sql, 'Empresa Teste A', '120000000000000201', 'cadastros', 'custo_cadastro'),
  '23505',
  NULL,
  'segunda sobrescrita da mesma campanha é recusada: a campanha tem uma só'
)
FROM modelo_insercao;
SELECT throws_ok(
  format(sql, 'Empresa Teste A', '120000000000000202', 'cadastros', 'custo_cadastro'),
  '23503',
  NULL,
  'sobrescrita que aponta para campanha de outra empresa é recusada'
)
FROM modelo_insercao;
SELECT throws_ok(
  format(sql, 'Empresa Teste B', '120000000000000202', resultado, kpi),
  '23503',
  NULL,
  descricao
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    ('metrica_inexistente', 'custo_cadastro', 'resultado fora do catálogo de métricas é recusado'),
    ('cadastros', 'metrica_inexistente', 'KPI fora do catálogo de métricas é recusado')
) AS caso (resultado, kpi, descricao);
SELECT throws_ok(
  format(sql, 'Empresa Teste B', '120000000000000202', resultado, kpi),
  '23502',
  NULL,
  descricao
)
FROM modelo_insercao
CROSS JOIN (
  VALUES
    (NULL, 'custo_cadastro', 'sobrescrita sem resultado é recusada'),
    ('cadastros', NULL, 'sobrescrita sem KPI é recusada')
) AS caso (resultado, kpi, descricao);

-- A ETL lê a sobrescrita para resolver o resultado (RF-15, RF-16); a escrita
-- é da área do operador, pelas funções de analitico (ADR-0009 §3 e §4).
SELECT ok(
  has_table_privilege('etl_carga', 'normalizado.sobrescrita_resultado_campanha', 'SELECT')
    AND NOT has_table_privilege(
      'etl_carga', 'normalizado.sobrescrita_resultado_campanha',
      'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN'
    ),
  'etl_carga tem só SELECT em sobrescrita_resultado_campanha'
);

-- A leitura passa pela política do RLS. Como etl_carga, as funções do pgTAP
-- não ficam acessíveis: a contagem é guardada num parâmetro da transação.
SET LOCAL ROLE etl_carga;
SELECT set_config(
  'sobrescrita_resultado_campanha_test.linhas_etl_carga',
  (SELECT count(*) FROM normalizado.sobrescrita_resultado_campanha)::text,
  true
);
RESET ROLE;
SELECT is(
  current_setting('sobrescrita_resultado_campanha_test.linhas_etl_carga')::bigint,
  1::bigint,
  'etl_carga lê a sobrescrita gravada'
);

SELECT * FROM finish();
ROLLBACK;
