-- Massa fictícia equivalente à empresa de referência do REQUIREMENTS §4.2: 2
-- contas, 6 campanhas ativas e 20 anúncios ativos por dia, com 37 meses de
-- histórico até hoje, nas cinco tabelas de fatos. Serve para medir o RNF-06
-- das funções de analitico e para desenvolver o painel com volume real. O
-- nome, os IDs e os textos são inventados (CLAUDE.md §4).
--
-- Só carrega no banco local, que tem o seed (ADR-0010). Não abre nem fecha
-- transação, para que quem a inclui escolha: o psql -1 e o script de medição
-- a carregam numa transação só, e ela fica no banco até o próximo
-- supabase db reset.
--
-- O volume segue a §4.2: a cada 6 meses entram 6 campanhas novas, que duram
-- 6 meses, e cada anúncio dura um mês. Cada dia de anúncio tem 25 tipos de
-- ação, e cada dia de campanha, 60 categorias de quebra. Com o sorteio de
-- semente fixa, a mesma data gera a mesma massa.
\set ON_ERROR_STOP on

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM normalizado.empresa WHERE nome = 'Empresa Exemplo') THEN
    RAISE EXCEPTION 'a massa fictícia só é carregada no banco local, que tem o seed (ADR-0010)';
  END IF;
  IF EXISTS (SELECT FROM normalizado.empresa WHERE nome = 'Empresa Exemplo Referência') THEN
    RAISE EXCEPTION 'a massa da empresa de referência já está carregada';
  END IF;
  PERFORM setseed(0.42);
END
$$;

-- O histórico começa no dia 1 do mês de 36 meses atrás: são 37 meses com o
-- corrente (R-19).
CREATE TEMPORARY TABLE parametro_massa AS
SELECT
  2 AS contas,
  6 AS meses_por_onda,
  20 AS anuncios_por_dia,
  (
    SELECT calendario.inicio_mes
    FROM normalizado.calendario AS calendario
    WHERE calendario.data = (current_date - interval '36 months')::date
  ) AS inicio,
  current_date AS fim;

-- Cada onda tem uma campanha por perfil, com o resultado principal que o
-- catálogo dá ao objetivo e à meta de otimização.
CREATE TEMPORARY TABLE perfil_campanha (posicao integer PRIMARY KEY, objetivo text NOT NULL, meta_otimizacao text NOT NULL);
INSERT INTO perfil_campanha VALUES
  (0, 'OUTCOME_ENGAGEMENT', 'CONVERSATIONS'),
  (1, 'OUTCOME_SALES', 'OFFSITE_CONVERSIONS'),
  (2, 'OUTCOME_LEADS', 'OFFSITE_CONVERSIONS'),
  (3, 'OUTCOME_TRAFFIC', 'LANDING_PAGE_VIEWS'),
  (4, 'OUTCOME_AWARENESS', 'REACH'),
  (5, 'OUTCOME_ENGAGEMENT', 'POST_ENGAGEMENT');

-- Os tipos de ação de cada dia de anúncio, com a taxa sobre as impressões.
-- Inclui os do catálogo e outros que a API devolve, como os de pixel (R-21).
CREATE TEMPORARY TABLE perfil_acao (tipo_acao text PRIMARY KEY, taxa numeric NOT NULL, com_valor boolean NOT NULL);
INSERT INTO perfil_acao VALUES
  ('link_click', 0.015, false),
  ('landing_page_view', 0.010, false),
  ('post_engagement', 0.030, false),
  ('page_engagement', 0.031, false),
  ('post_reaction', 0.010, false),
  ('comment', 0.001, false),
  ('post', 0.0005, false),
  ('like', 0.002, false),
  ('video_view', 0.050, false),
  ('photo_view', 0.005, false),
  ('onsite_conversion.messaging_conversation_started_7d', 0.002, false),
  ('onsite_conversion.messaging_first_reply', 0.0015, false),
  ('onsite_conversion.total_messaging_connection', 0.002, false),
  ('onsite_conversion.post_save', 0.001, false),
  ('lead', 0.001, false),
  ('offsite_conversion.fb_pixel_lead', 0.001, false),
  ('omni_purchase', 0.0005, true),
  ('offsite_conversion.fb_pixel_purchase', 0.0005, true),
  ('purchase', 0.0005, true),
  ('omni_add_to_cart', 0.002, true),
  ('offsite_conversion.fb_pixel_add_to_cart', 0.002, true),
  ('omni_initiated_checkout', 0.001, true),
  ('offsite_conversion.fb_pixel_initiate_checkout', 0.001, true),
  ('omni_view_content', 0.008, false),
  ('offsite_conversion.fb_pixel_view_content', 0.008, false);

