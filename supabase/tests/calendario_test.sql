-- Prova a tabela de calendário, a única fonte para agrupar dia, semana ISO,
-- mês e ano (CLAUDE.md §5; REQUIREMENTS §3.2; ADR-0009 §2).
BEGIN;
SELECT plan(15);

SELECT col_is_pk('normalizado', 'calendario', 'data', 'data é a PK de calendario');

-- Cada data do intervalo de 01/01/2023 a 31/12/2035 tem exatamente uma linha,
-- e não há linha fora dele.
SELECT is_empty(
  $$
  SELECT coalesce(esperada.data, c.data) AS data, count(c.data) AS linhas
  FROM generate_series('2023-01-01'::timestamp, '2035-12-31'::timestamp, interval '1 day') AS esperada (data)
  FULL JOIN normalizado.calendario AS c ON c.data = esperada.data::date
  GROUP BY coalesce(esperada.data, c.data), esperada.data
  HAVING esperada.data IS NULL OR count(c.data) <> 1
  $$,
  'cada data de 01/01/2023 a 31/12/2035 tem exatamente uma linha, e nenhuma outra existe'
);

-- Viradas de ano: a semana pertence ao ano ISO, enquanto mês e ano seguem o
-- calendário.
SELECT results_eq(
  $$
  SELECT data, dia_semana_iso, semana_iso, ano_iso, inicio_semana, mes, ano, inicio_mes, nome_mes
  FROM normalizado.calendario
  WHERE data IN ('2025-12-29', '2027-01-01', '2023-01-01', '2024-12-30', '2026-12-31', '2035-12-31')
  ORDER BY data
  $$,
  $$
  SELECT data::date, dia_semana_iso::smallint, semana_iso::smallint, ano_iso::smallint,
         inicio_semana::date, mes::smallint, ano::smallint, inicio_mes::date, nome_mes
  FROM (
    VALUES
      ('2023-01-01', 7, 52, 2022, '2022-12-26', 1, 2023, '2023-01-01', 'janeiro'),
      ('2024-12-30', 1, 1, 2025, '2024-12-30', 12, 2024, '2024-12-01', 'dezembro'),
      ('2025-12-29', 1, 1, 2026, '2025-12-29', 12, 2025, '2025-12-01', 'dezembro'),
      ('2026-12-31', 4, 53, 2026, '2026-12-28', 12, 2026, '2026-12-01', 'dezembro'),
      ('2027-01-01', 5, 53, 2026, '2026-12-28', 1, 2027, '2027-01-01', 'janeiro'),
      ('2035-12-31', 1, 1, 2036, '2035-12-31', 12, 2035, '2035-12-01', 'dezembro')
  ) AS esperado (data, dia_semana_iso, semana_iso, ano_iso, inicio_semana, mes, ano, inicio_mes, nome_mes)
  $$,
  'viradas de ano: 29/12/2025 é da semana ISO 1 de 2026, e 01/01/2027 da semana 53 de 2026'
);

SELECT results_eq(
  $$
  SELECT mes, nome_mes
  FROM normalizado.calendario
  GROUP BY mes, nome_mes
  ORDER BY mes
  $$,
  $$
  SELECT mes::smallint, nome_mes
  FROM (
    VALUES
      (1, 'janeiro'), (2, 'fevereiro'), (3, 'março'), (4, 'abril'),
      (5, 'maio'), (6, 'junho'), (7, 'julho'), (8, 'agosto'),
      (9, 'setembro'), (10, 'outubro'), (11, 'novembro'), (12, 'dezembro')
  ) AS esperado (mes, nome_mes)
  $$,
  'cada mês tem um único nome em pt-BR, do mapeamento fixo'
);

-- Uma semana ISO completa tem 7 datas, de segunda a domingo. Só as semanas
-- cortadas pelas bordas do intervalo ficam incompletas.
SELECT is_empty(
  $$
  SELECT ano_iso, semana_iso
  FROM normalizado.calendario
  GROUP BY ano_iso, semana_iso
  HAVING count(*) <> 7
    AND min(data) <> '2023-01-01'
    AND max(data) <> '2035-12-31'
  $$,
  'toda semana ISO interna ao intervalo tem 7 datas'
);

