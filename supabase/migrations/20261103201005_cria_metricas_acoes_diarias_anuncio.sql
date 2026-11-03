-- Métricas e ações diárias por anúncio: o fato de maior uso do painel e a
-- tabela longa de actions e action_values (RF-12; CLAUDE.md §5; ADR-0009 §2 e
-- §3). Os fatos não guardam a conta, derivável pelo anúncio, nem colunas de
-- auditoria: a carga substitui as linhas a cada execução, e o instante é o da
-- execução, por execucao_id.
--
-- Métrica-base ausente é NULL, nunca zero; na tabela de ações, a ausência de
-- linha é que significa zero, porque a API omite os tipos sem ocorrência.

-- Uma linha por anúncio × dia. O alcance é o do dia e nunca é somado entre
-- dias (ADR-0006).
CREATE TABLE normalizado.metrica_diaria_anuncio (
  empresa_id uuid NOT NULL,
  anuncio_id uuid NOT NULL,
  data date NOT NULL,
  investimento numeric,
  impressoes bigint,
  alcance bigint,
  execucao_id uuid NOT NULL,
  PRIMARY KEY (empresa_id, anuncio_id, data),
  CONSTRAINT metrica_diaria_anuncio_empresa_id_fkey FOREIGN KEY (empresa_id)
    REFERENCES normalizado.empresa (id),
  CONSTRAINT metrica_diaria_anuncio_anuncio_fkey FOREIGN KEY (empresa_id, anuncio_id)
    REFERENCES normalizado.anuncio (empresa_id, id),
  CONSTRAINT metrica_diaria_anuncio_calendario_fkey FOREIGN KEY (data)
    REFERENCES normalizado.calendario (data),
  CONSTRAINT metrica_diaria_anuncio_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id),
  CONSTRAINT metrica_diaria_anuncio_investimento_check CHECK (investimento >= 0),
  CONSTRAINT metrica_diaria_anuncio_impressoes_check CHECK (impressoes >= 0),
  CONSTRAINT metrica_diaria_anuncio_alcance_check CHECK (alcance >= 0)
);

-- Uma linha por anúncio × dia × tipo de ação, com a quantidade de actions e o
-- valor de action_values. Sai junto com a métrica do mesmo anúncio e dia,
-- para que a substituição da janela não deixe órfão um tipo que sumiu na
-- revisão da Meta (RF-17).
CREATE TABLE normalizado.acao_diaria_anuncio (
  empresa_id uuid NOT NULL,
  anuncio_id uuid NOT NULL,
  data date NOT NULL,
  tipo_acao text NOT NULL,
  quantidade bigint,
  valor numeric,
  execucao_id uuid NOT NULL,
  PRIMARY KEY (empresa_id, anuncio_id, data, tipo_acao),
  CONSTRAINT acao_diaria_anuncio_empresa_id_fkey FOREIGN KEY (empresa_id)
    REFERENCES normalizado.empresa (id),
  CONSTRAINT acao_diaria_anuncio_metrica_diaria_anuncio_fkey FOREIGN KEY (empresa_id, anuncio_id, data)
    REFERENCES normalizado.metrica_diaria_anuncio (empresa_id, anuncio_id, data) ON DELETE CASCADE,
  CONSTRAINT acao_diaria_anuncio_calendario_fkey FOREIGN KEY (data)
    REFERENCES normalizado.calendario (data),
  CONSTRAINT acao_diaria_anuncio_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id),
  -- Domínio aberto: os tipos personalizados não têm lista fechada (R-21). O
  -- formato é o dos tipos da Meta, segmentos minúsculos separados por ponto,
  -- como offsite_conversion.custom.<id>.
  CONSTRAINT acao_diaria_anuncio_tipo_acao_check CHECK (tipo_acao ~ '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$'),
  CONSTRAINT acao_diaria_anuncio_quantidade_check CHECK (quantidade >= 0),
  CONSTRAINT acao_diaria_anuncio_valor_check CHECK (valor >= 0),
  CONSTRAINT acao_diaria_anuncio_medida_check CHECK (quantidade IS NOT NULL OR valor IS NOT NULL)
);

-- Intervalos do painel e substituição da janela (ADR-0009 §2).
CREATE INDEX metrica_diaria_anuncio_empresa_id_data_idx
  ON normalizado.metrica_diaria_anuncio (empresa_id, data);
CREATE INDEX acao_diaria_anuncio_empresa_id_data_idx
  ON normalizado.acao_diaria_anuncio (empresa_id, data);

ALTER TABLE normalizado.metrica_diaria_anuncio ENABLE ROW LEVEL SECURITY;
ALTER TABLE normalizado.acao_diaria_anuncio ENABLE ROW LEVEL SECURITY;

-- Os grants limitam a política aos comandos da ETL (ADR-0009 §3).
CREATE POLICY etl_carga_acessa ON normalizado.metrica_diaria_anuncio
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON normalizado.acao_diaria_anuncio
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);

-- A substituição da janela apaga o escopo e inclui o conjunto completo, sem
-- UPDATE (ADR-0009 §5).
GRANT SELECT, INSERT, DELETE
  ON normalizado.metrica_diaria_anuncio, normalizado.acao_diaria_anuncio
  TO etl_carga;
