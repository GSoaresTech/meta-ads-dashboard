-- Prova o catálogo de métricas e de resultado por objetivo: as chaves, os
-- domínios, a amarração do tipo da métrica à origem, o limite das explicações
-- e as referências das regras de resultado às métricas (RNF-01; ADR-0007;
-- ADR-0009 §2 e §3).
BEGIN;
SELECT plan(75);

-- Estrutura
SELECT col_is_pk('normalizado', 'metrica', 'codigo', 'codigo é a PK de metrica');
SELECT col_is_unique(
  'normalizado', 'metrica', ARRAY['codigo', 'unidade'],
  'metrica tem UNIQUE (codigo, unidade), alvo da FK composta das metas'
);
SELECT col_is_pk('normalizado', 'resultado_objetivo', 'id', 'id é a PK de resultado_objetivo');
SELECT col_default_is(
  'normalizado', 'resultado_objetivo', 'id', 'gen_random_uuid()',
  'id de resultado_objetivo vem de gen_random_uuid()'
);
-- meta_otimizacao nula é "qualquer", e objetivo nulo é "Não classificado":
-- sem NULLS NOT DISTINCT, essas linhas poderiam se repetir.
SELECT ok(
  (
    SELECT i.indnullsnotdistinct
    FROM pg_catalog.pg_constraint AS c
    JOIN pg_catalog.pg_index AS i ON i.indexrelid = c.conindid
    WHERE c.conname = 'resultado_objetivo_objetivo_meta_otimizacao_key'
      AND c.conrelid = 'normalizado.resultado_objetivo'::regclass
  ),
  'resultado_objetivo tem UNIQUE NULLS NOT DISTINCT (objetivo, meta_otimizacao)'
);
SELECT col_is_pk(
  'normalizado', 'metrica_apoio_resultado', ARRAY['resultado_objetivo_id', 'metrica'],
  'metrica_apoio_resultado tem PK (resultado_objetivo_id, metrica)'
);
SELECT col_is_unique(
  'normalizado', 'metrica_apoio_resultado', ARRAY['resultado_objetivo_id', 'ordem'],
  'metrica_apoio_resultado tem UNIQUE (resultado_objetivo_id, ordem)'
);
SELECT col_is_pk('normalizado', 'objetivo_equivalente', 'objetivo_legado', 'objetivo_legado é a PK de objetivo_equivalente');

-- Toda regra de resultado aponta para métricas do catálogo.
SELECT fk_ok('normalizado', tabela, coluna, 'normalizado', 'metrica', 'codigo', format('%s.%s referencia metrica', tabela, coluna))
FROM (
  VALUES
    ('resultado_objetivo', 'metrica_resultado'),
    ('resultado_objetivo', 'metrica_kpi'),
    ('metrica_apoio_resultado', 'metrica')
) AS fk (tabela, coluna);
SELECT fk_ok(
  'normalizado', 'metrica_apoio_resultado', 'resultado_objetivo_id', 'normalizado', 'resultado_objetivo', 'id',
  'metrica_apoio_resultado.resultado_objetivo_id referencia resultado_objetivo'
);
-- A derivada é a razão entre duas métricas do próprio catálogo.
SELECT fk_ok('normalizado', 'metrica', coluna, 'normalizado', 'metrica', 'codigo', format('metrica.%s referencia metrica', coluna))
FROM unnest(ARRAY['numerador', 'denominador']) AS coluna;

-- Um CHECK avaliado como NULL passa, então as colunas de domínio e de texto
-- obrigatório são NOT NULL (ADR-0009 §1).
SELECT col_not_null('normalizado', tabela, coluna, format('%s.%s é NOT NULL', tabela, coluna))
FROM (
  VALUES
    ('metrica', 'rotulo'),
    ('metrica', 'explicacao'),
    ('metrica', 'formula'),
    ('metrica', 'unidade'),
    ('metrica', 'aditiva'),
    ('metrica', 'tipo'),
    ('resultado_objetivo', 'nome_objetivo'),
    ('metrica_apoio_resultado', 'ordem'),
    ('objetivo_equivalente', 'objetivo')
) AS coluna_obrigatoria (tabela, coluna);
-- "Qualquer" meta, "Não classificado" e as regras sem resultado principal
-- (REQUIREMENTS §7.2).
SELECT col_is_null('normalizado', 'resultado_objetivo', coluna, format('resultado_objetivo.%s é anulável', coluna))
FROM unnest(ARRAY['objetivo', 'meta_otimizacao', 'metrica_resultado', 'metrica_kpi']) AS coluna;

