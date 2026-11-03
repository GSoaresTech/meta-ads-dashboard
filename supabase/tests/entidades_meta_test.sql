-- Prova as entidades da Meta: a hierarquia campanha → conjunto → anúncio →
-- criativo, as chaves que impedem apontar para outra empresa e os domínios
-- (RF-01; ADR-0009 §1, §2 e §3; R-35).
BEGIN;
SELECT plan(170);

-- Estrutura
SELECT col_is_pk('normalizado', tabela, 'id', format('id é a PK de %s', tabela))
FROM unnest(ARRAY['pagina', 'campanha', 'conjunto_anuncio', 'criativo', 'anuncio']) AS tabela;
SELECT col_default_is('normalizado', tabela, 'id', 'gen_random_uuid()', format('id de %s vem de gen_random_uuid()', tabela))
FROM unnest(ARRAY['pagina', 'campanha', 'conjunto_anuncio', 'criativo', 'anuncio']) AS tabela;
SELECT col_type_is('normalizado', tabela, 'id_meta', 'text', format('id_meta de %s é text, nunca número (CLAUDE.md §5)', tabela))
FROM unnest(ARRAY['pagina', 'campanha', 'conjunto_anuncio', 'criativo', 'anuncio']) AS tabela;
SELECT col_is_unique('normalizado', tabela, ARRAY['empresa_id', 'id'], format('%s tem UNIQUE (empresa_id, id), alvo das FKs compostas', tabela))
FROM unnest(ARRAY['pagina', 'campanha', 'conjunto_anuncio', 'criativo', 'anuncio']) AS tabela;
SELECT col_is_pk(
  'normalizado', 'janela_atribuicao_conjunto', ARRAY['empresa_id', 'conjunto_anuncio_id', 'tipo_evento'],
  'janela_atribuicao_conjunto tem PK (empresa_id, conjunto_anuncio_id, tipo_evento)'
);
SELECT fk_ok('normalizado', filha, ARRAY['empresa_id', coluna], 'normalizado', pai, ARRAY['empresa_id', 'id'], format('%s.%s tem FK composta para %s', filha, coluna, pai))
FROM (
  VALUES
    ('campanha', 'conta_anuncio_id', 'conta_anuncio'),
    ('conjunto_anuncio', 'campanha_id', 'campanha'),
    ('janela_atribuicao_conjunto', 'conjunto_anuncio_id', 'conjunto_anuncio'),
    ('criativo', 'conta_anuncio_id', 'conta_anuncio'),
    ('criativo', 'pagina_id', 'pagina'),
    ('anuncio', 'conjunto_anuncio_id', 'conjunto_anuncio'),
    ('anuncio', 'criativo_id', 'criativo')
) AS fk (filha, coluna, pai);
SELECT fk_ok('normalizado', tabela, 'empresa_id', 'normalizado', 'empresa', 'id', format('%s.empresa_id referencia empresa', tabela))
FROM unnest(ARRAY['pagina', 'campanha', 'conjunto_anuncio', 'janela_atribuicao_conjunto', 'criativo', 'anuncio']) AS tabela;
-- As FKs são MATCH SIMPLE: um pai nulo dispensaria a conferência e deixaria a
-- entidade órfã (RF-01). Só a Página do criativo é opcional.
SELECT col_not_null('normalizado', tabela, coluna, format('%s.%s é NOT NULL', tabela, coluna))
FROM (
  VALUES
    ('campanha', 'conta_anuncio_id'),
    ('conjunto_anuncio', 'campanha_id'),
    ('janela_atribuicao_conjunto', 'conjunto_anuncio_id'),
    ('criativo', 'conta_anuncio_id'),
    ('anuncio', 'conjunto_anuncio_id'),
    ('anuncio', 'criativo_id')
) AS fk (tabela, coluna);
SELECT col_is_null('normalizado', 'criativo', 'pagina_id', 'criativo.pagina_id é opcional');

