-- Prova a função da trilha de navegação: os parâmetros, o isolamento entre
-- empresas, o caminho de Geral até a entidade em foco e os fusos que cada
-- nível abrange, de onde o painel calcula os atalhos de período (RF-23,
-- RF-26; RNF-14; REQUIREMENTS §3.3; ADR-0009 §4).
BEGIN;
SELECT plan(25);

-- Atributos: o painel_leitor só executa, e a função roda com os privilégios
-- do postgres, com search_path vazio (ADR-0009 §3 e §4).
SELECT has_function(
  'analitico', 'obter_trilha', ARRAY['text', 'uuid', 'text', 'uuid'],
  'analitico.obter_trilha existe com credencial, empresa, nível e entidade'
);
SELECT results_eq(
  $$
  SELECT p.provolatile = 's', p.prosecdef, p.proconfig::text = '{"search_path=\"\""}'
  FROM pg_catalog.pg_proc AS p
  WHERE p.oid = 'analitico.obter_trilha(text, uuid, text, uuid)'::regprocedure
  $$,
  $$ VALUES (true, true, true) $$,
  'a função é STABLE, SECURITY DEFINER e com search_path vazio'
);
SELECT is(
  pg_get_function_result('analitico.obter_trilha(text, uuid, text, uuid)'::regprocedure),
  'TABLE(nivel text, entidade_id uuid, nome text, fusos_horarios text[])',
  'uma linha por nível, do geral até a entidade em foco, com o nome e os fusos'
);
SELECT ok(
  has_function_privilege('painel_leitor', 'analitico.obter_trilha(text, uuid, text, uuid)', 'EXECUTE'),
  'painel_leitor executa analitico.obter_trilha'
);
SELECT ok(
  NOT has_function_privilege('etl_carga', 'analitico.obter_trilha(text, uuid, text, uuid)', 'EXECUTE'),
  'etl_carga não executa analitico.obter_trilha'
);

-- A empresa A tem duas contas em São Paulo, uma em Los Angeles e uma ainda
-- sem a primeira extração, sem nome, fuso nem moeda. A campanha e o anúncio
-- ficam na primeira conta. A empresa B tem uma conta com campanha e anúncio,
-- que nunca podem aparecer para a credencial de A.
INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A'), ('Empresa Teste B');
INSERT INTO normalizado.execucao_carga (empresa_id, tipo)
SELECT id, 'diaria' FROM normalizado.empresa WHERE nome IN ('Empresa Teste A', 'Empresa Teste B');
INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, nome, fuso_horario, moeda, execucao_id)
SELECT x.empresa_id, v.id_meta, v.nome, v.fuso_horario, v.moeda, x.id
FROM (
  VALUES
    ('Empresa Teste A', '411111111111111', 'Conta Teste Brasil', 'America/Sao_Paulo', 'BRL'),
    ('Empresa Teste A', '411111111111112', 'Conta Teste Brasil Dois', 'America/Sao_Paulo', 'BRL'),
    ('Empresa Teste A', '411111111111113', 'Conta Teste Pacífico', 'America/Los_Angeles', 'USD'),
    ('Empresa Teste A', '411111111111114', NULL, NULL, NULL),
    ('Empresa Teste B', '422222222222221', 'Conta Teste B', 'Europe/Lisbon', 'EUR')
) AS v (empresa, id_meta, nome, fuso_horario, moeda)
JOIN normalizado.empresa AS e ON e.nome = v.empresa
JOIN normalizado.execucao_carga AS x ON x.empresa_id = e.id;
INSERT INTO normalizado.criativo (empresa_id, conta_anuncio_id, id_meta, execucao_id)
SELECT empresa_id, id, id_meta || '9', execucao_id FROM normalizado.conta_anuncio
WHERE id_meta IN ('411111111111111', '422222222222221');
INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, nome, objetivo, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, v.nome, 'OUTCOME_SALES', 'ACTIVE', c.execucao_id
FROM (
  VALUES
    ('411111111111111', '420000000000000001', 'Campanha Teste A'),
    ('422222222222221', '420000000000000002', 'Campanha Teste B')
) AS v (conta, id_meta, nome)
JOIN normalizado.conta_anuncio AS c ON c.id_meta = v.conta;
INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, 'ACTIVE', c.execucao_id
FROM (
  VALUES ('420000000000000001', '430000000000000001'), ('420000000000000002', '430000000000000002')
) AS v (campanha, id_meta)
JOIN normalizado.campanha AS c ON c.id_meta = v.campanha;
INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, nome, status, execucao_id)
SELECT j.empresa_id, j.id, k.id, v.id_meta, v.nome, 'ACTIVE', j.execucao_id
FROM (
  VALUES
    ('430000000000000001', '450000000000000001', 'Anúncio Teste A'),
    ('430000000000000002', '450000000000000002', 'Anúncio Teste B')
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
    ('empresa_b', 'empresa', 'Empresa Teste B'),
    ('operador', 'operador', NULL)
) AS v (caso, escopo, empresa)
LEFT JOIN normalizado.empresa AS e ON e.nome = v.empresa;
UPDATE normalizado.credencial_acesso
SET revogado_em = now()
WHERE hash = (SELECT sha256(convert_to(token, 'UTF8')) FROM credencial_teste WHERE caso = 'empresa_a_revogada');