-- Uma métrica válida de cada tipo, usada pelos testes seguintes.
SELECT lives_ok(
  $$
  INSERT INTO normalizado.metrica
    (codigo, rotulo, explicacao, formula, unidade, aditiva, tipo, campo_base, tipo_acao, medida_acao, numerador, denominador, fator)
  VALUES
    ('teste_base', 'Base de teste', 'Explicação de teste.', 'soma', 'moeda', true, 'base', 'investimento', NULL, NULL, NULL, NULL, NULL),
    ('teste_acao', 'Ação de teste', 'Explicação de teste.', 'soma', 'quantidade', true, 'acao', NULL,
     'offsite_conversion.fb_pixel_lead', 'quantidade', NULL, NULL, NULL),
    ('teste_derivada', 'Derivada de teste', 'Explicação de teste.', 'base ÷ ação', 'moeda', false, 'derivada', NULL, NULL, NULL,
     'teste_base', 'teste_acao', 1)
  $$,
  'métricas base, de ação e derivada com a origem do próprio tipo são aceitas'
);

-- RNF-01: explicações com no máximo 200 caracteres.
SELECT lives_ok(
  format(
    $$
    INSERT INTO normalizado.metrica (codigo, rotulo, explicacao, formula, unidade, aditiva, tipo, numerador, denominador, fator)
    VALUES ('teste_200', 'Teste', %L, 'soma', 'quantidade', false, 'derivada', 'teste_base', 'teste_acao', 1)
    $$,
    repeat('á', 199) || '.'
  ),
  'RNF-01: explicação com 200 caracteres é aceita'
);
SELECT throws_ok(
  format(
    $$
    INSERT INTO normalizado.metrica (codigo, rotulo, explicacao, formula, unidade, aditiva, tipo, numerador, denominador, fator)
    VALUES ('teste_201', 'Teste', %L, 'soma', 'quantidade', false, 'derivada', 'teste_base', 'teste_acao', 1)
    $$,
    repeat('á', 200) || '.'
  ),
  '23514',
  NULL,
  'RNF-01: explicação com 201 caracteres é recusada'
);
SELECT is_empty(
  'SELECT codigo FROM normalizado.metrica WHERE char_length(explicacao) > 200',
  'RNF-01: toda explicação do catálogo tem no máximo 200 caracteres'
);

-- Domínios e textos de metrica. Cada linha muda um único campo da métrica
-- derivada válida.
SELECT throws_ok(
  format(
    $$
    INSERT INTO normalizado.metrica (codigo, rotulo, explicacao, formula, unidade, aditiva, tipo, numerador, denominador, fator)
    VALUES (%L, %L, %L, %L, %L, false, %L, 'teste_base', 'teste_acao', 1)
    $$,
    codigo, rotulo, explicacao, formula, unidade, tipo
  ),
  '23514',
  NULL,
  descricao
)
FROM (
  VALUES
    ('Teste_Maiusculas', 'Teste', 'Explicação.', 'soma', 'moeda', 'derivada', 'código fora do formato snake_case é recusado'),
    ('teste_rotulo', ' Teste', 'Explicação.', 'soma', 'moeda', 'derivada', 'rótulo não aparado é recusado'),
    ('teste_rotulo', '', 'Explicação.', 'soma', 'moeda', 'derivada', 'rótulo vazio é recusado'),
    ('teste_explicacao', 'Teste', '', 'soma', 'moeda', 'derivada', 'explicação vazia é recusada'),
    ('teste_formula', 'Teste', 'Explicação.', 'soma ', 'moeda', 'derivada', 'fórmula não aparada é recusada'),
    ('teste_unidade', 'Teste', 'Explicação.', 'soma', 'reais', 'derivada', 'unidade fora do domínio é recusada'),
    ('teste_tipo', 'Teste', 'Explicação.', 'soma', 'moeda', 'calculada', 'tipo fora do domínio é recusado')
) AS caso (codigo, rotulo, explicacao, formula, unidade, tipo, descricao);

