-- Prova a revogação da credencial de acesso: só o operador revoga, a
-- credencial revogada deixa de resolver na chamada seguinte, e a linha
-- continua no banco, com a data da revogação (ADR-0004; ADR-0009 §4; RF-45;
-- RNF-14).
BEGIN;
SELECT plan(10);

-- Atributos: escrita da área do operador, com os privilégios do postgres
-- (ADR-0009 §4).
SELECT has_function(
  'analitico', 'revogar_credencial', ARRAY['text', 'uuid'],
  'analitico.revogar_credencial(text, uuid) existe'
);
SELECT results_eq(
  $$
  SELECT p.provolatile::text, p.prosecdef, p.proconfig::text = '{"search_path=\"\""}', pg_get_function_result(p.oid)
  FROM pg_catalog.pg_proc AS p
  WHERE p.oid = 'analitico.revogar_credencial(text, uuid)'::regprocedure
  $$,
  $$ VALUES ('v', true, true, 'void') $$,
  'a revogação é VOLATILE, SECURITY DEFINER, com search_path vazio, e não devolve nada'
);
SELECT ok(
  has_function_privilege('painel_leitor', 'analitico.revogar_credencial(text, uuid)', 'EXECUTE')
    AND NOT has_function_privilege('etl_carga', 'analitico.revogar_credencial(text, uuid)', 'EXECUTE'),
  'painel_leitor executa analitico.revogar_credencial, e etl_carga não'
);

INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Teste A'), ('Empresa Teste B');

-- Duas credenciais de operador, uma de cada empresa, uma da empresa A já
-- revogada em data passada e uma da empresa A criada depois do início da
-- transação que a revoga. A desconhecida tem token sem credencial.
CREATE TEMPORARY TABLE credencial_teste (caso text PRIMARY KEY, token text NOT NULL, id uuid);
INSERT INTO credencial_teste (caso, token)
SELECT 'operador', normalizado.gerar_credencial('operador', NULL)
UNION ALL
SELECT 'operador_2', normalizado.gerar_credencial('operador', NULL)
UNION ALL
SELECT 'empresa_a', normalizado.gerar_credencial('empresa', id) FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
UNION ALL
SELECT 'empresa_a_antiga', normalizado.gerar_credencial('empresa', id) FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
UNION ALL
SELECT 'empresa_a_recente', normalizado.gerar_credencial('empresa', id) FROM normalizado.empresa WHERE nome = 'Empresa Teste A'
UNION ALL
SELECT 'empresa_b', normalizado.gerar_credencial('empresa', id) FROM normalizado.empresa WHERE nome = 'Empresa Teste B'
UNION ALL
SELECT 'desconhecida', translate(encode(extensions.gen_random_bytes(32), 'base64'), '+/=', '-_');

UPDATE credencial_teste AS t
SET id = c.id
FROM normalizado.credencial_acesso AS c
WHERE c.hash = sha256(convert_to(t.token, 'UTF8'));

UPDATE normalizado.credencial_acesso
SET criado_em = '2026-11-01 10:00-03', revogado_em = '2026-11-02 10:00-03'
WHERE id = (SELECT id FROM credencial_teste WHERE caso = 'empresa_a_antiga');

-- Em READ COMMITTED, cada comando vê o que outra sessão confirmou depois do
-- início da transação, cujo now() fica para trás. O segundo a mais no
-- criado_em simula essa credencial.
UPDATE normalizado.credencial_acesso
SET criado_em = now() + interval '1 second'
WHERE id = (SELECT id FROM credencial_teste WHERE caso = 'empresa_a_recente');

-- As tentativas, na ordem: quem revoga, com que credencial, e qual
-- credencial. Cada uma vê o efeito das anteriores.
CREATE TEMPORARY TABLE tentativa (passo integer PRIMARY KEY, credencial text, alvo uuid);
INSERT INTO tentativa (passo, credencial, alvo)
SELECT v.passo, quem.token, coalesce(alvo.id, v.alvo_avulso)
FROM (
  VALUES
    (1, 'empresa_a', 'empresa_b', NULL::uuid),
    (2, 'empresa_a', 'empresa_a', NULL),
    (3, 'desconhecida', 'empresa_b', NULL),
    (4, NULL, 'empresa_b', NULL),
    (5, 'operador', NULL, gen_random_uuid()),
    (6, 'operador', 'empresa_a', NULL),
    (7, 'operador', 'empresa_a_antiga', NULL),
    (8, 'operador', 'empresa_a_recente', NULL),
    (9, 'operador', 'operador_2', NULL),
    (10, 'operador_2', 'empresa_b', NULL),
    (11, 'operador', 'operador', NULL),
    (12, 'operador', 'empresa_b', NULL)
) AS v (passo, quem, alvo, alvo_avulso)
LEFT JOIN credencial_teste AS quem ON quem.caso = v.quem
LEFT JOIN credencial_teste AS alvo ON alvo.caso = v.alvo;

