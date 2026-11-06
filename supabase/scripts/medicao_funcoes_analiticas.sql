-- Medição do RNF-06: cada função de analitico executa em até 500 ms, no p95
-- de 20 execuções, com os dados da empresa de referência (REQUIREMENTS §4.2
-- e §6.2). Cada cenário é uma chamada que o painel faz, pela credencial de
-- empresa, como o servidor do painel chama. Cada função nova de analitico
-- acrescenta aqui os próprios cenários.
--
-- Se a massa fictícia não estiver no banco local, ela é carregada antes e
-- removida no fim, porque os testes pgTAP contam as linhas do banco só com o
-- seed. Se ela já estiver, fica. Antes de medir, o VACUUM ANALYZE deixa as
-- estatísticas e o mapa de visibilidade como o autovacuum os deixa em
-- produção depois das cargas: medir com as linhas recém-inseridas, ainda
-- sem estatísticas, mede o planejador às cegas, e não a função. A medição
-- roda numa transação desfeita no fim, que leva junto a credencial gerada.
-- O token fica só em variável do psql e nunca é impresso.
\set ON_ERROR_STOP on
\set EXECUCOES 20
\set LIMITE_P95_MS 500

SELECT NOT EXISTS (SELECT FROM normalizado.empresa WHERE nome = 'Empresa Exemplo Referência') AS carregar_massa \gset
\if :carregar_massa
  BEGIN;
  \o /dev/null
  \ir massa_empresa_referencia.sql
  \o
  COMMIT;
\endif

VACUUM ANALYZE
  normalizado.conta_anuncio, normalizado.campanha, normalizado.conjunto_anuncio, normalizado.anuncio,
  normalizado.metrica_diaria_anuncio, normalizado.acao_diaria_anuncio,
  normalizado.quebra_diaria_campanha, normalizado.acao_quebra_diaria_campanha, normalizado.alcance_periodo;

BEGIN;

SELECT id AS empresa_id FROM normalizado.empresa WHERE nome = 'Empresa Exemplo Referência' \gset
SELECT normalizado.gerar_credencial('empresa', :'empresa_id') AS token \gset

-- As datas dos atalhos do painel (RF-26), pelo calendário, e o início do
-- histórico carregado. Os últimos 7 e 30 dias terminam ontem (REQUIREMENTS
-- §3.2).
SELECT
  hoje.data AS hoje,
  hoje.data - 1 AS ontem,
  hoje.data - 7 AS inicio_7_dias,
  hoje.data - 30 AS inicio_30_dias,
  hoje.inicio_mes AS inicio_mes,
  mes_passado.inicio_mes AS inicio_mes_passado,
  mes_passado.data AS fim_mes_passado,
  make_date(hoje.ano, 1, 1) AS inicio_ano,
  (SELECT min(diaria.data) FROM normalizado.metrica_diaria_anuncio AS diaria WHERE diaria.empresa_id = :'empresa_id')
    AS inicio_historico
FROM normalizado.calendario AS hoje
JOIN normalizado.calendario AS mes_passado ON mes_passado.data = hoje.inicio_mes - 1
WHERE hoje.data = current_date \gset

-- As entidades em foco são as de maior volume: a conta, a campanha e o
-- anúncio com mais dias de métrica no último ano.
SELECT conta.id AS conta_id, campanha.id AS campanha_id
FROM normalizado.metrica_diaria_anuncio AS diaria
JOIN normalizado.anuncio AS anuncio ON anuncio.empresa_id = diaria.empresa_id AND anuncio.id = diaria.anuncio_id
JOIN normalizado.conjunto_anuncio AS conjunto
  ON conjunto.empresa_id = anuncio.empresa_id AND conjunto.id = anuncio.conjunto_anuncio_id