-- Uma inclusão válida por tabela, com o id_meta (%1$L), a empresa (%2$L) e o
-- status (%3$L) como parâmetros. Cada empresa tem um só pai de cada tipo até
-- o fim dos testes que usam estes modelos, e uma só execução.
CREATE TEMPORARY TABLE modelo_insercao (tabela text PRIMARY KEY, sql text NOT NULL);
INSERT INTO modelo_insercao VALUES
  ('pagina', $$
    INSERT INTO normalizado.pagina (empresa_id, id_meta, nome, execucao_id)
    SELECT e.id, %1$L, 'Página Teste', x.id
    FROM normalizado.empresa AS e JOIN normalizado.execucao_carga AS x ON x.empresa_id = e.id
    WHERE e.nome = %2$L
  $$),
  ('campanha', $$
    INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, nome, objetivo, status, execucao_id)
    SELECT p.empresa_id, p.id, %1$L, 'Campanha Teste', 'OUTCOME_SALES', %3$L, x.id
    FROM normalizado.conta_anuncio AS p JOIN normalizado.empresa AS e ON e.id = p.empresa_id
    JOIN normalizado.execucao_carga AS x ON x.empresa_id = e.id
    WHERE e.nome = %2$L
  $$),
  ('conjunto_anuncio', $$
    INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, nome, status, execucao_id)
    SELECT p.empresa_id, p.id, %1$L, 'Conjunto Teste', %3$L, x.id
    FROM normalizado.campanha AS p JOIN normalizado.empresa AS e ON e.id = p.empresa_id
    JOIN normalizado.execucao_carga AS x ON x.empresa_id = e.id
    WHERE e.nome = %2$L
  $$),
  ('criativo', $$
    INSERT INTO normalizado.criativo (empresa_id, conta_anuncio_id, id_meta, execucao_id)
    SELECT p.empresa_id, p.id, %1$L, x.id
    FROM normalizado.conta_anuncio AS p JOIN normalizado.empresa AS e ON e.id = p.empresa_id
    JOIN normalizado.execucao_carga AS x ON x.empresa_id = e.id
    WHERE e.nome = %2$L
  $$),
  ('anuncio', $$
    INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, nome, status, execucao_id)
    SELECT p.empresa_id, p.id, k.id, %1$L, 'Anúncio Teste', %3$L, x.id
    FROM normalizado.conjunto_anuncio AS p
    JOIN normalizado.criativo AS k ON k.empresa_id = p.empresa_id
    JOIN normalizado.empresa AS e ON e.id = p.empresa_id
    JOIN normalizado.execucao_carga AS x ON x.empresa_id = e.id
    WHERE e.nome = %2$L
  $$);

INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A'), ('Empresa Teste B');
INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta)
SELECT id, CASE nome WHEN 'Empresa Teste A' THEN '111111111111111' ELSE '222222222222222' END
FROM normalizado.empresa
WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');
-- A execução que grava as entidades de cada empresa, com id fixo: a da A
-- termina em a, e a da B, em b (ADR-0009 §1, Rastreio).
INSERT INTO normalizado.execucao_carga (id, empresa_id, tipo)
SELECT CASE nome WHEN 'Empresa Teste A' THEN '00000000-0000-4000-8000-00000000000a' ELSE '00000000-0000-4000-8000-00000000000b' END::uuid,
  id, 'diaria'
FROM normalizado.empresa
WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');

-- A hierarquia de cada empresa, de cima para baixo. O sufixo 1 é da empresa A,
-- e o 2, da B.
SELECT lives_ok(
  format(m.sql, ids.id_meta, ids.empresa, 'ACTIVE'),
  format('%s da %s é aceito', m.tabela, ids.empresa)
)
FROM modelo_insercao AS m
JOIN (
  VALUES
    ('pagina', '300000000000001', 'Empresa Teste A'),
    ('pagina', '300000000000002', 'Empresa Teste B')
) AS ids (tabela, id_meta, empresa) USING (tabela);
SELECT lives_ok(
  format(m.sql, ids.id_meta, ids.empresa, 'ACTIVE'),
  format('%s da %s é aceito', m.tabela, ids.empresa)
)
FROM modelo_insercao AS m
JOIN (
  VALUES
    ('campanha', '120000000000000101', 'Empresa Teste A'),
    ('campanha', '120000000000000102', 'Empresa Teste B')
) AS ids (tabela, id_meta, empresa) USING (tabela);
SELECT lives_ok(
  format(m.sql, ids.id_meta, ids.empresa, 'ACTIVE'),
  format('%s da %s é aceito', m.tabela, ids.empresa)
)
FROM modelo_insercao AS m
JOIN (
  VALUES
    ('conjunto_anuncio', '120000000000000201', 'Empresa Teste A'),
    ('conjunto_anuncio', '120000000000000202', 'Empresa Teste B'),
    ('criativo', '120000000000000301', 'Empresa Teste A'),
    ('criativo', '120000000000000302', 'Empresa Teste B')
) AS ids (tabela, id_meta, empresa) USING (tabela);
SELECT lives_ok(
  format(m.sql, ids.id_meta, ids.empresa, 'ACTIVE'),
  format('%s da %s é aceito', m.tabela, ids.empresa)
)
FROM modelo_insercao AS m
JOIN (
  VALUES
    ('anuncio', '120000000000000401', 'Empresa Teste A'),
    ('anuncio', '120000000000000402', 'Empresa Teste B')
) AS ids (tabela, id_meta, empresa) USING (tabela);

