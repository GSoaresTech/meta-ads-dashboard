-- Prova os tipos de resultado de uma empresa num intervalo: o resultado
-- principal resolvido das campanhas com entrega, em cada moeda, de onde vêm
-- os totais da visão Geral (REQUIREMENTS §3.1 e §3.3; RF-34; RNF-14;
-- ADR-0013).
BEGIN;
SELECT plan(16);

-- Atributos: o painel_leitor só executa, e a função roda com os privilégios
-- do postgres, com search_path vazio (ADR-0009 §3 e §4).
SELECT has_function(
  'analitico', 'listar_resultados', ARRAY['text', 'uuid', 'date', 'date'],
  'analitico.listar_resultados existe com a assinatura do ADR-0009 §4'
);
SELECT results_eq(
  $$
  SELECT p.provolatile = 's', p.prosecdef, p.proconfig::text = '{"search_path=\"\""}'
  FROM pg_catalog.pg_proc AS p
  WHERE p.oid = 'analitico.listar_resultados(text, uuid, date, date)'::regprocedure
  $$,
  $$ VALUES (true, true, true) $$,
  'a função é STABLE, SECURITY DEFINER e com search_path vazio'
);
SELECT is(
  pg_get_function_result('analitico.listar_resultados(text, uuid, date, date)'::regprocedure),
  'TABLE(moeda text, metrica text)',
  'uma linha por moeda e tipo de resultado'
);
SELECT ok(
  has_function_privilege('painel_leitor', 'analitico.listar_resultados(text, uuid, date, date)', 'EXECUTE'),
  'painel_leitor executa analitico.listar_resultados'
);
SELECT ok(
  NOT has_function_privilege('etl_carga', 'analitico.listar_resultados(text, uuid, date, date)', 'EXECUTE'),
  'etl_carga não executa analitico.listar_resultados'
);

-- A empresa A tem uma conta em BRL e outra em USD. Em BRL: vendas com entrega
-- em setembro e em outubro, cadastros só em setembro, duas campanhas de
-- conversas em outubro, uma de vídeo sem resultado principal no catálogo e um
-- tráfego sobrescrito para cadastros, em outubro. Em USD: vendas em outubro. A
-- empresa B tem tráfego em outubro, que nunca pode aparecer para A.
INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A'), ('Empresa Teste B');
INSERT INTO normalizado.execucao_carga (empresa_id, tipo)
SELECT id, 'diaria' FROM normalizado.empresa WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');
INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, nome, fuso_horario, moeda, execucao_id)
SELECT x.empresa_id, v.id_meta, v.nome, 'America/Sao_Paulo', v.moeda, x.id
FROM (
  VALUES
    ('Empresa Teste A', '611111111111111', 'Conta Teste Real', 'BRL'),
    ('Empresa Teste A', '611111111111112', 'Conta Teste Dólar', 'USD'),
    ('Empresa Teste B', '622222222222221', 'Conta Teste B', 'BRL')
) AS v (empresa, id_meta, nome, moeda)
JOIN normalizado.empresa AS e ON e.nome = v.empresa
JOIN normalizado.execucao_carga AS x ON x.empresa_id = e.id;
INSERT INTO normalizado.criativo (empresa_id, conta_anuncio_id, id_meta, execucao_id)
SELECT empresa_id, id, id_meta || '9', execucao_id FROM normalizado.conta_anuncio;
INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, nome, objetivo, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, v.nome, v.objetivo, 'ACTIVE', c.execucao_id
FROM (
  VALUES
    ('611111111111111', '620000000000000001', 'Campanha Teste Vendas', 'OUTCOME_SALES'),
    ('611111111111111', '620000000000000002', 'Campanha Teste Cadastros', 'OUTCOME_LEADS'),
    ('611111111111111', '620000000000000003', 'Campanha Teste Conversas Um', 'OUTCOME_ENGAGEMENT'),
    ('611111111111111', '620000000000000004', 'Campanha Teste Conversas Dois', 'OUTCOME_ENGAGEMENT'),
    ('611111111111111', '620000000000000005', 'Campanha Teste Vídeo', 'OUTCOME_ENGAGEMENT'),
    ('611111111111111', '620000000000000006', 'Campanha Teste Sobrescrita', 'OUTCOME_TRAFFIC'),
    ('611111111111112', '620000000000000007', 'Campanha Teste Vendas Dólar', 'OUTCOME_SALES'),
    ('622222222222221', '620000000000000008', 'Campanha Teste B', 'OUTCOME_TRAFFIC')
) AS v (conta, id_meta, nome, objetivo)
JOIN normalizado.conta_anuncio AS c ON c.id_meta = v.conta;
INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, meta_otimizacao, status, execucao_id)
SELECT c.empresa_id, c.id, '63' || right(c.id_meta, 16),
  CASE
    WHEN c.nome LIKE 'Campanha Teste Conversas%' THEN 'CONVERSATIONS'
    WHEN c.nome = 'Campanha Teste Vídeo' THEN 'THRUPLAY'
  END,
  'ACTIVE', c.execucao_id