JOIN normalizado.campanha AS campanha ON campanha.empresa_id = conjunto.empresa_id AND campanha.id = conjunto.campanha_id
JOIN normalizado.conta_anuncio AS conta ON conta.empresa_id = campanha.empresa_id AND conta.id = campanha.conta_anuncio_id
WHERE diaria.empresa_id = :'empresa_id' AND diaria.data > current_date - 365
GROUP BY conta.id, campanha.id
ORDER BY count(*) DESC, campanha.id
LIMIT 1 \gset
SELECT diaria.anuncio_id AS anuncio_id
FROM normalizado.metrica_diaria_anuncio AS diaria
WHERE diaria.empresa_id = :'empresa_id' AND diaria.data BETWEEN :'inicio_mes_passado' AND :'fim_mes_passado'
GROUP BY diaria.anuncio_id
ORDER BY count(*) DESC, diaria.anuncio_id
LIMIT 1 \gset

CREATE TEMPORARY TABLE cenario (ordem integer PRIMARY KEY, descricao text NOT NULL, chamada text NOT NULL);
INSERT INTO cenario (ordem, descricao, chamada)
SELECT
  row_number() OVER (),
  caso.descricao,
  format(
    'SELECT * FROM analitico.obter_desempenho(%L, %L, %L, %L, %L, %L, %L)',
    :'token', :'empresa_id', caso.nivel, caso.entidade_id, caso.inicio, caso.fim, caso.granularidade
  )
FROM (
  VALUES
    ('obter_desempenho · geral · últimos 30 dias · dia', 'geral', NULL, :'inicio_30_dias', :'ontem', 'dia'),
    ('obter_desempenho · geral · este mês · período', 'geral', NULL, :'inicio_mes', :'hoje', 'periodo'),
    ('obter_desempenho · geral · mês passado · período', 'geral', NULL, :'inicio_mes_passado', :'fim_mes_passado', 'periodo'),
    ('obter_desempenho · geral · este ano · mês', 'geral', NULL, :'inicio_ano', :'hoje', 'mes'),
    ('obter_desempenho · geral · 37 meses · mês', 'geral', NULL, :'inicio_historico', :'hoje', 'mes'),
    ('obter_desempenho · geral · 37 meses · semana', 'geral', NULL, :'inicio_historico', :'hoje', 'semana'),
    ('obter_desempenho · geral · 37 meses · dia', 'geral', NULL, :'inicio_historico', :'hoje', 'dia'),
    ('obter_desempenho · conta · últimos 30 dias · período', 'conta', :'conta_id', :'inicio_30_dias', :'ontem', 'periodo'),
    ('obter_desempenho · conta · este ano · semana', 'conta', :'conta_id', :'inicio_ano', :'hoje', 'semana'),
    ('obter_desempenho · conta · 37 meses · dia', 'conta', :'conta_id', :'inicio_historico', :'hoje', 'dia'),
    ('obter_desempenho · campanha · este ano · período', 'campanha', :'campanha_id', :'inicio_ano', :'hoje', 'periodo'),
    ('obter_desempenho · campanha · este ano · dia', 'campanha', :'campanha_id', :'inicio_ano', :'hoje', 'dia'),
    ('obter_desempenho · anúncio · mês passado · dia', 'anuncio', :'anuncio_id', :'inicio_mes_passado', :'fim_mes_passado', 'dia'),
    ('obter_desempenho · anúncio · 37 meses · mês', 'anuncio', :'anuncio_id', :'inicio_historico', :'hoje', 'mes')
) AS caso (descricao, nivel, entidade_id, inicio, fim, granularidade);