-- Isolamento: uma linha da empresa A não aponta para um pai da empresa B
-- (ADR-0009 §1).
SELECT throws_ok(
  $$
  INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, objetivo, status, execucao_id)
  SELECT e.id, p.id, '120000000000000199', 'OUTCOME_SALES', 'ACTIVE', '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.empresa AS e, normalizado.conta_anuncio AS p
  WHERE e.nome = 'Empresa Teste A' AND p.id_meta = '222222222222222'
  $$,
  '23503',
  'insert or update on table "campanha" violates foreign key constraint "campanha_conta_anuncio_fkey"',
  'campanha da empresa A não aponta para conta da empresa B'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, status, execucao_id)
  SELECT e.id, p.id, '120000000000000299', 'ACTIVE', '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.empresa AS e, normalizado.campanha AS p
  WHERE e.nome = 'Empresa Teste A' AND p.id_meta = '120000000000000102'
  $$,
  '23503',
  'insert or update on table "conjunto_anuncio" violates foreign key constraint "conjunto_anuncio_campanha_fkey"',
  'conjunto da empresa A não aponta para campanha da empresa B'
);
SELECT throws_ok(
  $$
  UPDATE normalizado.conjunto_anuncio
  SET campanha_id = (SELECT id FROM normalizado.campanha WHERE id_meta = '120000000000000102')
  WHERE id_meta = '120000000000000201'
  $$,
  '23503',
  'insert or update on table "conjunto_anuncio" violates foreign key constraint "conjunto_anuncio_campanha_fkey"',
  'conjunto da empresa A não passa a apontar para campanha da empresa B'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.janela_atribuicao_conjunto (empresa_id, conjunto_anuncio_id, tipo_evento, janela_dias, execucao_id)
  SELECT e.id, p.id, 'CLICK_THROUGH', 7, '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.empresa AS e, normalizado.conjunto_anuncio AS p
  WHERE e.nome = 'Empresa Teste A' AND p.id_meta = '120000000000000202'
  $$,
  '23503',
  'insert or update on table "janela_atribuicao_conjunto" violates foreign key constraint "janela_atribuicao_conjunto_conjunto_anuncio_fkey"',
  'janela de atribuição da empresa A não aponta para conjunto da empresa B'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.criativo (empresa_id, conta_anuncio_id, id_meta, execucao_id)
  SELECT e.id, p.id, '120000000000000399', '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.empresa AS e, normalizado.conta_anuncio AS p
  WHERE e.nome = 'Empresa Teste A' AND p.id_meta = '222222222222222'
  $$,
  '23503',
  'insert or update on table "criativo" violates foreign key constraint "criativo_conta_anuncio_fkey"',
  'criativo da empresa A não aponta para conta da empresa B'
);
SELECT lives_ok(
  $$
  UPDATE normalizado.criativo
  SET pagina_id = (
    SELECT p.id FROM normalizado.pagina AS p
    JOIN normalizado.empresa AS e ON e.id = p.empresa_id
    WHERE e.nome = 'Empresa Teste A'
  )
  WHERE id_meta = '120000000000000301'
  $$,
  'criativo da empresa A aponta para Página da empresa A'
);
SELECT throws_ok(
  $$
  UPDATE normalizado.criativo
  SET pagina_id = (
    SELECT p.id FROM normalizado.pagina AS p
    JOIN normalizado.empresa AS e ON e.id = p.empresa_id
    WHERE e.nome = 'Empresa Teste B'
  )
  WHERE id_meta = '120000000000000301'
  $$,
  '23503',
  'insert or update on table "criativo" violates foreign key constraint "criativo_pagina_fkey"',
  'criativo da empresa A não aponta para Página da empresa B'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, status, execucao_id)
  SELECT e.id, p.id, k.id, '120000000000000499', 'ACTIVE', '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.empresa AS e, normalizado.conjunto_anuncio AS p, normalizado.criativo AS k
  WHERE e.nome = 'Empresa Teste A' AND p.id_meta = '120000000000000202' AND k.id_meta = '120000000000000301'
  $$,
  '23503',
  'insert or update on table "anuncio" violates foreign key constraint "anuncio_conjunto_anuncio_fkey"',
  'anúncio da empresa A não aponta para conjunto da empresa B'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, status, execucao_id)
  SELECT e.id, p.id, k.id, '120000000000000499', 'ACTIVE', '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.empresa AS e, normalizado.conjunto_anuncio AS p, normalizado.criativo AS k
  WHERE e.nome = 'Empresa Teste A' AND p.id_meta = '120000000000000201' AND k.id_meta = '120000000000000302'
  $$,
  '23503',
  'insert or update on table "anuncio" violates foreign key constraint "anuncio_criativo_fkey"',
  'anúncio da empresa A não aponta para criativo da empresa B'
);
SELECT throws_ok(
  $$
  UPDATE normalizado.anuncio
  SET criativo_id = (SELECT id FROM normalizado.criativo WHERE id_meta = '120000000000000302')
  WHERE id_meta = '120000000000000401'
  $$,
  '23503',
  'insert or update on table "anuncio" violates foreign key constraint "anuncio_criativo_fkey"',
  'anúncio da empresa A não passa a apontar para criativo da empresa B'
);