-- O tipo amarra a origem: base lê uma coluna, ação lê um tipo de ação e uma
-- medida, e derivada lê só a razão entre duas métricas, com o fator de escala
-- (ADR-0009 §2).
SELECT throws_ok(
  format(
    $$
    INSERT INTO normalizado.metrica
      (codigo, rotulo, explicacao, formula, unidade, aditiva, tipo, campo_base, tipo_acao, medida_acao, numerador, denominador, fator)
    VALUES ('teste_origem', 'Teste', 'Explicação.', 'soma', 'quantidade', true, %L, %L, %L, %L, %L, %L, %L)
    $$,
    tipo, campo_base, tipo_acao, medida_acao, numerador, denominador, fator
  ),
  '23514',
  NULL,
  descricao
)
FROM (
  VALUES
    ('base', NULL, NULL, NULL, NULL, NULL, NULL, 'métrica base sem coluna é recusada'),
    ('base', 'impressoes', 'link_click', 'quantidade', NULL, NULL, NULL, 'métrica base com tipo de ação é recusada'),
    ('base', 'impressoes', NULL, NULL, 'teste_base', 'teste_acao', 1, 'métrica base com operandos é recusada'),
    ('acao', NULL, 'link_click', NULL, NULL, NULL, NULL, 'métrica de ação sem medida é recusada'),
    ('acao', NULL, NULL, 'quantidade', NULL, NULL, NULL, 'métrica de ação sem tipo de ação é recusada'),
    ('acao', 'impressoes', 'link_click', 'quantidade', NULL, NULL, NULL, 'métrica de ação com coluna é recusada'),
    ('acao', NULL, 'link_click', 'quantidade', 'teste_base', 'teste_acao', 1, 'métrica de ação com operandos é recusada'),
    ('acao', NULL, 'link_click', 'soma', NULL, NULL, NULL, 'medida de ação fora do domínio é recusada'),
    ('acao', NULL, 'Link Click', 'quantidade', NULL, NULL, NULL, 'tipo de ação fora do formato da API é recusado'),
    ('derivada', 'impressoes', NULL, NULL, 'teste_base', 'teste_acao', 1, 'métrica derivada com coluna é recusada'),
    ('derivada', NULL, 'link_click', 'quantidade', 'teste_base', 'teste_acao', 1, 'métrica derivada com tipo de ação é recusada'),
    ('derivada', NULL, NULL, NULL, NULL, 'teste_acao', 1, 'métrica derivada sem numerador é recusada'),
    ('derivada', NULL, NULL, NULL, 'teste_base', NULL, 1, 'métrica derivada sem denominador é recusada'),
    ('derivada', NULL, NULL, NULL, 'teste_base', 'teste_acao', NULL, 'métrica derivada sem fator é recusada'),
    ('derivada', NULL, NULL, NULL, 'teste_base', 'teste_acao', 0, 'fator zero é recusado'),
    ('base', 'Impressoes', NULL, NULL, NULL, NULL, NULL, 'coluna fora do formato snake_case é recusada')
) AS caso (tipo, campo_base, tipo_acao, medida_acao, numerador, denominador, fator, descricao);
SELECT throws_ok(
  format(
    $$
    INSERT INTO normalizado.metrica (codigo, rotulo, explicacao, formula, unidade, aditiva, tipo, numerador, denominador, fator)
    VALUES ('teste_operando', 'Teste', 'Explicação.', 'soma', 'moeda', false, 'derivada', %L, %L, 1)
    $$,
    numerador, denominador
  ),
  '23503',
  NULL,
  descricao
)
FROM (
  VALUES
    ('metrica_inexistente', 'teste_acao', 'numerador fora do catálogo de métricas é recusado'),
    ('teste_base', 'metrica_inexistente', 'denominador fora do catálogo de métricas é recusado')
) AS caso (numerador, denominador, descricao);

-- resultado_objetivo
SELECT lives_ok(
  $$
  INSERT INTO normalizado.resultado_objetivo (objetivo, meta_otimizacao, nome_objetivo, metrica_resultado, metrica_kpi)
  VALUES
    ('OBJETIVO_TESTE', NULL, 'Objetivo de teste', 'teste_acao', 'teste_derivada'),
    ('OBJETIVO_TESTE', 'META_TESTE', 'Objetivo de teste por meta', 'teste_base', NULL)
  $$,
  'a linha genérica e a específica do mesmo objetivo convivem'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.resultado_objetivo (objetivo, meta_otimizacao, nome_objetivo)
  VALUES ('OBJETIVO_TESTE', NULL, 'Outro nome')
  $$,
  '23505',
  NULL,
  'uma segunda linha "qualquer meta" para o mesmo objetivo é recusada'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.resultado_objetivo (objetivo, meta_otimizacao, nome_objetivo)
  VALUES (NULL, 'META_TESTE', 'Sem objetivo')
  $$,
  '23514',
  NULL,
  'objetivo nulo com meta de otimização preenchida é recusado'
);
SELECT throws_ok(
  format(
    $$
    INSERT INTO normalizado.resultado_objetivo (objetivo, meta_otimizacao, nome_objetivo)
    VALUES (%L, %L, %L)
    $$,
    objetivo, meta_otimizacao, nome_objetivo
  ),
  '23514',
  NULL,
  descricao
)
FROM (
  VALUES
    ('outcome_teste', NULL, 'Teste', 'objetivo fora do formato dos enums da Meta é recusado'),
    ('OBJETIVO_TESTE_2', 'meta teste', 'Teste', 'meta de otimização fora do formato dos enums da Meta é recusada'),
    ('OBJETIVO_TESTE_2', NULL, 'Teste ', 'nome do objetivo não aparado é recusado')
) AS caso (objetivo, meta_otimizacao, nome_objetivo, descricao);
SELECT throws_ok(
  format(
    $$
    INSERT INTO normalizado.resultado_objetivo (objetivo, nome_objetivo, %I)
    VALUES ('OBJETIVO_TESTE_2', 'Teste', 'metrica_inexistente')
    $$,
    coluna
  ),
  '23503',
  NULL,
  format('%s fora do catálogo de métricas é recusada', coluna)
)
FROM unnest(ARRAY['metrica_resultado', 'metrica_kpi']) AS coluna;