-- As demais funções, depois das de desempenho, com as mesmas entidades em
-- foco.
INSERT INTO cenario (ordem, descricao, chamada)
SELECT (SELECT max(anterior.ordem) FROM cenario AS anterior) + row_number() OVER (), caso.descricao, caso.chamada
FROM (
  VALUES
    ('obter_trilha · geral', format('SELECT * FROM analitico.obter_trilha(%L, %L, %L, NULL)', :'token', :'empresa_id', 'geral')),
    (
      'obter_trilha · anúncio',
      format('SELECT * FROM analitico.obter_trilha(%L, %L, %L, %L)', :'token', :'empresa_id', 'anuncio', :'anuncio_id')
    ),
    ('listar_entidades · geral', format('SELECT * FROM analitico.listar_entidades(%L, %L, %L, NULL)', :'token', :'empresa_id', 'geral')),
    (
      'listar_entidades · conta',
      format('SELECT * FROM analitico.listar_entidades(%L, %L, %L, %L)', :'token', :'empresa_id', 'conta', :'conta_id')
    ),
    (
      'listar_entidades · campanha',
      format('SELECT * FROM analitico.listar_entidades(%L, %L, %L, %L)', :'token', :'empresa_id', 'campanha', :'campanha_id')
    ),
    ('listar_metricas', format('SELECT * FROM analitico.listar_metricas(%L)', :'token'))
) AS caso (descricao, chamada);

-- Executa a chamada e consome todas as linhas, sem enviá-las ao cliente. O
-- p95 é por posto mais próximo: a 19ª de 20 durações em ordem crescente.
CREATE FUNCTION pg_temp.medir(p_chamada text, p_execucoes integer)
RETURNS TABLE (p50_ms numeric, p95_ms numeric, maximo_ms numeric, linhas bigint)
LANGUAGE plpgsql
AS $$
DECLARE
  inicio timestamptz;
  duracao numeric[] := '{}';
  contagem bigint;
BEGIN
  FOR execucao IN 1..p_execucoes LOOP
    inicio := clock_timestamp();
    EXECUTE format('SELECT count(*) FROM (%s) AS chamada', p_chamada) INTO contagem;
    duracao := duracao || (extract(epoch FROM clock_timestamp() - inicio) * 1000)::numeric;
  END LOOP;
  RETURN QUERY
  SELECT
    round(percentile_disc(0.5) WITHIN GROUP (ORDER BY ms), 1),
    round(percentile_disc(0.95) WITHIN GROUP (ORDER BY ms), 1),
    round(max(ms), 1),
    contagem
  FROM unnest(duracao) AS ms;
END
$$;

SELECT
  cenario.descricao AS cenario,
  medicao.linhas,
  medicao.p50_ms,
  medicao.p95_ms,
  medicao.maximo_ms,
  medicao.p95_ms <= :LIMITE_P95_MS AS atende_rnf_06
FROM cenario
CROSS JOIN LATERAL pg_temp.medir(cenario.chamada, :EXECUCOES) AS medicao
ORDER BY cenario.ordem;

ROLLBACK;

-- De baixo para cima, porque as FKs não apagam em cascata (ADR-0009 §1); as
-- ações saem com o fato a que pertencem.
\if :carregar_massa
  BEGIN;
  CREATE TEMPORARY TABLE empresa_massa ON COMMIT DROP AS
  SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Exemplo Referência';
  DELETE FROM normalizado.alcance_periodo WHERE empresa_id IN (SELECT id FROM empresa_massa);
  DELETE FROM normalizado.quebra_diaria_campanha WHERE empresa_id IN (SELECT id FROM empresa_massa);
  DELETE FROM normalizado.metrica_diaria_anuncio WHERE empresa_id IN (SELECT id FROM empresa_massa);
  DELETE FROM normalizado.anuncio WHERE empresa_id IN (SELECT id FROM empresa_massa);
  DELETE FROM normalizado.criativo WHERE empresa_id IN (SELECT id FROM empresa_massa);
  DELETE FROM normalizado.conjunto_anuncio WHERE empresa_id IN (SELECT id FROM empresa_massa);
  DELETE FROM normalizado.campanha WHERE empresa_id IN (SELECT id FROM empresa_massa);
  DELETE FROM normalizado.pagina WHERE empresa_id IN (SELECT id FROM empresa_massa);
  DELETE FROM normalizado.conta_anuncio WHERE empresa_id IN (SELECT id FROM empresa_massa);
  DELETE FROM normalizado.execucao_carga WHERE empresa_id IN (SELECT id FROM empresa_massa);
  DELETE FROM normalizado.empresa WHERE id IN (SELECT id FROM empresa_massa);
  COMMIT;
\endif