-- id_meta duplicado: o UNIQUE é global, salvo em pagina (ADR-0009 §1).
SELECT throws_ok(
  format(m.sql, ids.id_meta, empresa, 'ACTIVE'),
  '23505',
  format('duplicate key value violates unique constraint "%s_id_meta_key"', m.tabela),
  format('id_meta duplicado de %s é recusado na %s', m.tabela, empresa)
)
FROM modelo_insercao AS m
JOIN (
  VALUES
    ('campanha', '120000000000000101'),
    ('conjunto_anuncio', '120000000000000201'),
    ('criativo', '120000000000000301'),
    ('anuncio', '120000000000000401')
) AS ids (tabela, id_meta) USING (tabela)
CROSS JOIN unnest(ARRAY['Empresa Teste A', 'Empresa Teste B']) AS empresa;
SELECT throws_ok(
  format(sql, '300000000000001', 'Empresa Teste A'),
  '23505',
  'duplicate key value violates unique constraint "pagina_empresa_id_id_meta_key"',
  'id_meta de Página duplicado na mesma empresa é recusado'
)
FROM modelo_insercao WHERE tabela = 'pagina';
SELECT lives_ok(
  format(sql, '300000000000001', 'Empresa Teste B'),
  'a mesma Página é aceita em outra empresa'
)
FROM modelo_insercao WHERE tabela = 'pagina';

-- id_meta não numérico (R-35), inclusive com prefixo, como o act_ da conta.
SELECT throws_ok(
  format(m.sql, id_meta, 'Empresa Teste A', 'ACTIVE'),
  '23514',
  format('new row for relation "%s" violates check constraint "%s_id_meta_check"', m.tabela, m.tabela),
  format('id_meta não numérico %L é recusado em %s', id_meta, m.tabela)
)
FROM modelo_insercao AS m
CROSS JOIN unnest(ARRAY['act_120000000000000999', '12000000000000099a', ' 120000000000000999', '']) AS id_meta;

-- Status: domínio fechado (R-35), e NULL também é recusado, porque um CHECK
-- avaliado como NULL passa (ADR-0009 §1).
SELECT throws_ok(
  format(m.sql, '120000000000000999', 'Empresa Teste A', status),
  '23514',
  format('new row for relation "%s" violates check constraint "%s_status_check"', m.tabela, m.tabela),
  format('status %L fora do domínio é recusado em %s', status, m.tabela)
)
FROM modelo_insercao AS m
CROSS JOIN unnest(ARRAY['active', 'ATIVO', 'IN_PROCESS', 'WITH_ISSUES']) AS status
WHERE m.tabela IN ('campanha', 'conjunto_anuncio', 'anuncio');
SELECT throws_ok(
  format(m.sql, '120000000000000999', 'Empresa Teste A', NULL),
  '23502', NULL,
  format('status nulo é recusado em %s', m.tabela)
)
FROM modelo_insercao AS m
WHERE m.tabela IN ('campanha', 'conjunto_anuncio', 'anuncio');
SELECT lives_ok(
  format('UPDATE normalizado.%I SET status = %L WHERE id_meta = %L', tabela, status, id_meta),
  format('status %s é aceito em %s', status, tabela)
)
FROM (
  VALUES
    ('campanha', '120000000000000101'),
    ('conjunto_anuncio', '120000000000000201'),
    ('anuncio', '120000000000000401')
) AS ids (tabela, id_meta)
CROSS JOIN unnest(ARRAY['PAUSED', 'DELETED', 'ARCHIVED']) AS status;

