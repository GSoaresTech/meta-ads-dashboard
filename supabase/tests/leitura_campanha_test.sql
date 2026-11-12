-- Prova a leitura da campanha em foco: o objetivo e o status em rótulo de
-- negócio, o resultado principal e o KPI resolvidos e as métricas de apoio da
-- regra do catálogo, na ordem de exibição, com o isolamento entre empresas
-- (REQUIREMENTS §3.1; RF-31; RNF-14; ADR-0007; ADR-0009 §4).
BEGIN;
SELECT plan(17);

-- Atributos: o painel_leitor só executa, e a função roda com os privilégios
-- do postgres, com search_path vazio (ADR-0009 §3 e §4).
SELECT has_function(
  'analitico', 'obter_campanha', ARRAY['text', 'uuid', 'uuid'],
  'analitico.obter_campanha existe com a assinatura do ADR-0009 §4'
);
SELECT results_eq(
  $$
  SELECT p.provolatile = 's', p.prosecdef, p.proconfig::text = '{"search_path=\"\""}'
  FROM pg_catalog.pg_proc AS p
  WHERE p.oid = 'analitico.obter_campanha(text, uuid, uuid)'::regprocedure
  $$,
  $$ VALUES (true, true, true) $$,
  'a função é STABLE, SECURITY DEFINER e com search_path vazio'
);
SELECT is(
  pg_get_function_result('analitico.obter_campanha(text, uuid, uuid)'::regprocedure),
  'TABLE(objetivo text, status text, metrica_resultado text, metrica_kpi text, metricas_apoio text[])',
  'uma linha com o objetivo, o status, o resultado, o KPI e as métricas de apoio'
);
SELECT ok(
  has_function_privilege('painel_leitor', 'analitico.obter_campanha(text, uuid, uuid)', 'EXECUTE'),
  'painel_leitor executa analitico.obter_campanha'
);
SELECT ok(
  NOT has_function_privilege('etl_carga', 'analitico.obter_campanha(text, uuid, uuid)', 'EXECUTE'),
  'etl_carga não executa analitico.obter_campanha'
);

-- A empresa A tem uma conta com uma campanha de cada caso: vendas, conversas
-- pela meta de otimização do conjunto, uma sobrescrita e um objetivo
-- desconhecido da API. A empresa B tem uma campanha que nunca pode aparecer
-- para a credencial de A.
INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A'), ('Empresa Teste B');
INSERT INTO normalizado.execucao_carga (empresa_id, tipo)
SELECT id, 'diaria' FROM normalizado.empresa WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');
INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, nome, fuso_horario, moeda, execucao_id)
SELECT x.empresa_id, v.id_meta, v.nome, 'America/Sao_Paulo', 'BRL', x.id
FROM (
  VALUES
    ('Empresa Teste A', '511111111111111', 'Conta Teste A'),
    ('Empresa Teste B', '522222222222221', 'Conta Teste B')
) AS v (empresa, id_meta, nome)
JOIN normalizado.empresa AS e ON e.nome = v.empresa
JOIN normalizado.execucao_carga AS x ON x.empresa_id = e.id;
INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, nome, objetivo, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, v.nome, v.objetivo, v.status, c.execucao_id
FROM (
  VALUES
    ('511111111111111', '520000000000000001', 'Campanha Teste Vendas', 'OUTCOME_SALES', 'ACTIVE'),
    ('511111111111111', '520000000000000002', 'Campanha Teste Conversas', 'OUTCOME_ENGAGEMENT', 'PAUSED'),
    ('511111111111111', '520000000000000003', 'Campanha Teste Sobrescrita', 'OUTCOME_SALES', 'ARCHIVED'),
    ('511111111111111', '520000000000000004', 'Campanha Teste Desconhecida', 'OUTCOME_TESTE', 'DELETED'),
    ('522222222222221', '520000000000000005', 'Campanha Teste B', 'OUTCOME_SALES', 'ACTIVE')
) AS v (conta, id_meta, nome, objetivo, status)
JOIN normalizado.conta_anuncio AS c ON c.id_meta = v.conta;
INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, status, meta_otimizacao, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, 'ACTIVE', v.meta_otimizacao, c.execucao_id
FROM (
  VALUES
    ('520000000000000001', '530000000000000001', 'OFFSITE_CONVERSIONS'),
    ('520000000000000002', '530000000000000002', 'CONVERSATIONS'),
    ('520000000000000003', '530000000000000003', 'OFFSITE_CONVERSIONS'),
    ('520000000000000004', '530000000000000004', NULL),
    ('520000000000000005', '530000000000000005', 'OFFSITE_CONVERSIONS')
) AS v (campanha, id_meta, meta_otimizacao)
JOIN normalizado.campanha AS c ON c.id_meta = v.campanha;
INSERT INTO normalizado.sobrescrita_resultado_campanha (empresa_id, campanha_id, metrica_resultado, metrica_kpi)
SELECT empresa_id, id, 'conversas_iniciadas', 'custo_conversa'
FROM normalizado.campanha
WHERE id_meta = '520000000000000003';

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