-- A chamada e o retorno pelo nome da empresa e pelo ID da Meta das
-- entidades, que deixam os casos legíveis. A ordinalidade preserva a ordem
-- em que a função devolve os níveis, que a junção não garante.
CREATE TEMPORARY VIEW entidade_teste AS
SELECT id, id_meta FROM normalizado.conta_anuncio
UNION ALL SELECT id, id_meta FROM normalizado.campanha
UNION ALL SELECT id, id_meta FROM normalizado.anuncio;

CREATE FUNCTION pg_temp.trilha(p_caso text, p_empresa text, p_nivel text, p_id_meta text)
RETURNS TABLE (nivel text, id_meta text, nome text, fusos_horarios text[])
LANGUAGE sql STABLE AS $$
  SELECT trilha.nivel, entidade.id_meta, trilha.nome, trilha.fusos_horarios
  FROM analitico.obter_trilha(
    (SELECT token FROM credencial_teste WHERE caso = p_caso),
    (SELECT id FROM normalizado.empresa WHERE nome = p_empresa),
    p_nivel,
    (SELECT id FROM entidade_teste WHERE id_meta = p_id_meta)
  ) WITH ORDINALITY AS trilha
  LEFT JOIN entidade_teste AS entidade ON entidade.id = trilha.entidade_id
  ORDER BY trilha.ordinality
$$;

-- Parâmetros fora do domínio levantam 22023, mesmo com credencial válida
-- (ADR-0009 §4).
SELECT throws_ok(
  format($$ SELECT * FROM pg_temp.trilha('empresa_a', 'Empresa Teste A', %L, %L) $$, nivel, id_meta),
  '22023',
  NULL,
  descricao
)
FROM (
  VALUES
    ('empresa', NULL, 'nível fora do domínio é recusado'),
    (NULL, NULL, 'nível nulo é recusado'),
    ('geral', '411111111111111', 'entidade no nível geral é recusada'),
    ('anuncio', NULL, 'nível anúncio sem entidade é recusado')
) AS caso (nivel, id_meta, descricao);

