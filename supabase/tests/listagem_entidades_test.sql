-- Prova a listagem das entidades filhas: os parâmetros, o isolamento entre
-- empresas e as contas, campanhas ou anúncios abaixo da entidade em foco,
-- de onde o painel desce de nível (RF-23; RNF-14; ADR-0009 §4).
BEGIN;
SELECT plan(20);

-- Atributos: o painel_leitor só executa, e a função roda com os privilégios
-- do postgres, com search_path vazio (ADR-0009 §3 e §4).
SELECT has_function(
  'analitico', 'listar_entidades', ARRAY['text', 'uuid', 'text', 'uuid'],
  'analitico.listar_entidades existe com a assinatura do ADR-0009 §4'
);
SELECT results_eq(
  $$
  SELECT p.provolatile = 's', p.prosecdef, p.proconfig::text = '{"search_path=\"\""}'
  FROM pg_catalog.pg_proc AS p
  WHERE p.oid = 'analitico.listar_entidades(text, uuid, text, uuid)'::regprocedure
  $$,
  $$ VALUES (true, true, true) $$,
  'a função é STABLE, SECURITY DEFINER e com search_path vazio'
);
SELECT is(
  pg_get_function_result('analitico.listar_entidades(text, uuid, text, uuid)'::regprocedure),
  'TABLE(nivel text, entidade_id uuid, nome text)',
  'uma linha por entidade filha, com o nível e o nome'
);
SELECT ok(
  has_function_privilege('painel_leitor', 'analitico.listar_entidades(text, uuid, text, uuid)', 'EXECUTE'),
  'painel_leitor executa analitico.listar_entidades'
);
SELECT ok(
  NOT has_function_privilege('etl_carga', 'analitico.listar_entidades(text, uuid, text, uuid)', 'EXECUTE'),
  'etl_carga não executa analitico.listar_entidades'
);

-- A empresa A tem três contas, uma ainda sem nome. A primeira tem duas
-- campanhas, e a primeira delas, dois conjuntos, cada um com um anúncio. A
-- empresa B tem uma conta com campanha e anúncio, que nunca podem aparecer
-- para a credencial de A.
INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A'), ('Empresa Teste B');
INSERT INTO normalizado.execucao_carga (empresa_id, tipo)
SELECT id, 'diaria' FROM normalizado.empresa WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');
INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, nome, fuso_horario, moeda, execucao_id)
SELECT x.empresa_id, v.id_meta, v.nome, v.fuso_horario, v.moeda, x.id
FROM (
  VALUES
    ('Empresa Teste A', '511111111111111', 'Conta Teste Beta', 'America/Sao_Paulo', 'BRL'),
    ('Empresa Teste A', '511111111111112', 'Conta Teste Alfa', 'America/Sao_Paulo', 'BRL'),
    ('Empresa Teste A', '511111111111113', NULL, NULL, NULL),
    ('Empresa Teste B', '522222222222221', 'Conta Teste B', 'America/Sao_Paulo', 'BRL')
) AS v (empresa, id_meta, nome, fuso_horario, moeda)
JOIN normalizado.empresa AS e ON e.nome = v.empresa
JOIN normalizado.execucao_carga AS x ON x.empresa_id = e.id;
INSERT INTO normalizado.criativo (empresa_id, conta_anuncio_id, id_meta, execucao_id)
SELECT empresa_id, id, id_meta || '9', execucao_id FROM normalizado.conta_anuncio
WHERE id_meta IN ('511111111111111', '522222222222221');
INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, nome, objetivo, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, v.nome, 'OUTCOME_SALES', 'ACTIVE', c.execucao_id
FROM (
  VALUES
    ('511111111111111', '520000000000000001', 'Campanha Teste Zeta'),
    ('511111111111111', '520000000000000002', 'Campanha Teste Eta'),
    ('522222222222221', '520000000000000003', 'Campanha Teste B')
) AS v (conta, id_meta, nome)
JOIN normalizado.conta_anuncio AS c ON c.id_meta = v.conta;
INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, 'ACTIVE', c.execucao_id
FROM (
  VALUES
    ('520000000000000001', '530000000000000001'),
    ('520000000000000001', '530000000000000002'),
    ('520000000000000002', '530000000000000003'),
    ('520000000000000003', '530000000000000004')
) AS v (campanha, id_meta)
JOIN normalizado.campanha AS c ON c.id_meta = v.campanha;
INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, nome, status, execucao_id)
SELECT j.empresa_id, j.id, k.id, v.id_meta, v.nome, 'ACTIVE', j.execucao_id
FROM (
  VALUES
    ('530000000000000001', '550000000000000001', 'Anúncio Teste Um'),
    ('530000000000000002', '550000000000000002', 'Anúncio Teste Dois'),
    ('530000000000000003', '550000000000000003', 'Anúncio Teste Três'),
    ('530000000000000004', '550000000000000004', 'Anúncio Teste B')
) AS v (conjunto, id_meta, nome)
JOIN normalizado.conjunto_anuncio AS j ON j.id_meta = v.conjunto
JOIN normalizado.campanha AS c ON c.empresa_id = j.empresa_id AND c.id = j.campanha_id
JOIN normalizado.criativo AS k ON k.empresa_id = c.empresa_id AND k.conta_anuncio_id = c.conta_anuncio_id;

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

