-- Rótulos de negócio dos valores de enum da API que o painel exibe: nenhum
-- valor da Meta aparece na tela, e o texto é dado, não código (RF-37; RNF-02;
-- ADR-0007; ADR-0009 §1 e §2). O objetivo não entra aqui: o nome dele vem de
-- resultado_objetivo, junto com o resultado principal.
--
-- A tabela é global, sem empresa_id, e muda só por migration, como o restante
-- do catálogo. Cada domínio ganha as linhas com a visão que o exibe.
CREATE TABLE normalizado.rotulo_valor_api (
  dominio text NOT NULL,
  valor text NOT NULL,
  rotulo text NOT NULL,
  PRIMARY KEY (dominio, valor),
  CONSTRAINT rotulo_valor_api_dominio_check
    CHECK (dominio IN ('status', 'chamada_acao', 'genero', 'plataforma', 'posicionamento')),
  -- Só aparado e não vazio: cada domínio da API tem o próprio formato, e o
  -- CHECK de formato fica nas colunas que guardam esses valores.
  CONSTRAINT rotulo_valor_api_valor_check CHECK (valor = btrim(valor) AND valor <> ''),
  CONSTRAINT rotulo_valor_api_rotulo_check CHECK (rotulo = btrim(rotulo) AND rotulo <> '')
);

ALTER TABLE normalizado.rotulo_valor_api ENABLE ROW LEVEL SECURITY;

-- A ETL só lê o catálogo; o grant limita a política a SELECT (ADR-0009 §3).
-- O painel lê o catálogo só pelas funções de analitico.
CREATE POLICY etl_carga_acessa ON normalizado.rotulo_valor_api
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);

GRANT SELECT ON normalizado.rotulo_valor_api TO etl_carga;

-- O status é domínio fechado (R-35): todo valor do CHECK das entidades tem
-- rótulo, e o rotulo_valor_api_test.sql falha se um valor novo vier sem ele.
-- O feminino é o da campanha, a entidade cujo status a tela mostra (RF-37).
INSERT INTO normalizado.rotulo_valor_api (dominio, valor, rotulo) VALUES
  ('status', 'ACTIVE', 'Ativa'),
  ('status', 'PAUSED', 'Pausada'),
  ('status', 'ARCHIVED', 'Arquivada'),
  ('status', 'DELETED', 'Excluída');