-- metrica_apoio_resultado
SELECT lives_ok(
  $$
  INSERT INTO normalizado.metrica_apoio_resultado (resultado_objetivo_id, metrica, ordem)
  SELECT r.id, apoio.metrica, apoio.ordem
  FROM normalizado.resultado_objetivo AS r
  CROSS JOIN (VALUES ('teste_base', 1), ('teste_derivada', 2)) AS apoio (metrica, ordem)
  WHERE r.objetivo = 'OBJETIVO_TESTE' AND r.meta_otimizacao IS NULL
  $$,
  'métricas de apoio do catálogo são aceitas, em ordem'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.metrica_apoio_resultado (resultado_objetivo_id, metrica, ordem)
  SELECT id, 'metrica_inexistente', 3
  FROM normalizado.resultado_objetivo
  WHERE objetivo = 'OBJETIVO_TESTE' AND meta_otimizacao IS NULL
  $$,
  '23503',
  NULL,
  'métrica de apoio fora do catálogo é recusada'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.metrica_apoio_resultado (resultado_objetivo_id, metrica, ordem)
  SELECT id, 'teste_acao', 2
  FROM normalizado.resultado_objetivo
  WHERE objetivo = 'OBJETIVO_TESTE' AND meta_otimizacao IS NULL
  $$,
  '23505',
  NULL,
  'duas métricas de apoio na mesma posição são recusadas'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.metrica_apoio_resultado (resultado_objetivo_id, metrica, ordem)
  SELECT id, 'teste_acao', 0
  FROM normalizado.resultado_objetivo
  WHERE objetivo = 'OBJETIVO_TESTE' AND meta_otimizacao IS NULL
  $$,
  '23514',
  NULL,
  'posição menor que 1 é recusada'
);

-- objetivo_equivalente
SELECT lives_ok(
  $$
  INSERT INTO normalizado.objetivo_equivalente (objetivo_legado, objetivo)
  VALUES ('LEGADO_TESTE', 'OBJETIVO_TESTE')
  $$,
  'um objetivo legado com o equivalente atual é aceito'
);
SELECT throws_ok(
  format(
    $$
    INSERT INTO normalizado.objetivo_equivalente (objetivo_legado, objetivo)
    VALUES (%L, %L)
    $$,
    objetivo_legado, objetivo
  ),
  '23514',
  NULL,
  descricao
)
FROM (
  VALUES
    ('legado_teste', 'OBJETIVO_TESTE', 'objetivo legado fora do formato dos enums da Meta é recusado'),
    ('LEGADO_TESTE_2', 'Objetivo Teste', 'objetivo equivalente fora do formato dos enums da Meta é recusado')
) AS caso (objetivo_legado, objetivo, descricao);

-- A ETL só lê o catálogo; ele muda por migration (ADR-0007; ADR-0009 §3).
SELECT ok(
  has_table_privilege('etl_carga', format('normalizado.%I', tabela), 'SELECT')
    AND NOT has_table_privilege(
      'etl_carga', format('normalizado.%I', tabela), 'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN'
    ),
  format('etl_carga tem só SELECT em %s', tabela)
)
FROM unnest(ARRAY['metrica', 'resultado_objetivo', 'metrica_apoio_resultado', 'objetivo_equivalente']) AS tabela;

SELECT * FROM finish();
ROLLBACK;
