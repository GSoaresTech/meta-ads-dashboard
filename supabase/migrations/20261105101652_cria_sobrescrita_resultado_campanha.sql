-- Sobrescrita do resultado principal por campanha: o primeiro passo da
-- precedência do ADR-0007, mantido pelo operador (RF-49; ADR-0009 §2 e §3).
-- É dado operacional da empresa, fora do repositório, ao contrário do
-- catálogo global, que muda por migration.

-- Uma linha por campanha com resultado definido pelo operador. Os dois
-- campos são obrigatórios: a sobrescrita substitui o par resultado e KPI do
-- catálogo, e o nome do objetivo e as métricas de apoio continuam vindo dele.
CREATE TABLE normalizado.sobrescrita_resultado_campanha (
  empresa_id uuid NOT NULL REFERENCES normalizado.empresa (id),
  campanha_id uuid NOT NULL,
  metrica_resultado text NOT NULL REFERENCES normalizado.metrica (codigo),
  metrica_kpi text NOT NULL REFERENCES normalizado.metrica (codigo),
  criado_em timestamptz NOT NULL DEFAULT now(),
  atualizado_em timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (empresa_id, campanha_id),
  CONSTRAINT sobrescrita_resultado_campanha_campanha_fkey FOREIGN KEY (empresa_id, campanha_id)
    REFERENCES normalizado.campanha (empresa_id, id)
);

ALTER TABLE normalizado.sobrescrita_resultado_campanha ENABLE ROW LEVEL SECURITY;

-- A ETL lê a sobrescrita pela resolução do resultado (RF-15, RF-16); a
-- escrita é da área do operador, pelas funções de analitico, donas do
-- postgres. O grant limita a política a SELECT (ADR-0009 §3).
CREATE POLICY etl_carga_acessa ON normalizado.sobrescrita_resultado_campanha
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);

GRANT SELECT ON normalizado.sobrescrita_resultado_campanha TO etl_carga;
