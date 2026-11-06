-- Prova os índices que a resolução do resultado de cada campanha usa para ir
-- da campanha aos conjuntos e do conjunto aos anúncios. Sem eles, o tempo cresce
-- com conjuntos × anúncios (RNF-06; ADR-0009 §4).
BEGIN;
SELECT plan(4);

SELECT has_index(
  'normalizado', 'anuncio', 'anuncio_empresa_id_conjunto_anuncio_id_idx',
  ARRAY['empresa_id', 'conjunto_anuncio_id'],
  'anuncio tem índice por empresa e conjunto'
);
SELECT has_index(
  'normalizado', 'conjunto_anuncio', 'conjunto_anuncio_empresa_id_campanha_id_idx',
  ARRAY['empresa_id', 'campanha_id'],
  'conjunto_anuncio tem índice por empresa e campanha'
);

-- A prova pelo plano, com volume suficiente para o planejador preferir o índice:
-- uma campanha com um conjunto e muitos anúncios em outro.
INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste Índices');
INSERT INTO normalizado.execucao_carga (empresa_id, tipo)
SELECT id, 'diaria' FROM normalizado.empresa WHERE nome = 'Empresa Teste Índices';
INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, execucao_id)
SELECT empresa_id, '599999999999991', id FROM normalizado.execucao_carga
WHERE empresa_id = (SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Teste Índices');
INSERT INTO normalizado.criativo (empresa_id, conta_anuncio_id, id_meta, execucao_id)
SELECT empresa_id, id, '599999999999992', execucao_id FROM normalizado.conta_anuncio WHERE id_meta = '599999999999991';
INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, objetivo, status, execucao_id)
SELECT c.empresa_id, c.id, (598000000000000 + g)::text, 'OUTCOME_SALES', 'ACTIVE', c.execucao_id
FROM normalizado.conta_anuncio AS c, generate_series(1, 200) AS g
WHERE c.id_meta = '599999999999991';
INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, status, execucao_id)
SELECT c.empresa_id, c.id, (597000000000000 + (c.id_meta::bigint % 100000) * 10 + g)::text, 'ACTIVE', c.execucao_id
FROM normalizado.campanha AS c, generate_series(1, 3) AS g
WHERE c.id_meta LIKE '598%';
INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, status, execucao_id)
SELECT j.empresa_id, j.id, k.id, (596000000000000 + row_number() OVER ())::text, 'ACTIVE', j.execucao_id
FROM normalizado.conjunto_anuncio AS j
JOIN normalizado.criativo AS k ON k.id_meta = '599999999999992'
CROSS JOIN generate_series(1, 3)
WHERE j.id_meta LIKE '597%';
ANALYZE normalizado.conjunto_anuncio;
ANALYZE normalizado.anuncio;

CREATE FUNCTION pg_temp.plano(p_consulta text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE
  linha text;
  plano text := '';
BEGIN
  FOR linha IN EXECUTE 'EXPLAIN ' || p_consulta LOOP
    plano := plano || linha || E'\n';
  END LOOP;
  RETURN plano;
END
$$;

SELECT matches(
  pg_temp.plano(format(
    $$ SELECT id FROM normalizado.anuncio WHERE empresa_id = %L AND conjunto_anuncio_id = %L $$,
    j.empresa_id, j.id
  )),
  'anuncio_empresa_id_conjunto_anuncio_id_idx',
  'os anúncios de um conjunto são lidos pelo índice'
)
FROM normalizado.conjunto_anuncio AS j WHERE j.id_meta LIKE '597%' LIMIT 1;
SELECT matches(
  pg_temp.plano(format(
    $$ SELECT id FROM normalizado.conjunto_anuncio WHERE empresa_id = %L AND campanha_id = %L $$,
    c.empresa_id, c.id
  )),
  'conjunto_anuncio_empresa_id_campanha_id_idx',
  'os conjuntos de uma campanha são lidos pelo índice'
)
FROM normalizado.campanha AS c WHERE c.id_meta LIKE '598%' LIMIT 1;

SELECT * FROM finish();
ROLLBACK;