-- O painel_leitor faz as tentativas e depois resolve cada credencial. Ele
-- não tem as funções do pgTAP nem SELECT nas tabelas; os resultados ficam
-- em tabelas temporárias, conferidas depois de voltar ao postgres.
CREATE TEMPORARY TABLE resultado (passo integer PRIMARY KEY, estado text NOT NULL, mensagem text);
CREATE TEMPORARY TABLE resolvido (caso text NOT NULL, escopo text, empresa_id uuid);
GRANT SELECT ON tentativa, credencial_teste TO painel_leitor;
GRANT INSERT ON resultado, resolvido TO painel_leitor;

SET LOCAL ROLE painel_leitor;
DO $$
DECLARE
  item record;
BEGIN
  FOR item IN SELECT passo, credencial, alvo FROM tentativa ORDER BY passo LOOP
    BEGIN
      PERFORM analitico.revogar_credencial(item.credencial, item.alvo);
      INSERT INTO resultado (passo, estado) VALUES (item.passo, 'aceito');
    EXCEPTION WHEN OTHERS THEN
      INSERT INTO resultado (passo, estado, mensagem) VALUES (item.passo, SQLSTATE, SQLERRM);
    END;
  END LOOP;
END
$$;

INSERT INTO resolvido (caso, escopo, empresa_id)
SELECT t.caso, r.escopo, r.empresa_id
FROM credencial_teste AS t
CROSS JOIN LATERAL analitico.resolver_acesso(t.token) AS r;
RESET ROLE;

SELECT results_eq(
  $$ SELECT passo, estado, mensagem FROM resultado ORDER BY passo $$,
  $$
  VALUES
    -- Sem a credencial do operador, nada é revogado, nem a própria credencial.
    (1, '42501', 'acesso negado'),
    (2, '42501', 'acesso negado'),
    (3, '42501', 'acesso negado'),
    (4, '42501', 'acesso negado'),
    -- Um ID que não é de nenhuma credencial não passa em silêncio.
    (5, 'P0002', 'credencial não encontrada'),
    -- O operador revoga um link, um link já revogado, um link criado depois
    -- do início da transação e outro operador.
    (6, 'aceito', NULL),
    (7, 'aceito', NULL),
    (8, 'aceito', NULL),
    (9, 'aceito', NULL),
    -- O operador revogado não escreve mais.
    (10, '42501', 'acesso negado'),
    -- O operador revoga a própria credencial, como na rotação, e perde o
    -- acesso na chamada seguinte.
    (11, 'aceito', NULL),
    (12, '42501', 'acesso negado')
  $$,
  'só o operador revoga, e a credencial revogada perde o acesso na chamada seguinte'
);

SELECT is_empty(
  $$ SELECT caso FROM resolvido WHERE caso IN ('empresa_a', 'empresa_a_antiga', 'empresa_a_recente', 'operador', 'operador_2') $$,
  'uma credencial revogada não resolve, de empresa ou de operador (RF-45)'
);
SELECT results_eq(
  $$
  SELECT r.caso, r.escopo, e.nome
  FROM resolvido AS r
  LEFT JOIN normalizado.empresa AS e ON e.id = r.empresa_id
  ORDER BY r.caso
  $$,
  $$ VALUES ('empresa_b', 'empresa', 'Empresa Teste B') $$,
  'a credencial da empresa B continua resolvendo, só para a empresa B'
);

-- A revogação marca a linha e a mantém, sem apagar nada.
SELECT results_eq(
  $$
  SELECT t.caso, c.revogado_em IS NOT NULL
  FROM credencial_teste AS t
  JOIN normalizado.credencial_acesso AS c ON c.id = t.id
  ORDER BY t.caso
  $$,
  $$
  VALUES ('empresa_a', true),
         ('empresa_a_antiga', true),
         ('empresa_a_recente', true),
         ('empresa_b', false),
         ('operador', true),
         ('operador_2', true)
  $$,
  'as credenciais revogadas continuam no banco, marcadas, e a da empresa B não foi tocada'
);
SELECT is(
  (SELECT c.revogado_em FROM normalizado.credencial_acesso AS c JOIN credencial_teste AS t USING (id) WHERE t.caso = 'empresa_a_antiga'),
  '2026-11-02 10:00-03'::timestamptz,
  'revogar de novo mantém a data da primeira revogação'
);
SELECT is(
  (SELECT c.revogado_em FROM normalizado.credencial_acesso AS c JOIN credencial_teste AS t USING (id) WHERE t.caso = 'empresa_a'),
  now(),
  'a revogação grava o instante da transação que revogou'
);
-- Sem isso, o CHECK revogado_em >= criado_em recusaria a revogação, e o
-- erro levaria a linha, com o hash, à mensagem e ao log.
SELECT is(
  (SELECT c.revogado_em = c.criado_em FROM normalizado.credencial_acesso AS c JOIN credencial_teste AS t USING (id) WHERE t.caso = 'empresa_a_recente'),
  true,
  'a credencial criada depois do início da transação é revogada no instante da criação'
);

SELECT * FROM finish();
ROLLBACK;