-- A chamada pelo nome da empresa e pelo ID da Meta da campanha, que deixam
-- os casos legíveis.
CREATE FUNCTION pg_temp.campanha(p_caso text, p_empresa text, p_id_meta text)
RETURNS TABLE (objetivo text, status text, metrica_resultado text, metrica_kpi text, metricas_apoio text[])
LANGUAGE sql STABLE AS $$
  SELECT *
  FROM analitico.obter_campanha(
    (SELECT token FROM credencial_teste WHERE caso = p_caso),
    (SELECT id FROM normalizado.empresa WHERE nome = p_empresa),
    (
      SELECT id FROM normalizado.campanha WHERE id_meta = p_id_meta
      UNION ALL
      SELECT id FROM normalizado.conta_anuncio WHERE id_meta = p_id_meta
    )
  )
$$;

-- A campanha é obrigatória, mesmo com credencial válida (ADR-0009 §4).
SELECT throws_ok(
  $$ SELECT * FROM pg_temp.campanha('empresa_a', 'Empresa Teste A', NULL) $$,
  '22023',
  NULL,
  'a campanha nula é recusada'
);

-- RF-31: o resultado principal e o KPI vêm da resolução do catálogo, e as
-- métricas de apoio, da regra, na ordem de exibição. O objetivo e o status
-- saem em rótulo de negócio, nunca como o valor da API (RF-37).
SELECT results_eq(
  $$ SELECT * FROM pg_temp.campanha('empresa_a', 'Empresa Teste A', '520000000000000001') $$,
  $$ VALUES ('Vendas', 'Ativa', 'compras', 'custo_compra', ARRAY['valor_compras', 'roas', 'cliques_link']) $$,
  'a campanha de vendas destaca as compras e o custo por compra, com o apoio da regra'
);
SELECT results_eq(
  $$ SELECT * FROM pg_temp.campanha('empresa_a', 'Empresa Teste A', '520000000000000002') $$,
  $$ VALUES ('Conversas', 'Pausada', 'conversas_iniciadas', 'custo_conversa', ARRAY['cliques_link', 'ctr', 'cpm']) $$,
  'a meta de otimização do conjunto escolhe a regra de conversas'
);
-- A sobrescrita troca o resultado e o KPI, e o objetivo e as métricas de
-- apoio continuam os da regra (ADR-0009 §4).
SELECT results_eq(
  $$ SELECT * FROM pg_temp.campanha('empresa_a', 'Empresa Teste A', '520000000000000003') $$,
  $$ VALUES ('Vendas', 'Arquivada', 'conversas_iniciadas', 'custo_conversa', ARRAY['valor_compras', 'roas', 'cliques_link']) $$,
  'a sobrescrita troca o resultado e o KPI, mas não o objetivo nem o apoio'
);
SELECT results_eq(
  $$ SELECT * FROM pg_temp.campanha('empresa_a', 'Empresa Teste A', '520000000000000004') $$,
  $$ VALUES ('Não classificado', 'Excluída', NULL::text, NULL::text, ARRAY['investimento', 'impressoes', 'cliques_link']) $$,
  'a campanha "Não classificado" não tem resultado e traz o apoio da regra própria (§7.2)'
);
UPDATE normalizado.metrica_apoio_resultado SET ordem = ordem + 10
WHERE resultado_objetivo_id = (
  SELECT id FROM normalizado.resultado_objetivo WHERE objetivo = 'OUTCOME_SALES' AND meta_otimizacao IS NULL
) AND metrica = 'valor_compras';
SELECT results_eq(
  $$ SELECT metricas_apoio FROM pg_temp.campanha('empresa_a', 'Empresa Teste A', '520000000000000001') $$,
  $$ VALUES (ARRAY['roas', 'cliques_link', 'valor_compras']) $$,
  'mudar a ordem no catálogo muda a ordem das métricas de apoio (ADR-0007)'
);

-- RNF-14: a credencial de uma empresa nunca devolve linha de outra. O
-- acesso negado e a campanha que não é da empresa devolvem zero linhas, sem
-- erro (ADR-0009 §4).
SELECT is_empty(
  format($$ SELECT * FROM pg_temp.campanha(%L, %L, %L) $$, caso, empresa, id_meta),
  descricao
)
FROM (
  VALUES
    ('empresa_a', 'Empresa Teste B', '520000000000000005', 'a credencial de A não lê a campanha de B pela empresa B'),
    ('empresa_a', 'Empresa Teste A', '520000000000000005', 'a campanha de B não é lida pela empresa A'),
    ('empresa_a', 'Empresa Teste A', '511111111111111', 'uma conta não é lida como campanha'),
    ('empresa_a_revogada', 'Empresa Teste A', '520000000000000001', 'a credencial revogada não devolve nada'),
    ('operador', 'Empresa Teste A', '520000000000000005', 'nem o operador lê uma campanha por outra empresa')
) AS caso (caso, empresa, id_meta, descricao);

-- O operador lê qualquer empresa (ADR-0004).
SELECT results_eq(
  $$ SELECT objetivo, metrica_resultado FROM pg_temp.campanha('operador', 'Empresa Teste B', '520000000000000005') $$,
  $$ VALUES ('Vendas', 'compras') $$,
  'o operador lê a campanha de outra empresa'
);

SELECT * FROM finish();
ROLLBACK;