-- O caminho de cada nível, em ordem, do geral até a entidade em foco. O
-- geral abrange todas as contas da empresa, cada fuso uma vez, e os demais
-- níveis, só o fuso da conta deles (REQUIREMENTS §3.3).
SELECT results_eq(
  $$ SELECT * FROM pg_temp.trilha('empresa_a', 'Empresa Teste A', 'geral', NULL) $$,
  $$ VALUES ('geral', NULL::text, 'Empresa Teste A', '{America/Los_Angeles,America/Sao_Paulo}'::text[]) $$,
  'o geral traz o nome da empresa e os fusos distintos das contas, sem os nulos'
);
SELECT results_eq(
  $$ SELECT * FROM pg_temp.trilha('empresa_a', 'Empresa Teste A', 'conta', '411111111111113') $$,
  $$
  VALUES
    ('geral', NULL::text, 'Empresa Teste A', '{America/Los_Angeles,America/Sao_Paulo}'::text[]),
    ('conta', '411111111111113', 'Conta Teste Pacífico', '{America/Los_Angeles}')
  $$,
  'a conta vem depois do geral, só com o fuso dela'
);
SELECT results_eq(
  $$ SELECT * FROM pg_temp.trilha('empresa_a', 'Empresa Teste A', 'conta', '411111111111114') $$,
  $$
  VALUES
    ('geral', NULL::text, 'Empresa Teste A', '{America/Los_Angeles,America/Sao_Paulo}'::text[]),
    ('conta', '411111111111114', NULL, '{}')
  $$,
  'a conta ainda sem extração vem sem nome e sem fuso'
);
SELECT results_eq(
  $$ SELECT * FROM pg_temp.trilha('empresa_a', 'Empresa Teste A', 'campanha', '420000000000000001') $$,
  $$
  VALUES
    ('geral', NULL::text, 'Empresa Teste A', '{America/Los_Angeles,America/Sao_Paulo}'::text[]),
    ('conta', '411111111111111', 'Conta Teste Brasil', '{America/Sao_Paulo}'),
    ('campanha', '420000000000000001', 'Campanha Teste A', '{America/Sao_Paulo}')
  $$,
  'a campanha vem com a conta a que pertence e o fuso dela'
);
SELECT results_eq(
  $$ SELECT * FROM pg_temp.trilha('empresa_a', 'Empresa Teste A', 'anuncio', '450000000000000001') $$,
  $$
  VALUES
    ('geral', NULL::text, 'Empresa Teste A', '{America/Los_Angeles,America/Sao_Paulo}'::text[]),
    ('conta', '411111111111111', 'Conta Teste Brasil', '{America/Sao_Paulo}'),
    ('campanha', '420000000000000001', 'Campanha Teste A', '{America/Sao_Paulo}'),
    ('anuncio', '450000000000000001', 'Anúncio Teste A', '{America/Sao_Paulo}')
  $$,
  'o anúncio vem com a campanha e a conta, chegando a ele pelo conjunto'
);

-- RNF-14: a credencial de uma empresa nunca devolve linha de outra. O
-- acesso negado e a entidade que não é da empresa ou do nível pedido
-- devolvem zero linhas, sem erro, e o painel responde 404 (ADR-0009 §4).
SELECT is_empty(
  format($$ SELECT * FROM pg_temp.trilha(%L, %L, %L, %L) $$, caso, empresa, nivel, id_meta),
  descricao
)
FROM (
  VALUES
    ('empresa_a', 'Empresa Teste B', 'geral', NULL, 'a credencial de A não abre o geral de B'),
    ('empresa_a', 'Empresa Teste B', 'conta', '422222222222221', 'a credencial de A não abre a conta de B'),
    ('empresa_a', 'Empresa Teste B', 'anuncio', '450000000000000002', 'a credencial de A não abre o anúncio de B'),
    ('empresa_a', 'Empresa Teste A', 'conta', '422222222222221', 'a conta de B não aparece pela empresa A'),
    ('empresa_a', 'Empresa Teste A', 'campanha', '420000000000000002', 'a campanha de B não aparece pela empresa A'),
    ('empresa_a', 'Empresa Teste A', 'anuncio', '450000000000000002', 'o anúncio de B não aparece pela empresa A'),
    ('empresa_a', 'Empresa Teste A', 'conta', '420000000000000001', 'uma campanha não abre como conta'),
    ('empresa_a', 'Empresa Teste A', 'campanha', '450000000000000001', 'um anúncio não abre como campanha'),
    ('empresa_a_revogada', 'Empresa Teste A', 'geral', NULL, 'a credencial revogada não devolve nada')
) AS caso (caso, empresa, nivel, id_meta, descricao);

-- O operador lê qualquer empresa (ADR-0004), e cada link, a própria.
SELECT results_eq(
  $$ SELECT * FROM pg_temp.trilha('operador', 'Empresa Teste B', 'anuncio', '450000000000000002') $$,
  $$
  VALUES
    ('geral', NULL::text, 'Empresa Teste B', '{Europe/Lisbon}'::text[]),
    ('conta', '422222222222221', 'Conta Teste B', '{Europe/Lisbon}'),
    ('campanha', '420000000000000002', 'Campanha Teste B', '{Europe/Lisbon}'),
    ('anuncio', '450000000000000002', 'Anúncio Teste B', '{Europe/Lisbon}')
  $$,
  'o operador abre a trilha de outra empresa'
);
SELECT results_eq(
  $$ SELECT nivel, id_meta FROM pg_temp.trilha('empresa_b', 'Empresa Teste B', 'campanha', '420000000000000002') $$,
  $$ VALUES ('geral', NULL::text), ('conta', '422222222222221'), ('campanha', '420000000000000002') $$,
  'o link de B abre a trilha da própria campanha'
);

SELECT * FROM finish();
ROLLBACK;
