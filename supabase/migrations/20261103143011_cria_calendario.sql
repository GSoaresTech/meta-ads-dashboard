-- Calendário: a única fonte para agrupar dia, semana ISO, mês e ano
-- (CLAUDE.md §5; REQUIREMENTS §3.2; ADR-0009 §2). É global, sem empresa_id.
CREATE TABLE normalizado.calendario (
  data date PRIMARY KEY,
  dia_semana_iso smallint NOT NULL,
  semana_iso smallint NOT NULL,
  ano_iso smallint NOT NULL,
  inicio_semana date NOT NULL,
  mes smallint NOT NULL,
  ano smallint NOT NULL,
  inicio_mes date NOT NULL,
  -- Mapeamento fixo, e não to_char com TMMonth, que depende do locale do
  -- servidor. Gerada a partir de mes, o nome não tem como divergir do número.
  nome_mes text NOT NULL GENERATED ALWAYS AS (
    (ARRAY[
      'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
      'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'
    ])[mes]
  ) STORED,
  -- Os CHECKs amarram cada coluna à data com extract e make_date, que são
  -- imutáveis e independentes do to_char da geração abaixo: uma migration que
  -- estender o intervalo com uma linha incoerente falha. date_trunc não serve,
  -- porque sobre date resolve para timestamptz e depende do fuso.
  CONSTRAINT calendario_dia_semana_iso_check CHECK (dia_semana_iso = extract(isodow FROM data)),
  CONSTRAINT calendario_semana_iso_check CHECK (semana_iso = extract(week FROM data)),
  CONSTRAINT calendario_ano_iso_check CHECK (ano_iso = extract(isoyear FROM data)),
  CONSTRAINT calendario_inicio_semana_check CHECK (inicio_semana = data - (dia_semana_iso - 1)),
  CONSTRAINT calendario_mes_check CHECK (mes = extract(month FROM data)),
  CONSTRAINT calendario_ano_check CHECK (ano = extract(year FROM data)),
  CONSTRAINT calendario_inicio_mes_check CHECK (inicio_mes = make_date(ano, mes, 1))
);

-- O intervalo cobre os 37 meses de histórico (R-19) de qualquer conta
-- cadastrada até o fim dele; estendê-lo é uma migration nova (ADR-0009). A
-- série é de timestamp sem fuso para não depender do TimeZone da sessão.
INSERT INTO normalizado.calendario
  (data, dia_semana_iso, semana_iso, ano_iso, inicio_semana, mes, ano, inicio_mes)
SELECT
  dia::date,
  to_char(dia, 'ID')::smallint,
  to_char(dia, 'IW')::smallint,
  to_char(dia, 'IYYY')::smallint,
  dia::date - (to_char(dia, 'ID')::integer - 1),
  to_char(dia, 'MM')::smallint,
  to_char(dia, 'YYYY')::smallint,
  dia::date - (to_char(dia, 'DD')::integer - 1)
FROM generate_series('2023-01-01'::timestamp, '2035-12-31'::timestamp, interval '1 day') AS dia;

ALTER TABLE normalizado.calendario ENABLE ROW LEVEL SECURITY;

-- A ETL só lê o calendário; o grant limita a política a SELECT (ADR-0009 §3).
CREATE POLICY etl_carga_acessa ON normalizado.calendario
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);

GRANT SELECT ON normalizado.calendario TO etl_carga;