-- Domínio aberto (ADR-0009 §1): só o formato dos enums da Meta.
SELECT throws_ok(
  $$
  INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, status, execucao_id)
  SELECT empresa_id, id, '120000000000000999', 'ACTIVE', '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.conta_anuncio WHERE id_meta = '111111111111111'
  $$,
  '23502', NULL, 'campanha sem objetivo é recusada'
);
SELECT throws_ok(
  format(
    $$
    UPDATE normalizado.campanha SET objetivo = %L WHERE id_meta = '120000000000000101'
    $$,
    objetivo
  ),
  '23514',
  'new row for relation "campanha" violates check constraint "campanha_objetivo_check"',
  format('objetivo %L fora do formato é recusado', objetivo)
)
FROM unnest(ARRAY['outcome_sales', 'Vendas', '', ' OUTCOME_SALES']) AS objetivo;
SELECT lives_ok(
  $$UPDATE normalizado.campanha SET objetivo = 'OBJETIVO_NOVO_DA_META' WHERE id_meta = '120000000000000101'$$,
  'objetivo fora do catálogo, no formato da Meta, é aceito (RF-15)'
);
SELECT lives_ok(
  $$UPDATE normalizado.conjunto_anuncio SET meta_otimizacao = 'OFFSITE_CONVERSIONS' WHERE id_meta = '120000000000000201'$$,
  'meta de otimização no formato da Meta é aceita'
);
SELECT throws_ok(
  $$UPDATE normalizado.conjunto_anuncio SET meta_otimizacao = 'offsite_conversions' WHERE id_meta = '120000000000000201'$$,
  '23514',
  'new row for relation "conjunto_anuncio" violates check constraint "conjunto_anuncio_meta_otimizacao_check"',
  'meta de otimização fora do formato é recusada'
);
SELECT throws_ok(
  $$UPDATE normalizado.criativo SET chamada_acao = 'Saiba mais' WHERE id_meta = '120000000000000301'$$,
  '23514',
  'new row for relation "criativo" violates check constraint "criativo_chamada_acao_check"',
  'chamada para ação fora do formato é recusada'
);

-- Texto livre aparado e não vazio: a ETL converte vazio em NULL (RF-13).
SELECT throws_ok(
  format('UPDATE normalizado.%I SET %I = %L WHERE id_meta = %L', tabela, coluna, valor, id_meta),
  '23514',
  format('new row for relation "%s" violates check constraint "%s_%s_check"', tabela, tabela, coluna),
  format('%s.%s %L é recusado', tabela, coluna, valor)
)
FROM (
  VALUES
    ('pagina', 'nome', '300000000000002'),
    ('campanha', 'nome', '120000000000000101'),
    ('conjunto_anuncio', 'nome', '120000000000000201'),
    ('anuncio', 'nome', '120000000000000401'),
    ('criativo', 'titulo', '120000000000000301'),
    ('criativo', 'texto', '120000000000000301'),
    ('criativo', 'id_publicacao_facebook', '120000000000000301'),
    ('criativo', 'link_publicacao_facebook', '120000000000000301'),
    ('criativo', 'id_midia_instagram', '120000000000000301'),
    ('criativo', 'link_publicacao_instagram', '120000000000000301'),
    ('criativo', 'caminho_miniatura', '120000000000000301')
) AS alvo (tabela, coluna, id_meta)
CROSS JOIN unnest(ARRAY['', ' Texto']) AS valor;