SELECT is_empty(
  $$
  SELECT ano_iso, semana_iso
  FROM normalizado.calendario
  GROUP BY ano_iso, semana_iso
  HAVING count(DISTINCT inicio_semana) <> 1
     OR min(inicio_semana) <> min(data) - (min(dia_semana_iso) - 1)
  $$,
  'as datas de uma semana ISO têm o mesmo início, a segunda-feira da semana'
);

SELECT is_empty(
  $$
  SELECT ano, mes
  FROM normalizado.calendario
  GROUP BY ano, mes
  HAVING count(DISTINCT inicio_mes) <> 1
     OR min(inicio_mes) <> min(data)
  $$,
  'as datas de um mês têm o mesmo início, o dia 1 do mês'
);

-- Os CHECKs recusam uma linha incoerente com a data, mesmo fora do
-- intervalo. 2036-01-07 é uma segunda-feira da semana ISO 2 de 2036.
SELECT lives_ok(
  $$
  INSERT INTO normalizado.calendario
    (data, dia_semana_iso, semana_iso, ano_iso, inicio_semana, mes, ano, inicio_mes)
  VALUES ('2036-01-07', 1, 2, 2036, '2036-01-07', 1, 2036, '2036-01-01')
  $$,
  'uma linha coerente é aceita'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.calendario
    (data, dia_semana_iso, semana_iso, ano_iso, inicio_semana, mes, ano, inicio_mes)
  VALUES ('2036-01-08', 2, 54, 2036, '2036-01-07', 1, 2036, '2036-01-01')
  $$,
  '23514',
  NULL,
  'semana ISO fora de 1 a 53 é recusada'
);
-- Valores dentro da faixa, mas de outra data: 2036-01-08 é da semana 2.
SELECT throws_ok(
  $$
  INSERT INTO normalizado.calendario
    (data, dia_semana_iso, semana_iso, ano_iso, inicio_semana, mes, ano, inicio_mes)
  VALUES ('2036-01-08', 2, 40, 2036, '2036-01-07', 1, 2036, '2036-01-01')
  $$,
  '23514',
  NULL,
  'semana ISO de outra data é recusada'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.calendario
    (data, dia_semana_iso, semana_iso, ano_iso, inicio_semana, mes, ano, inicio_mes)
  VALUES ('2036-01-08', 2, 2, 2037, '2036-01-07', 1, 2037, '2037-01-01')
  $$,
  '23514',
  NULL,
  'ano de outra data é recusado'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.calendario
    (data, dia_semana_iso, semana_iso, ano_iso, inicio_semana, mes, ano, inicio_mes)
  VALUES ('2036-01-08', 2, 2, 2036, '2036-01-06', 1, 2036, '2036-01-01')
  $$,
  '23514',
  NULL,
  'início da semana que não corresponde ao dia da semana é recusado'
);
SELECT throws_ok(
  $$
  INSERT INTO normalizado.calendario
    (data, dia_semana_iso, semana_iso, ano_iso, inicio_semana, mes, ano, inicio_mes)
  VALUES ('2036-01-08', 2, 2, 2036, '2036-01-07', 1, 2036, '2035-12-01')
  $$,
  '23514',
  NULL,
  'início do mês fora do mês da data é recusado'
);

-- A ETL só lê o calendário (ADR-0009 §3); a política deixa o RLS liberar as
-- linhas para ela.
SELECT ok(
  has_table_privilege('etl_carga', 'normalizado.calendario', 'SELECT')
    AND NOT has_table_privilege(
      'etl_carga', 'normalizado.calendario', 'INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN'
    ),
  'etl_carga tem só SELECT em calendario'
);

-- Como etl_carga, as funções do pgTAP não ficam acessíveis: a contagem é
-- guardada num parâmetro da transação e comparada depois de voltar ao postgres.
SET LOCAL ROLE etl_carga;
SELECT set_config('calendario_test.linhas_etl_carga', count(*)::text, true)
FROM normalizado.calendario
WHERE data BETWEEN '2023-01-01' AND '2035-12-31';
RESET ROLE;

SELECT is(
  current_setting('calendario_test.linhas_etl_carga')::bigint,
  ('2035-12-31'::date - '2023-01-01'::date + 1)::bigint,
  'etl_carga lê todas as datas do calendário'
);

SELECT * FROM finish();
ROLLBACK;
