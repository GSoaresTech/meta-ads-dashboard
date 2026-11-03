-- Quebras diárias por campanha e as ações delas: idade+gênero,
-- plataforma+posicionamento e região, com as métricas-base e as ações dos
-- tipos do catálogo (RF-03; ADR-0009 §2 e §3). O resultado principal não é
-- coluna: depende do catálogo e da sobrescrita (RF-49), e por isso é derivado
-- em analitico. Como nas métricas diárias, os fatos não guardam a conta nem
-- colunas de auditoria.

-- Uma linha por campanha × dia × tipo de quebra × categoria. Região tem uma
-- dimensão só, e a subcategoria nula não cabe numa PK: a chave é substituta,
-- e o grão fica no UNIQUE NULLS NOT DISTINCT, que trata dois NULL como iguais.
CREATE TABLE normalizado.quebra_diaria_campanha (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  empresa_id uuid NOT NULL,
  campanha_id uuid NOT NULL,
  data date NOT NULL,
  tipo_quebra text NOT NULL,
  -- O valor da API (age e gender, publisher_platform e platform_position, ou
  -- region); o rótulo vem do catálogo.
  categoria text NOT NULL,
  subcategoria text,
  investimento numeric,
  impressoes bigint,
  alcance bigint,
  execucao_id uuid NOT NULL,
  CONSTRAINT quebra_diaria_campanha_empresa_id_id_key UNIQUE (empresa_id, id),
  CONSTRAINT quebra_diaria_campanha_grao_key UNIQUE NULLS NOT DISTINCT
    (empresa_id, campanha_id, data, tipo_quebra, categoria, subcategoria),
  CONSTRAINT quebra_diaria_campanha_empresa_id_fkey FOREIGN KEY (empresa_id)
    REFERENCES normalizado.empresa (id),
  CONSTRAINT quebra_diaria_campanha_campanha_fkey FOREIGN KEY (empresa_id, campanha_id)
    REFERENCES normalizado.campanha (empresa_id, id),
  CONSTRAINT quebra_diaria_campanha_calendario_fkey FOREIGN KEY (data)
    REFERENCES normalizado.calendario (data),
  CONSTRAINT quebra_diaria_campanha_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id),
  CONSTRAINT quebra_diaria_campanha_tipo_quebra_check
    CHECK (tipo_quebra IN ('idade_genero', 'plataforma_posicionamento', 'regiao')),
  CONSTRAINT quebra_diaria_campanha_regiao_subcategoria_check CHECK ((tipo_quebra = 'regiao') = (subcategoria IS NULL)),
  -- Domínio aberto. A região é texto livre da API, com espaços e acentos,
  -- então o formato é só o do texto aparado e não vazio (ADR-0009 §1).
  CONSTRAINT quebra_diaria_campanha_categoria_check CHECK (categoria = btrim(categoria) AND categoria <> ''),
  CONSTRAINT quebra_diaria_campanha_subcategoria_check
    CHECK (subcategoria = btrim(subcategoria) AND subcategoria <> ''),
  CONSTRAINT quebra_diaria_campanha_investimento_check CHECK (investimento >= 0),
  CONSTRAINT quebra_diaria_campanha_impressoes_check CHECK (impressoes >= 0),
  CONSTRAINT quebra_diaria_campanha_alcance_check CHECK (alcance >= 0)
);

-- Uma linha por linha de quebra × tipo de ação, para os tipos do catálogo de
-- métricas, e não só os do resultado principal: assim uma sobrescrita vale
-- também para o histórico, sem reextração (ADR-0009 §2). Sai junto com a
-- linha de quebra.
CREATE TABLE normalizado.acao_quebra_diaria_campanha (
  empresa_id uuid NOT NULL,
  quebra_diaria_campanha_id bigint NOT NULL,
  tipo_acao text NOT NULL,
  quantidade bigint,
  valor numeric,
  execucao_id uuid NOT NULL,
  PRIMARY KEY (empresa_id, quebra_diaria_campanha_id, tipo_acao),
  CONSTRAINT acao_quebra_diaria_campanha_empresa_id_fkey FOREIGN KEY (empresa_id)
    REFERENCES normalizado.empresa (id),
  CONSTRAINT acao_quebra_diaria_campanha_quebra_diaria_campanha_fkey FOREIGN KEY (empresa_id, quebra_diaria_campanha_id)
    REFERENCES normalizado.quebra_diaria_campanha (empresa_id, id) ON DELETE CASCADE,
  CONSTRAINT acao_quebra_diaria_campanha_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id),
  -- O mesmo formato de acao_diaria_anuncio (R-21).
  CONSTRAINT acao_quebra_diaria_campanha_tipo_acao_check CHECK (tipo_acao ~ '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$'),
  CONSTRAINT acao_quebra_diaria_campanha_quantidade_check CHECK (quantidade >= 0),
  CONSTRAINT acao_quebra_diaria_campanha_valor_check CHECK (valor >= 0),
  CONSTRAINT acao_quebra_diaria_campanha_medida_check CHECK (quantidade IS NOT NULL OR valor IS NOT NULL)
);

-- Intervalos do painel e substituição da janela (ADR-0009 §2). As ações da
-- quebra não têm data e saem pela cascata, que usa a PK.
CREATE INDEX quebra_diaria_campanha_empresa_id_data_idx
  ON normalizado.quebra_diaria_campanha (empresa_id, data);

ALTER TABLE normalizado.quebra_diaria_campanha ENABLE ROW LEVEL SECURITY;
ALTER TABLE normalizado.acao_quebra_diaria_campanha ENABLE ROW LEVEL SECURITY;

-- Os grants limitam a política aos comandos da ETL (ADR-0009 §3).
CREATE POLICY etl_carga_acessa ON normalizado.quebra_diaria_campanha
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON normalizado.acao_quebra_diaria_campanha
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);

-- A substituição da janela apaga o escopo e inclui o conjunto completo, sem
-- UPDATE (ADR-0009 §5).
GRANT SELECT, INSERT, DELETE
  ON normalizado.quebra_diaria_campanha, normalizado.acao_quebra_diaria_campanha
  TO etl_carga;
