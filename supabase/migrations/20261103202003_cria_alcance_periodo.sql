-- Alcance por período: alcance e impressões já agregados pela API por conta,
-- campanha e anúncio, para cada semana ISO, mês e ano, porque alcance conta
-- pessoas únicas e nunca é somado entre dias nem entre entidades (RF-04;
-- ADR-0006; ADR-0009 §2 e §3). Como nos demais fatos, sem colunas de
-- auditoria.

-- Uma linha por entidade × tipo de período × início do período. A entidade é
-- uma coluna por nível, cada uma com sua FK composta, e o CHECK de
-- num_nonnulls exige exatamente uma; como as FKs são MATCH SIMPLE, só a da
-- entidade preenchida é conferida. Duas das três ficam sempre nulas, então o
-- grão não cabe numa PK e fica num UNIQUE NULLS NOT DISTINCT.
CREATE TABLE normalizado.alcance_periodo (
  empresa_id uuid NOT NULL,
  conta_anuncio_id uuid,
  campanha_id uuid,
  anuncio_id uuid,
  tipo_periodo text NOT NULL,
  inicio_periodo date NOT NULL,
  -- Guardado porque não é derivável no período em andamento, extraído só até
  -- o dia da extração (ADR-0006).
  fim_periodo date NOT NULL,
  alcance bigint,
  impressoes bigint,
  execucao_id uuid NOT NULL,
  CONSTRAINT alcance_periodo_grao_key UNIQUE NULLS NOT DISTINCT
    (empresa_id, conta_anuncio_id, campanha_id, anuncio_id, tipo_periodo, inicio_periodo),
  CONSTRAINT alcance_periodo_empresa_id_fkey FOREIGN KEY (empresa_id)
    REFERENCES normalizado.empresa (id),
  CONSTRAINT alcance_periodo_conta_anuncio_fkey FOREIGN KEY (empresa_id, conta_anuncio_id)
    REFERENCES normalizado.conta_anuncio (empresa_id, id),
  CONSTRAINT alcance_periodo_campanha_fkey FOREIGN KEY (empresa_id, campanha_id)
    REFERENCES normalizado.campanha (empresa_id, id),
  CONSTRAINT alcance_periodo_anuncio_fkey FOREIGN KEY (empresa_id, anuncio_id)
    REFERENCES normalizado.anuncio (empresa_id, id),
  CONSTRAINT alcance_periodo_inicio_periodo_fkey FOREIGN KEY (inicio_periodo)
    REFERENCES normalizado.calendario (data),
  CONSTRAINT alcance_periodo_fim_periodo_fkey FOREIGN KEY (fim_periodo)
    REFERENCES normalizado.calendario (data),
  CONSTRAINT alcance_periodo_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id),
  CONSTRAINT alcance_periodo_entidade_check CHECK (num_nonnulls(conta_anuncio_id, campanha_id, anuncio_id) = 1),
  CONSTRAINT alcance_periodo_tipo_periodo_check CHECK (tipo_periodo IN ('semana', 'mes', 'ano')),
  CONSTRAINT alcance_periodo_fim_periodo_check CHECK (fim_periodo >= inicio_periodo),
  -- Os CHECKs de alinhamento usam extract só para validar a linha; o
  -- agrupamento por semana, mês e ano vem apenas de calendario (CLAUDE.md
  -- §5). A semana ISO começa na segunda-feira e dura até 7 dias.
  CONSTRAINT alcance_periodo_semana_check CHECK (
    tipo_periodo <> 'semana'
    OR (extract(isodow FROM inicio_periodo) = 1 AND fim_periodo - inicio_periodo < 7)
  ),
  CONSTRAINT alcance_periodo_mes_check CHECK (
    tipo_periodo <> 'mes'
    OR (
      extract(day FROM inicio_periodo) = 1
      AND extract(month FROM fim_periodo) = extract(month FROM inicio_periodo)
      AND extract(year FROM fim_periodo) = extract(year FROM inicio_periodo)
    )
  ),
  CONSTRAINT alcance_periodo_ano_check CHECK (
    tipo_periodo <> 'ano'
    OR (
      extract(doy FROM inicio_periodo) = 1
      AND extract(year FROM fim_periodo) = extract(year FROM inicio_periodo)
    )
  ),
  CONSTRAINT alcance_periodo_alcance_check CHECK (alcance >= 0),
  CONSTRAINT alcance_periodo_impressoes_check CHECK (impressoes >= 0)
);

ALTER TABLE normalizado.alcance_periodo ENABLE ROW LEVEL SECURITY;

-- O grant limita a política aos comandos da ETL (ADR-0009 §3).
CREATE POLICY etl_carga_acessa ON normalizado.alcance_periodo
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);

-- A substituição dos períodos que tocam a janela apaga e inclui, sem UPDATE
-- (ADR-0009 §5).
GRANT SELECT, INSERT, DELETE ON normalizado.alcance_periodo TO etl_carga;