-- As 60 categorias de cada dia de campanha, com os valores no formato da API.
CREATE TEMPORARY TABLE categoria_quebra (tipo_quebra text NOT NULL, categoria text NOT NULL, subcategoria text);
INSERT INTO categoria_quebra
SELECT 'idade_genero', idade, genero
FROM unnest(ARRAY['13-17', '18-24', '25-34', '35-44', '45-54', '55-64', '65+']) AS idade
CROSS JOIN unnest(ARRAY['female', 'male', 'unknown']) AS genero;
INSERT INTO categoria_quebra VALUES
  ('plataforma_posicionamento', 'facebook', 'feed'),
  ('plataforma_posicionamento', 'facebook', 'story'),
  ('plataforma_posicionamento', 'facebook', 'facebook_reels'),
  ('plataforma_posicionamento', 'facebook', 'marketplace'),
  ('plataforma_posicionamento', 'facebook', 'video_feeds'),
  ('plataforma_posicionamento', 'facebook', 'search'),
  ('plataforma_posicionamento', 'instagram', 'feed'),
  ('plataforma_posicionamento', 'instagram', 'story'),
  ('plataforma_posicionamento', 'instagram', 'instagram_reels'),
  ('plataforma_posicionamento', 'instagram', 'instagram_explore'),
  ('plataforma_posicionamento', 'instagram', 'profile_feed'),
  ('plataforma_posicionamento', 'messenger', 'messenger_inbox');
INSERT INTO categoria_quebra
SELECT 'regiao', regiao, NULL
FROM unnest(ARRAY[
  'Acre', 'Alagoas', 'Amapá', 'Amazonas', 'Bahia', 'Ceará', 'Distrito Federal', 'Espírito Santo', 'Goiás',
  'Maranhão', 'Mato Grosso', 'Mato Grosso do Sul', 'Minas Gerais', 'Pará', 'Paraíba', 'Paraná', 'Pernambuco',
  'Piauí', 'Rio de Janeiro', 'Rio Grande do Norte', 'Rio Grande do Sul', 'Rondônia', 'Roraima',
  'Santa Catarina', 'São Paulo', 'Sergipe', 'Tocantins'
]) AS regiao;

-- Os meses do histórico, numerados a partir de 0, e as ondas de campanhas.
CREATE TEMPORARY TABLE mes_massa AS
SELECT row_number() OVER (ORDER BY mes.inicio_mes) - 1 AS indice, mes.inicio_mes
FROM (
  SELECT DISTINCT calendario.inicio_mes
  FROM normalizado.calendario AS calendario
  CROSS JOIN parametro_massa AS parametro
  WHERE calendario.data BETWEEN parametro.inicio AND parametro.fim
) AS mes;

CREATE TEMPORARY TABLE campanha_massa AS
SELECT
  onda.indice AS onda,
  perfil.posicao,
  perfil.objetivo,
  perfil.meta_otimizacao,
  perfil.posicao % parametro.contas + 1 AS conta,
  lpad((onda.indice * 10 + perfil.posicao)::text, 12, '0') AS sufixo
FROM parametro_massa AS parametro
CROSS JOIN generate_series(0, (SELECT max(indice) FROM mes_massa)::integer / parametro.meses_por_onda) AS onda (indice)
CROSS JOIN perfil_campanha AS perfil;

-- Cada vaga de anúncio do dia pertence a uma campanha da onda do mês.
CREATE TEMPORARY TABLE anuncio_massa AS
SELECT
  mes.indice AS mes,
  mes.inicio_mes,
  campanha.sufixo AS sufixo_campanha,
  lpad((mes.indice * 100 + vaga.indice)::text, 12, '0') AS sufixo