FROM normalizado.campanha AS c
JOIN normalizado.empresa AS e ON e.id = c.empresa_id
WHERE e.nome IN ('Empresa Teste A', 'Empresa Teste B');
INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, nome, status, execucao_id)
SELECT j.empresa_id, j.id, k.id, '65' || right(j.id_meta, 16), 'Anúncio de ' || c.nome, 'ACTIVE', j.execucao_id
FROM normalizado.conjunto_anuncio AS j
JOIN normalizado.campanha AS c ON c.empresa_id = j.empresa_id AND c.id = j.campanha_id
JOIN normalizado.criativo AS k ON k.empresa_id = c.empresa_id AND k.conta_anuncio_id = c.conta_anuncio_id
JOIN normalizado.empresa AS e ON e.id = c.empresa_id
WHERE e.nome IN ('Empresa Teste A', 'Empresa Teste B');
INSERT INTO normalizado.metrica_diaria_anuncio (empresa_id, anuncio_id, data, investimento, impressoes, execucao_id)
SELECT a.empresa_id, a.id, v.data::date, 10.00, 100, a.execucao_id
FROM (
  VALUES
    ('Anúncio de Campanha Teste Vendas', '2026-09-15'),
    ('Anúncio de Campanha Teste Vendas', '2026-10-15'),
    ('Anúncio de Campanha Teste Cadastros', '2026-09-15'),
    ('Anúncio de Campanha Teste Conversas Um', '2026-10-15'),
    ('Anúncio de Campanha Teste Conversas Dois', '2026-10-16'),
    ('Anúncio de Campanha Teste Vídeo', '2026-10-15'),
    ('Anúncio de Campanha Teste Sobrescrita', '2026-10-15'),
    ('Anúncio de Campanha Teste Vendas Dólar', '2026-10-15'),
    ('Anúncio de Campanha Teste B', '2026-10-15')
) AS v (anuncio, data)
JOIN normalizado.anuncio AS a ON a.nome = v.anuncio;
INSERT INTO normalizado.sobrescrita_resultado_campanha (empresa_id, campanha_id, metrica_resultado, metrica_kpi)
SELECT empresa_id, id, 'cadastros', 'custo_cadastro'
FROM normalizado.campanha WHERE id_meta = '620000000000000006';

-- Credenciais geradas pela função do banco, a cada execução, para que
-- nenhum token fique no repositório.
CREATE TEMPORARY TABLE credencial_teste (caso text PRIMARY KEY, token text NOT NULL);
INSERT INTO credencial_teste (caso, token)
SELECT v.caso, normalizado.gerar_credencial(v.escopo, e.id)
FROM (
  VALUES
    ('empresa_a', 'empresa', 'Empresa Teste A'),
    ('empresa_a_revogada', 'empresa', 'Empresa Teste A'),
    ('operador', 'operador', NULL)
) AS v (caso, escopo, empresa)
LEFT JOIN normalizado.empresa AS e ON e.nome = v.empresa;
UPDATE normalizado.credencial_acesso
SET revogado_em = now()
WHERE hash = (SELECT sha256(convert_to(token, 'UTF8')) FROM credencial_teste WHERE caso = 'empresa_a_revogada');