-- Criativo completo. O ID da publicação no Facebook é um token "Post ID",
-- não um número (R-35).
SELECT lives_ok(
  $$
  UPDATE normalizado.criativo
  SET titulo = 'Título Teste',
      texto = 'Texto de anúncio fictício.',
      chamada_acao = 'LEARN_MORE',
      id_publicacao_facebook = '300000000000001_120000000000000999',
      link_publicacao_facebook = 'https://www.facebook.com/300000000000001/posts/120000000000000999',
      id_midia_instagram = '17800000000000001',
      link_publicacao_instagram = 'https://www.instagram.com/p/AbCdEfGhIjK/',
      caminho_miniatura = 'miniaturas/00000000-0000-0000-0000-000000000001.jpg'
  WHERE id_meta = '120000000000000301'
  $$,
  'criativo com textos, links e ID de publicação no formato Post ID é aceito'
);

-- Criativo reutilizável (N:1): dois anúncios apontam para o mesmo criativo.
SELECT lives_ok(
  $$
  INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, status, execucao_id)
  SELECT p.empresa_id, p.id, k.id, '120000000000000403', 'ACTIVE', '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.conjunto_anuncio AS p, normalizado.criativo AS k
  WHERE p.id_meta = '120000000000000201' AND k.id_meta = '120000000000000301'
  $$,
  'um segundo anúncio reutiliza o mesmo criativo'
);
SELECT is(
  (SELECT count(*) FROM normalizado.criativo WHERE empresa_id = (SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Teste A')),
  1::bigint,
  'o reuso não duplica o criativo'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, id_meta, status, execucao_id)
  SELECT empresa_id, id, '120000000000000499', 'ACTIVE', '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.conjunto_anuncio WHERE id_meta = '120000000000000201'
  $$,
  '23502', NULL, 'anúncio sem criativo é recusado (RF-01)'
);

-- Janela de atribuição: a tabela longa de attribution_spec (R-35).
SELECT lives_ok(
  $$
  INSERT INTO normalizado.janela_atribuicao_conjunto (empresa_id, conjunto_anuncio_id, tipo_evento, janela_dias, execucao_id)
  SELECT empresa_id, id, tipo_evento, janela_dias, '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.conjunto_anuncio,
    (VALUES ('CLICK_THROUGH', 7), ('VIEW_THROUGH', 1)) AS j (tipo_evento, janela_dias)
  WHERE id_meta = '120000000000000201'
  $$,
  'janelas de clique e de visualização do mesmo conjunto são aceitas'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.janela_atribuicao_conjunto (empresa_id, conjunto_anuncio_id, tipo_evento, janela_dias, execucao_id)
  SELECT empresa_id, id, 'CLICK_THROUGH', 1, '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.conjunto_anuncio WHERE id_meta = '120000000000000201'
  $$,
  '23505', NULL, 'segunda janela do mesmo tipo de evento no conjunto é recusada'
);
SELECT throws_ok(
  format(
    $$
    INSERT INTO normalizado.janela_atribuicao_conjunto (empresa_id, conjunto_anuncio_id, tipo_evento, janela_dias, execucao_id)
    SELECT empresa_id, id, %L, %s, '00000000-0000-4000-8000-00000000000a'
    FROM normalizado.conjunto_anuncio WHERE id_meta = '120000000000000201'
    $$,
    tipo_evento, janela_dias
  ),
  erro, NULL, descricao
)
FROM (
  VALUES
    ('ENGAGED_VIDEO_VIEW', '0', '23514', 'janela de 0 dias é recusada'),
    ('ENGAGED_VIDEO_VIEW', 'NULL', '23502', 'janela sem dias é recusada'),
    ('click_through', '1', '23514', 'tipo de evento fora do formato é recusado')
) AS caso (tipo_evento, janela_dias, erro, descricao);

-- Privilégios da etl_carga (ADR-0009 §3): a ETL não apaga entidades, que
-- ficam com status DELETED, e substitui as janelas do conjunto. Cada
-- privilégio é conferido sozinho, porque has_table_privilege com uma lista
-- devolve verdadeiro se o papel tiver qualquer um deles.
SELECT is(
  ARRAY(
    SELECT privilegio
    FROM unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN']) AS privilegio
    WHERE has_table_privilege('etl_carga', format('normalizado.%I', tabela), privilegio)
       OR (privilegio IN ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES')
           AND has_any_column_privilege('etl_carga', format('normalizado.%I', tabela), privilegio))
  ),
  esperado,
  format('etl_carga tem só %s em %s', array_to_string(esperado, ', '), tabela)
)
FROM (
  VALUES
    ('pagina', ARRAY['SELECT', 'INSERT', 'UPDATE']),
    ('campanha', ARRAY['SELECT', 'INSERT', 'UPDATE']),
    ('conjunto_anuncio', ARRAY['SELECT', 'INSERT', 'UPDATE']),
    ('criativo', ARRAY['SELECT', 'INSERT', 'UPDATE']),
    ('anuncio', ARRAY['SELECT', 'INSERT', 'UPDATE']),
    ('janela_atribuicao_conjunto', ARRAY['SELECT', 'INSERT', 'DELETE'])
) AS caso (tabela, esperado);
SELECT policies_are('normalizado', tabela, ARRAY['etl_carga_acessa'], format('%s tem só a política da etl_carga', tabela))
FROM unnest(ARRAY['pagina', 'campanha', 'conjunto_anuncio', 'janela_atribuicao_conjunto', 'criativo', 'anuncio']) AS tabela;

-- Como etl_carga, as funções do pgTAP não ficam acessíveis: o resultado é
-- guardado num parâmetro da transação e comparado depois de voltar ao
-- postgres. Uma política que escondesse as linhas faria os UPDATEs e o DELETE
-- terminarem sem erro e sem efeito, por isso o resultado é conferido nas
-- próprias linhas.
SET LOCAL ROLE etl_carga;
DO $$
BEGIN
  INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, objetivo, status, execucao_id)
  SELECT empresa_id, id, '120000000000000103', 'OUTCOME_LEADS', 'ACTIVE', '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.conta_anuncio WHERE id_meta = '111111111111111';
  UPDATE normalizado.campanha SET status = 'PAUSED' WHERE id_meta = '120000000000000103';
  UPDATE normalizado.pagina SET nome = 'Página ETL' WHERE id_meta = '300000000000002';
  UPDATE normalizado.conjunto_anuncio SET nome = 'Conjunto ETL' WHERE id_meta = '120000000000000202';
  UPDATE normalizado.criativo SET titulo = 'Título ETL' WHERE id_meta = '120000000000000302';
  UPDATE normalizado.anuncio SET nome = 'Anúncio ETL' WHERE id_meta = '120000000000000402';
  DELETE FROM normalizado.janela_atribuicao_conjunto
  WHERE conjunto_anuncio_id = (SELECT id FROM normalizado.conjunto_anuncio WHERE id_meta = '120000000000000201');
  INSERT INTO normalizado.janela_atribuicao_conjunto (empresa_id, conjunto_anuncio_id, tipo_evento, janela_dias, execucao_id)
  SELECT empresa_id, id, 'CLICK_THROUGH', 28, '00000000-0000-4000-8000-00000000000a'
  FROM normalizado.conjunto_anuncio WHERE id_meta = '120000000000000201';
  PERFORM set_config('entidades_meta_test.etl', 'aceito', true);