FROM mes_massa AS mes
CROSS JOIN parametro_massa AS parametro
CROSS JOIN generate_series(0, parametro.anuncios_por_dia - 1) AS vaga (indice)
JOIN campanha_massa AS campanha
  ON campanha.onda = mes.indice::integer / parametro.meses_por_onda
 AND campanha.posicao = vaga.indice % (SELECT count(*) FROM perfil_campanha);

-- Empresa, execução e entidades. A onda e o mês correntes ficam ativos, e o
-- resto, arquivado.
INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Exemplo Referência');
INSERT INTO normalizado.execucao_carga (empresa_id, tipo, status, terminado_em)
SELECT id, 'historica', 'sucesso', now() FROM normalizado.empresa WHERE nome = 'Empresa Exemplo Referência';

CREATE TEMPORARY TABLE referencia AS
SELECT execucao.empresa_id, execucao.id AS execucao_id
FROM normalizado.execucao_carga AS execucao
JOIN normalizado.empresa AS empresa ON empresa.id = execucao.empresa_id
WHERE empresa.nome = 'Empresa Exemplo Referência';

INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, nome, fuso_horario, moeda, execucao_id)
SELECT referencia.empresa_id, '98000000000000' || conta, 'Conta Referência ' || conta, 'America/Sao_Paulo', 'BRL',
  referencia.execucao_id
FROM referencia
CROSS JOIN parametro_massa AS parametro
CROSS JOIN generate_series(1, parametro.contas) AS conta;

INSERT INTO normalizado.pagina (empresa_id, id_meta, nome, execucao_id)
SELECT empresa_id, '981000000000001', 'Página Referência', execucao_id FROM referencia;

INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, nome, objetivo, status, execucao_id)
SELECT
  referencia.empresa_id,
  conta.id,
  '982' || massa.sufixo,
  format('Campanha Referência %s.%s', massa.onda + 1, massa.posicao + 1),
  massa.objetivo,
  CASE WHEN massa.onda = (SELECT max(onda) FROM campanha_massa) THEN 'ACTIVE' ELSE 'ARCHIVED' END,
  referencia.execucao_id
FROM campanha_massa AS massa
CROSS JOIN referencia
JOIN normalizado.conta_anuncio AS conta ON conta.id_meta = '98000000000000' || massa.conta;

INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, nome, meta_otimizacao, status, execucao_id)
SELECT campanha.empresa_id, campanha.id, '983' || massa.sufixo, 'Conjunto ' || campanha.nome, massa.meta_otimizacao,
  campanha.status, campanha.execucao_id
FROM campanha_massa AS massa
JOIN normalizado.campanha AS campanha ON campanha.id_meta = '982' || massa.sufixo;

INSERT INTO normalizado.criativo (empresa_id, conta_anuncio_id, pagina_id, id_meta, titulo, texto, chamada_acao, execucao_id)
SELECT campanha.empresa_id, campanha.conta_anuncio_id, pagina.id, '985' || massa.sufixo,
  'Título fictício ' || massa.sufixo, 'Texto de anúncio fictício da empresa de referência.', 'LEARN_MORE',
  campanha.execucao_id
FROM anuncio_massa AS massa
JOIN normalizado.campanha AS campanha ON campanha.id_meta = '982' || massa.sufixo_campanha
JOIN normalizado.pagina AS pagina ON pagina.empresa_id = campanha.empresa_id;

INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, nome, status, execucao_id)
SELECT conjunto.empresa_id, conjunto.id, criativo.id, '984' || massa.sufixo, 'Anúncio Referência ' || massa.sufixo,
  CASE WHEN massa.mes = (SELECT max(indice) FROM mes_massa) THEN 'ACTIVE' ELSE 'ARCHIVED' END,
  conjunto.execucao_id
FROM anuncio_massa AS massa
JOIN normalizado.conjunto_anuncio AS conjunto ON conjunto.id_meta = '983' || massa.sufixo_campanha
JOIN normalizado.criativo AS criativo ON criativo.id_meta = '985' || massa.sufixo;

-- Dentro da transação, o autovacuum não vê as linhas novas, e sem
-- estatísticas o planejador escolhe junções aninhadas nas etapas seguintes.
ANALYZE normalizado.conta_anuncio, normalizado.pagina, normalizado.campanha, normalizado.conjunto_anuncio,
  normalizado.criativo, normalizado.anuncio;

