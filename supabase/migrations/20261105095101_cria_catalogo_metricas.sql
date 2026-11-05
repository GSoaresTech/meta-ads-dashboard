-- Catálogo de métricas e de resultado por objetivo: rótulos, explicações,
-- fórmulas, aditividade e o mapa objetivo → resultado principal são dados,
-- não código (ADR-0007; ADR-0009 §2 e §3). As tabelas são globais, sem
-- empresa_id, e mudam só por migration; a sobrescrita por campanha é dado
-- operacional da empresa e fica em tabela própria.
--
-- Objetivo e meta de otimização são domínio aberto: só o formato dos enums da
-- Meta, como em campanha e conjunto_anuncio, porque o catálogo também guarda
-- objetivos legados e combinações que a Meta pode acrescentar (RF-15).

-- Uma linha por métrica. O tipo amarra a origem: a métrica base lê uma coluna
-- de metrica_diaria_anuncio, já com o nome em português (a tradução do campo
-- da API fica só no mapa de campos da ETL); a de ação lê a quantidade ou o
-- valor de um tipo de ação da tabela longa; e a derivada é calculada em
-- analitico a partir das outras, sem origem própria.
CREATE TABLE normalizado.metrica (
  codigo text PRIMARY KEY,
  rotulo text NOT NULL,
  explicacao text NOT NULL,
  formula text NOT NULL,
  unidade text NOT NULL,
  aditiva boolean NOT NULL,
  tipo text NOT NULL,
  campo_base text,
  tipo_acao text,
  medida_acao text,
  -- Alvo da FK composta (metrica, unidade) das metas, que deixa a regra da
  -- moeda dentro de uma única linha (ADR-0009 §2).
  CONSTRAINT metrica_codigo_unidade_key UNIQUE (codigo, unidade),
  CONSTRAINT metrica_codigo_check CHECK (codigo ~ '^[a-z][a-z0-9_]*$'),
  CONSTRAINT metrica_rotulo_check CHECK (rotulo = btrim(rotulo) AND rotulo <> ''),
  -- RNF-01: explicações curtas. char_length conta caracteres, não bytes.
  CONSTRAINT metrica_explicacao_check
    CHECK (explicacao = btrim(explicacao) AND explicacao <> '' AND char_length(explicacao) <= 200),
  CONSTRAINT metrica_formula_check CHECK (formula = btrim(formula) AND formula <> ''),
  CONSTRAINT metrica_unidade_check CHECK (unidade IN ('moeda', 'quantidade', 'percentual', 'razao')),
  CONSTRAINT metrica_tipo_check CHECK (tipo IN ('base', 'acao', 'derivada')),
  CONSTRAINT metrica_campo_base_check CHECK (campo_base ~ '^[a-z][a-z0-9_]*$'),
  -- O mesmo formato de tipo_acao nas tabelas de ações (R-21).
  CONSTRAINT metrica_tipo_acao_check CHECK (tipo_acao ~ '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$'),
  CONSTRAINT metrica_medida_acao_check CHECK (medida_acao IN ('quantidade', 'valor')),
  CONSTRAINT metrica_origem_check CHECK (
    CASE tipo
      WHEN 'base' THEN campo_base IS NOT NULL AND tipo_acao IS NULL AND medida_acao IS NULL
      WHEN 'acao' THEN campo_base IS NULL AND tipo_acao IS NOT NULL AND medida_acao IS NOT NULL
      ELSE num_nulls(campo_base, tipo_acao, medida_acao) = 3
    END
  )
);