-- A chamada e o retorno pelo nome da empresa e pelo ID da Meta das
-- entidades, que deixam os casos legíveis. A ordinalidade preserva a ordem
-- em que a função devolve as filhas, que a junção não garante.
CREATE TEMPORARY VIEW entidade_teste AS
SELECT id, id_meta FROM normalizado.conta_anuncio
UNION ALL SELECT id, id_meta FROM normalizado.campanha
UNION ALL SELECT id, id_meta FROM normalizado.anuncio;

CREATE FUNCTION pg_temp.filhas(p_caso text, p_empresa text, p_nivel text, p_id_meta_pai text)
RETURNS TABLE (nivel text, id_meta text, nome text)
LANGUAGE sql STABLE AS $$
  SELECT filha.nivel, entidade.id_meta, filha.nome
  FROM analitico.listar_entidades(
    (SELECT token FROM credencial_teste WHERE caso = p_caso),
    (SELECT id FROM normalizado.empresa WHERE nome = p_empresa),
    p_nivel,
    (SELECT id FROM entidade_teste WHERE id_meta = p_id_meta_pai)
  ) WITH ORDINALITY AS filha
  LEFT JOIN entidade_teste AS entidade ON entidade.id = filha.entidade_id
  ORDER BY filha.ordinality
$$;

-- Parâmetros fora do domínio levantam 22023, mesmo com credencial válida
-- (ADR-0009 §4).
SELECT throws_ok(
  format($$ SELECT * FROM pg_temp.filhas('empresa_a', 'Empresa Teste A', %L, %L) $$, nivel, id_meta),
  '22023',
  NULL,
  descricao
)
FROM (
  VALUES
    ('empresa', NULL, 'nível fora do domínio é recusado'),
    (NULL, NULL, 'nível nulo é recusado'),
    ('geral', '511111111111111', 'entidade pai no nível geral é recusada'),
    ('conta', NULL, 'nível conta sem entidade pai é recusado')
) AS caso (nivel, id_meta, descricao);

-- As filhas de cada nível, em ordem de nome, com as sem nome no fim.
SELECT results_eq(
  $$ SELECT * FROM pg_temp.filhas('empresa_a', 'Empresa Teste A', 'geral', NULL) $$,
  $$
  VALUES
    ('conta', '511111111111112', 'Conta Teste Alfa'),
    ('conta', '511111111111111', 'Conta Teste Beta'),
    ('conta', '511111111111113', NULL)
  $$,
  'o geral lista todas as contas da empresa'
);
SELECT results_eq(
  $$ SELECT * FROM pg_temp.filhas('empresa_a', 'Empresa Teste A', 'conta', '511111111111111') $$,
  $$
  VALUES
    ('campanha', '520000000000000002', 'Campanha Teste Eta'),
    ('campanha', '520000000000000001', 'Campanha Teste Zeta')
  $$,
  'a conta lista só as próprias campanhas'
);
SELECT results_eq(
  $$ SELECT * FROM pg_temp.filhas('empresa_a', 'Empresa Teste A', 'campanha', '520000000000000001') $$,
  $$
  VALUES
    ('anuncio', '550000000000000002', 'Anúncio Teste Dois'),
    ('anuncio', '550000000000000001', 'Anúncio Teste Um')
  $$,
  'a campanha lista os anúncios de todos os seus conjuntos'
);
SELECT is_empty(
  $$ SELECT * FROM pg_temp.filhas('empresa_a', 'Empresa Teste A', 'anuncio', '550000000000000001') $$,
  'o anúncio não tem filhas'
);

-- RNF-14: a credencial de uma empresa nunca devolve linha de outra. O
-- acesso negado e a entidade pai que não é da empresa ou do nível pedido
-- devolvem zero linhas, sem erro (ADR-0009 §4).
SELECT is_empty(
  format($$ SELECT * FROM pg_temp.filhas(%L, %L, %L, %L) $$, caso, empresa, nivel, id_meta),
  descricao
)
FROM (
  VALUES
    ('empresa_a', 'Empresa Teste B', 'geral', NULL, 'a credencial de A não lista as contas de B'),
    ('empresa_a', 'Empresa Teste B', 'campanha', '520000000000000003', 'a credencial de A não lista os anúncios de B'),
    ('empresa_a', 'Empresa Teste A', 'conta', '522222222222221', 'a conta de B não lista campanhas pela empresa A'),
    ('empresa_a', 'Empresa Teste A', 'campanha', '520000000000000003', 'a campanha de B não lista anúncios pela empresa A'),
    ('empresa_a', 'Empresa Teste A', 'conta', '520000000000000001', 'uma campanha não lista filhas como conta'),
    ('empresa_a_revogada', 'Empresa Teste A', 'geral', NULL, 'a credencial revogada não devolve nada')
) AS caso (caso, empresa, nivel, id_meta, descricao);

-- O operador lê qualquer empresa (ADR-0004).
SELECT results_eq(
  $$ SELECT * FROM pg_temp.filhas('operador', 'Empresa Teste B', 'campanha', '520000000000000003') $$,
  $$ VALUES ('anuncio', '550000000000000004', 'Anúncio Teste B') $$,
  'o operador lista as filhas de outra empresa'
);

SELECT * FROM finish();
ROLLBACK;