-- Métricas diárias de cada anúncio em todos os dias do mês dele, até hoje.
-- As CTEs MATERIALIZED garantem um sorteio por linha, reaproveitado em
-- todas as colunas que dependem dele.
WITH dia AS MATERIALIZED (
  SELECT
    anuncio.empresa_id,
    anuncio.id AS anuncio_id,
    calendario.data,
    round((5 + random() * 75)::numeric, 2) AS investimento,
    (200 + random() * 7800)::bigint AS impressoes,
    anuncio.execucao_id
  FROM anuncio_massa AS massa
  CROSS JOIN parametro_massa AS parametro
  JOIN normalizado.anuncio AS anuncio ON anuncio.id_meta = '984' || massa.sufixo
  JOIN normalizado.calendario AS calendario
    ON calendario.inicio_mes = massa.inicio_mes AND calendario.data <= parametro.fim
)
INSERT INTO normalizado.metrica_diaria_anuncio (empresa_id, anuncio_id, data, investimento, impressoes, alcance, execucao_id)
SELECT dia.empresa_id, dia.anuncio_id, dia.data, dia.investimento, dia.impressoes,
  (dia.impressoes * (0.6 + random() * 0.3))::bigint, dia.execucao_id
FROM dia;

WITH acao AS MATERIALIZED (
  SELECT
    diaria.empresa_id,
    diaria.anuncio_id,
    diaria.data,
    perfil.tipo_acao,
    perfil.com_valor,
    greatest(1, (diaria.impressoes * perfil.taxa * (0.5 + random()))::bigint) AS quantidade,
    diaria.execucao_id
  FROM normalizado.metrica_diaria_anuncio AS diaria
  JOIN referencia ON referencia.empresa_id = diaria.empresa_id
  CROSS JOIN perfil_acao AS perfil
)
INSERT INTO normalizado.acao_diaria_anuncio (empresa_id, anuncio_id, data, tipo_acao, quantidade, valor, execucao_id)
SELECT acao.empresa_id, acao.anuncio_id, acao.data, acao.tipo_acao, acao.quantidade,
  CASE WHEN acao.com_valor THEN round(acao.quantidade * (50 + random() * 250)::numeric, 2) END,
  acao.execucao_id
FROM acao;

ANALYZE normalizado.metrica_diaria_anuncio, normalizado.acao_diaria_anuncio;

-- Quebras: cada dia de campanha é repartido entre as categorias de cada tipo
-- de quebra por pesos sorteados, de modo que a soma bata com a campanha.
WITH dia_campanha AS (
  SELECT conjunto.empresa_id, conjunto.campanha_id, diaria.data,
    sum(diaria.investimento) AS investimento, sum(diaria.impressoes) AS impressoes, diaria.execucao_id
  FROM normalizado.metrica_diaria_anuncio AS diaria
  JOIN referencia ON referencia.empresa_id = diaria.empresa_id
  JOIN normalizado.anuncio AS anuncio ON anuncio.empresa_id = diaria.empresa_id AND anuncio.id = diaria.anuncio_id
  JOIN normalizado.conjunto_anuncio AS conjunto
    ON conjunto.empresa_id = anuncio.empresa_id AND conjunto.id = anuncio.conjunto_anuncio_id
  GROUP BY conjunto.empresa_id, conjunto.campanha_id, diaria.data, diaria.execucao_id
),
sorteio AS MATERIALIZED (
  SELECT dia_campanha.*, categoria.tipo_quebra, categoria.categoria, categoria.subcategoria, random()::numeric AS peso
  FROM dia_campanha
  CROSS JOIN categoria_quebra AS categoria
),
parcela AS (
  SELECT sorteio.*, sorteio.peso / sum(sorteio.peso) OVER (PARTITION BY sorteio.campanha_id, sorteio.data, sorteio.tipo_quebra) AS fracao
  FROM sorteio
)
INSERT INTO normalizado.quebra_diaria_campanha
  (empresa_id, campanha_id, data, tipo_quebra, categoria, subcategoria, investimento, impressoes, alcance, execucao_id)
SELECT parcela.empresa_id, parcela.campanha_id, parcela.data, parcela.tipo_quebra, parcela.categoria, parcela.subcategoria,
  round(parcela.investimento * parcela.fracao, 2),
  (parcela.impressoes * parcela.fracao)::bigint,
  (parcela.impressoes * parcela.fracao * 0.7)::bigint,
  parcela.execucao_id