-- Uma linha por objetivo × meta de otimização. meta_otimizacao nula é
-- "qualquer", e a linha específica vence a genérica pela precedência do
-- ADR-0007, o que resolve "qualquer, exceto CONVERSATIONS". objetivo nulo é a
-- linha única de "Não classificado", com o rótulo e as métricas de apoio do
-- caso sem catálogo. Como as duas colunas da chave natural são anuláveis, ela
-- fica num UNIQUE NULLS NOT DISTINCT, com a chave substituta como PK.
CREATE TABLE normalizado.resultado_objetivo (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  objetivo text,
  meta_otimizacao text,
  nome_objetivo text NOT NULL,
  -- Anuláveis: "Não classificado" não tem resultado, e o de
  -- OUTCOME_APP_PROMOTION é a confirmar (REQUIREMENTS §7.2, Q-10).
  metrica_resultado text REFERENCES normalizado.metrica (codigo),
  metrica_kpi text REFERENCES normalizado.metrica (codigo),
  CONSTRAINT resultado_objetivo_objetivo_meta_otimizacao_key
    UNIQUE NULLS NOT DISTINCT (objetivo, meta_otimizacao),
  CONSTRAINT resultado_objetivo_objetivo_check CHECK (objetivo ~ '^[A-Z][A-Z0-9_]*$'),
  CONSTRAINT resultado_objetivo_meta_otimizacao_check CHECK (meta_otimizacao ~ '^[A-Z][A-Z0-9_]*$'),
  CONSTRAINT resultado_objetivo_nao_classificado_check CHECK (objetivo IS NOT NULL OR meta_otimizacao IS NULL),
  CONSTRAINT resultado_objetivo_nome_objetivo_check CHECK (nome_objetivo = btrim(nome_objetivo) AND nome_objetivo <> '')
);

-- A lista ordenada de métricas de apoio de cada resultado: uma tabela, e não
-- uma lista numa coluna, para que cada métrica tenha FK para o catálogo.
CREATE TABLE normalizado.metrica_apoio_resultado (
  resultado_objetivo_id uuid NOT NULL REFERENCES normalizado.resultado_objetivo (id),
  metrica text NOT NULL REFERENCES normalizado.metrica (codigo),
  ordem smallint NOT NULL,
  PRIMARY KEY (resultado_objetivo_id, metrica),
  CONSTRAINT metrica_apoio_resultado_resultado_objetivo_id_ordem_key UNIQUE (resultado_objetivo_id, ordem),
  CONSTRAINT metrica_apoio_resultado_ordem_check CHECK (ordem >= 1)
);

-- Uma linha por objetivo legado com um único equivalente atual na tabela
-- oficial da Meta (R-40). Os legados com mais de um equivalente e os sem
-- equivalente oficial ficam sem linha até a Q-10 ser resolvida.
CREATE TABLE normalizado.objetivo_equivalente (
  objetivo_legado text PRIMARY KEY,
  objetivo text NOT NULL,
  CONSTRAINT objetivo_equivalente_objetivo_legado_check CHECK (objetivo_legado ~ '^[A-Z][A-Z0-9_]*$'),
  CONSTRAINT objetivo_equivalente_objetivo_check CHECK (objetivo ~ '^[A-Z][A-Z0-9_]*$')
);

ALTER TABLE normalizado.metrica ENABLE ROW LEVEL SECURITY;
ALTER TABLE normalizado.resultado_objetivo ENABLE ROW LEVEL SECURITY;
ALTER TABLE normalizado.metrica_apoio_resultado ENABLE ROW LEVEL SECURITY;
ALTER TABLE normalizado.objetivo_equivalente ENABLE ROW LEVEL SECURITY;

-- A ETL só lê o catálogo; o grant limita a política a SELECT (ADR-0009 §3).
-- O painel lê o catálogo só pelas funções de analitico.
CREATE POLICY etl_carga_acessa ON normalizado.metrica
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON normalizado.resultado_objetivo
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON normalizado.metrica_apoio_resultado
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON normalizado.objetivo_equivalente
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);

GRANT SELECT ON
  normalizado.metrica,
  normalizado.resultado_objetivo,
  normalizado.metrica_apoio_resultado,
  normalizado.objetivo_equivalente
TO etl_carga;