EXCEPTION WHEN OTHERS THEN
  PERFORM set_config('entidades_meta_test.etl', SQLSTATE, true);
END
$$;
RESET ROLE;
SELECT is(current_setting('entidades_meta_test.etl'), 'aceito', 'etl_carga grava as entidades sem erro');
SELECT results_eq(
  $$
  SELECT 'campanha', status FROM normalizado.campanha WHERE id_meta = '120000000000000103'
  UNION ALL SELECT 'pagina', nome FROM normalizado.pagina WHERE id_meta = '300000000000002'
  UNION ALL SELECT 'conjunto_anuncio', nome FROM normalizado.conjunto_anuncio WHERE id_meta = '120000000000000202'
  UNION ALL SELECT 'criativo', titulo FROM normalizado.criativo WHERE id_meta = '120000000000000302'
  UNION ALL SELECT 'anuncio', nome FROM normalizado.anuncio WHERE id_meta = '120000000000000402'
  $$,
  $$
  VALUES ('campanha', 'PAUSED'), ('pagina', 'Página ETL'), ('conjunto_anuncio', 'Conjunto ETL'),
    ('criativo', 'Título ETL'), ('anuncio', 'Anúncio ETL')
  $$,
  'etl_carga inclui e atualiza as entidades'
);
SELECT results_eq(
  $$
  SELECT j.tipo_evento, j.janela_dias
  FROM normalizado.janela_atribuicao_conjunto AS j
  JOIN normalizado.conjunto_anuncio AS c ON c.id = j.conjunto_anuncio_id
  WHERE c.id_meta = '120000000000000201'
  $$,
  $$VALUES ('CLICK_THROUGH', 28)$$,
  'etl_carga substitui as janelas de atribuição do conjunto'
);

SELECT * FROM finish();
ROLLBACK;