FROM parcela;

ANALYZE normalizado.quebra_diaria_campanha;

-- Ações das quebras: só o tipo do resultado principal de cada campanha, pela
-- mesma resolução da carga, repartido como o investimento (ADR-0011).
WITH resultado AS (
  SELECT resolvido.campanha_id, metrica.tipo_acao
  FROM normalizado.resolver_resultado_campanha((SELECT empresa_id FROM referencia)) AS resolvido
  JOIN normalizado.metrica AS metrica ON metrica.codigo = resolvido.metrica_resultado
  WHERE metrica.tipo = 'acao'
),
acao_dia AS (
  SELECT conjunto.campanha_id, acao.data, acao.tipo_acao, sum(acao.quantidade) AS quantidade, sum(acao.valor) AS valor
  FROM normalizado.acao_diaria_anuncio AS acao
  JOIN referencia ON referencia.empresa_id = acao.empresa_id
  JOIN normalizado.anuncio AS anuncio ON anuncio.empresa_id = acao.empresa_id AND anuncio.id = acao.anuncio_id
  JOIN normalizado.conjunto_anuncio AS conjunto
    ON conjunto.empresa_id = anuncio.empresa_id AND conjunto.id = anuncio.conjunto_anuncio_id
  JOIN resultado ON resultado.campanha_id = conjunto.campanha_id AND resultado.tipo_acao = acao.tipo_acao
  GROUP BY conjunto.campanha_id, acao.data, acao.tipo_acao
),
parcela AS (
  SELECT quebra.empresa_id, quebra.id, quebra.campanha_id, quebra.data, quebra.execucao_id,
    quebra.investimento / nullif(sum(quebra.investimento) OVER (PARTITION BY quebra.campanha_id, quebra.data, quebra.tipo_quebra), 0)
      AS fracao
  FROM normalizado.quebra_diaria_campanha AS quebra
  JOIN referencia ON referencia.empresa_id = quebra.empresa_id
)
INSERT INTO normalizado.acao_quebra_diaria_campanha (empresa_id, quebra_diaria_campanha_id, tipo_acao, quantidade, valor, execucao_id)
SELECT parcela.empresa_id, parcela.id, acao_dia.tipo_acao,
  round(acao_dia.quantidade * coalesce(parcela.fracao, 0))::bigint,
  round(acao_dia.valor * parcela.fracao, 2),
  parcela.execucao_id
FROM parcela
JOIN acao_dia ON acao_dia.campanha_id = parcela.campanha_id AND acao_dia.data = parcela.data;

ANALYZE normalizado.acao_quebra_diaria_campanha;

-- O último dia de cada semana ISO, mês e ano, pelo calendário. É tabela, e
-- não CTE, para que o planejador tenha estatísticas na junção abaixo.
CREATE TEMPORARY TABLE fim_periodo AS
SELECT 'semana' AS tipo_periodo, calendario.inicio_semana AS inicio_periodo, max(calendario.data) AS fim
FROM normalizado.calendario AS calendario GROUP BY calendario.inicio_semana
UNION ALL
SELECT 'mes', calendario.inicio_mes, max(calendario.data)
FROM normalizado.calendario AS calendario GROUP BY calendario.inicio_mes
UNION ALL
SELECT 'ano', make_date(calendario.ano, 1, 1), max(calendario.data)
FROM normalizado.calendario AS calendario GROUP BY calendario.ano;
ANALYZE fim_periodo;