CREATE FUNCTION pg_temp.resultados(p_caso text, p_empresa text, p_inicio date, p_fim date)
RETURNS TABLE (moeda text, metrica text)
LANGUAGE sql STABLE AS $$
  SELECT *
  FROM analitico.listar_resultados(
    (SELECT token FROM credencial_teste WHERE caso = p_caso),
    (SELECT id FROM normalizado.empresa WHERE nome = p_empresa),
    p_inicio,
    p_fim
  )
$$;

-- Parâmetros fora do domínio levantam 22023, mesmo com credencial válida
-- (ADR-0009 §4).
SELECT throws_ok(
  format($$ SELECT * FROM pg_temp.resultados('empresa_a', 'Empresa Teste A', %L, %L) $$, inicio, fim),
  '22023',
  NULL,
  descricao
)
FROM (
  VALUES
    (NULL, '2026-10-31', 'início nulo é recusado'),
    ('2026-10-01', NULL, 'fim nulo é recusado'),
    ('2026-10-31', '2026-10-01', 'início depois do fim é recusado')
) AS caso (inicio, fim, descricao);

-- Um tipo por moeda, sem repetir o das duas campanhas de conversas. A de
-- vídeo, sem resultado principal no catálogo, não gera linha, e a
-- sobrescrita vale no lugar da regra do objetivo: o tráfego conta como
-- cadastros.
SELECT results_eq(
  $$ SELECT * FROM pg_temp.resultados('empresa_a', 'Empresa Teste A', '2026-10-01', '2026-10-31') $$,
  $$
  VALUES
    ('BRL', 'cadastros'),
    ('BRL', 'compras'),
    ('BRL', 'conversas_iniciadas'),
    ('USD', 'compras')
  $$,
  'cada moeda lista os resultados das campanhas com entrega, em ordem'
);

-- A campanha sem entrega no intervalo não conta: em setembro, os cadastros
-- vêm da campanha de cadastros, e em BRL ficam só os dois tipos daquele mês.
SELECT results_eq(
  $$ SELECT * FROM pg_temp.resultados('empresa_a', 'Empresa Teste A', '2026-09-01', '2026-09-30') $$,
  $$ VALUES ('BRL', 'cadastros'), ('BRL', 'compras') $$,
  'só as campanhas com entrega no intervalo definem os tipos'
);
SELECT results_eq(
  $$ SELECT * FROM pg_temp.resultados('empresa_a', 'Empresa Teste A', '2026-10-16', '2026-10-16') $$,
  $$ VALUES ('BRL', 'conversas_iniciadas') $$,
  'os dois extremos do intervalo são inclusivos'
);
SELECT is_empty(
  $$ SELECT * FROM pg_temp.resultados('empresa_a', 'Empresa Teste A', '2026-08-01', '2026-08-31') $$,
  'o intervalo sem entrega não tem tipos'
);

-- RNF-14: a credencial de uma empresa nunca devolve linha de outra, e o
-- acesso negado devolve zero linhas, sem erro (ADR-0009 §4).
SELECT is_empty(
  format($$ SELECT * FROM pg_temp.resultados(%L, %L, '2026-10-01', '2026-10-31') $$, caso, empresa),
  descricao
)
FROM (
  VALUES
    ('empresa_a', 'Empresa Teste B', 'a credencial de A não lista os resultados de B'),
    ('empresa_a_revogada', 'Empresa Teste A', 'a credencial revogada não devolve nada')
) AS caso (caso, empresa, descricao);
SELECT is_empty(
  $$
  SELECT *
  FROM analitico.listar_resultados(
    'token que não é de nenhuma credencial',
    (SELECT id FROM normalizado.empresa WHERE nome = 'Empresa Teste A'),
    '2026-10-01',
    '2026-10-31'
  )
  $$,
  'a credencial inexistente não devolve nada'
);

-- O operador lê qualquer empresa (ADR-0004).
SELECT results_eq(
  $$ SELECT * FROM pg_temp.resultados('operador', 'Empresa Teste B', '2026-10-01', '2026-10-31') $$,
  $$ VALUES ('BRL', 'cliques_link') $$,
  'o operador lista os resultados de outra empresa'
);

SELECT * FROM finish();
ROLLBACK;