-- Alcance por período de cada conta, campanha e anúncio com entrega na
-- semana ISO, no mês ou no ano, cortado em hoje. Os períodos que começam
-- antes do histórico ficam sem alcance, como na carga histórica (ADR-0006).
WITH dia AS (
  SELECT diaria.empresa_id, diaria.execucao_id, diaria.impressoes, diaria.alcance,
    campanha.conta_anuncio_id, campanha.id AS campanha_id, diaria.anuncio_id,
    calendario.inicio_semana, calendario.inicio_mes, make_date(calendario.ano, 1, 1) AS inicio_ano
  FROM normalizado.metrica_diaria_anuncio AS diaria
  JOIN referencia ON referencia.empresa_id = diaria.empresa_id
  JOIN normalizado.anuncio AS anuncio ON anuncio.empresa_id = diaria.empresa_id AND anuncio.id = diaria.anuncio_id
  JOIN normalizado.conjunto_anuncio AS conjunto
    ON conjunto.empresa_id = anuncio.empresa_id AND conjunto.id = anuncio.conjunto_anuncio_id
  JOIN normalizado.campanha AS campanha ON campanha.empresa_id = conjunto.empresa_id AND campanha.id = conjunto.campanha_id
  JOIN normalizado.calendario AS calendario ON calendario.data = diaria.data
),
periodo_entidade AS (
  SELECT dia.empresa_id, dia.execucao_id, dia.impressoes, dia.alcance, periodo.tipo_periodo, periodo.inicio_periodo,
    entidade.nivel, entidade.id
  FROM dia
  CROSS JOIN LATERAL (
    VALUES ('semana', dia.inicio_semana), ('mes', dia.inicio_mes), ('ano', dia.inicio_ano)
  ) AS periodo (tipo_periodo, inicio_periodo)
  CROSS JOIN LATERAL (
    VALUES ('conta', dia.conta_anuncio_id), ('campanha', dia.campanha_id), ('anuncio', dia.anuncio_id)
  ) AS entidade (nivel, id)
)
INSERT INTO normalizado.alcance_periodo
  (empresa_id, conta_anuncio_id, campanha_id, anuncio_id, tipo_periodo, inicio_periodo, fim_periodo, alcance, impressoes, execucao_id)
SELECT
  periodo_entidade.empresa_id,
  CASE WHEN periodo_entidade.nivel = 'conta' THEN periodo_entidade.id END,
  CASE WHEN periodo_entidade.nivel = 'campanha' THEN periodo_entidade.id END,
  CASE WHEN periodo_entidade.nivel = 'anuncio' THEN periodo_entidade.id END,
  periodo_entidade.tipo_periodo,
  periodo_entidade.inicio_periodo,
  least(fim_periodo.fim, parametro.fim),
  (sum(periodo_entidade.alcance) * 0.6)::bigint,
  sum(periodo_entidade.impressoes),
  periodo_entidade.execucao_id
FROM periodo_entidade
CROSS JOIN parametro_massa AS parametro
JOIN fim_periodo
  ON fim_periodo.tipo_periodo = periodo_entidade.tipo_periodo AND fim_periodo.inicio_periodo = periodo_entidade.inicio_periodo
WHERE periodo_entidade.inicio_periodo >= parametro.inicio
GROUP BY periodo_entidade.empresa_id, periodo_entidade.execucao_id, periodo_entidade.nivel, periodo_entidade.id,
  periodo_entidade.tipo_periodo, periodo_entidade.inicio_periodo, fim_periodo.fim, parametro.fim;

ANALYZE normalizado.alcance_periodo;

-- O volume carregado, para conferir com a §4.2.
SELECT tabela, linhas
FROM referencia
CROSS JOIN LATERAL (
  VALUES
    ('campanha', (SELECT count(*) FROM normalizado.campanha AS t WHERE t.empresa_id = referencia.empresa_id)),
    ('anuncio', (SELECT count(*) FROM normalizado.anuncio AS t WHERE t.empresa_id = referencia.empresa_id)),
    ('metrica_diaria_anuncio', (SELECT count(*) FROM normalizado.metrica_diaria_anuncio AS t WHERE t.empresa_id = referencia.empresa_id)),
    ('acao_diaria_anuncio', (SELECT count(*) FROM normalizado.acao_diaria_anuncio AS t WHERE t.empresa_id = referencia.empresa_id)),
    ('quebra_diaria_campanha', (SELECT count(*) FROM normalizado.quebra_diaria_campanha AS t WHERE t.empresa_id = referencia.empresa_id)),
    ('acao_quebra_diaria_campanha',
     (SELECT count(*) FROM normalizado.acao_quebra_diaria_campanha AS t WHERE t.empresa_id = referencia.empresa_id)),
    ('alcance_periodo', (SELECT count(*) FROM normalizado.alcance_periodo AS t WHERE t.empresa_id = referencia.empresa_id))
) AS volume (tabela, linhas);
