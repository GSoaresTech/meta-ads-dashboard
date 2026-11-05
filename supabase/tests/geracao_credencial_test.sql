-- Prova a geração da credencial de acesso: o banco sorteia o token, grava só
-- o hash SHA-256 e devolve o token uma única vez. O link de empresa exige a
-- credencial do operador, e a primeira credencial do operador é criada pelo
-- postgres, pelo runbook (ADR-0004; ADR-0009 §4; RF-44; RNF-14; RNF-15).
BEGIN;
SELECT plan(14);

-- Atributos: as funções internas rodam com os privilégios de quem chama, e
-- a de analitico, com os do postgres (ADR-0009 §3 e §4).
SELECT has_function(
  'normalizado', 'gerar_credencial', ARRAY['text', 'uuid'],
  'normalizado.gerar_credencial(text, uuid) existe'
);
SELECT has_function(
  'normalizado', 'exigir_operador', ARRAY['text'],
  'normalizado.exigir_operador(text) existe'
);
SELECT has_function(
  'analitico', 'gerar_credencial_empresa', ARRAY['text', 'uuid'],
  'analitico.gerar_credencial_empresa(text, uuid) existe'
);
SELECT results_eq(
  $$
  SELECT p.oid::regprocedure::text, p.provolatile::text, p.prosecdef, p.proconfig::text = '{"search_path=\"\""}'
  FROM pg_catalog.pg_proc AS p
  WHERE p.oid IN (
    'normalizado.gerar_credencial(text, uuid)'::regprocedure,
    'normalizado.exigir_operador(text)'::regprocedure,
    'analitico.gerar_credencial_empresa(text, uuid)'::regprocedure
  )
  ORDER BY 1
  $$,
  $$
  VALUES ('analitico.gerar_credencial_empresa(text,uuid)', 'v', true, true),
         ('normalizado.exigir_operador(text)', 's', false, true),
         ('normalizado.gerar_credencial(text,uuid)', 'v', false, true)
  $$,
  'a geração é VOLATILE e a exigência do operador, STABLE; só a de analitico é SECURITY DEFINER; todas com search_path vazio'
);
-- Sem grant, só o dono executa: a primeira credencial do operador sai do
-- postgres, e nenhum papel próprio gera credencial sem a do operador.
SELECT is_empty(
  $$
  SELECT p.oid::regprocedure, a.grantee
  FROM pg_catalog.pg_proc AS p
  CROSS JOIN LATERAL aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) AS a
  WHERE p.oid IN ('normalizado.gerar_credencial(text, uuid)'::regprocedure, 'normalizado.exigir_operador(text)'::regprocedure)
    AND a.grantee <> p.proowner
  $$,
  'normalizado.gerar_credencial e normalizado.exigir_operador são executáveis só pelo postgres'
);
SELECT ok(
  has_function_privilege('painel_leitor', 'analitico.gerar_credencial_empresa(text, uuid)', 'EXECUTE')
    AND NOT has_function_privilege('etl_carga', 'analitico.gerar_credencial_empresa(text, uuid)', 'EXECUTE'),
  'painel_leitor executa analitico.gerar_credencial_empresa, e etl_carga não'
);

INSERT INTO normalizado.empresa (nome, situacao)
VALUES ('Empresa Teste A', 'ativa'), ('Empresa Teste B', 'ativa'), ('Empresa Teste Inativa', 'inativa');

-- Os tokens gerados ficam numa tabela temporária, desfeita com o ROLLBACK,
-- e nunca saem na saída do teste.
CREATE TEMPORARY TABLE token (caso text PRIMARY KEY, valor text NOT NULL);
CREATE TEMPORARY TABLE empresa_teste AS
SELECT nome, id FROM normalizado.empresa WHERE nome LIKE 'Empresa Teste %';

-- A primeira credencial do operador, como o runbook a cria.
INSERT INTO token (caso, valor) SELECT 'operador', normalizado.gerar_credencial('operador', NULL);

-- Com ela, o painel_leitor gera dois links da empresa A. Ele não tem as
-- funções do pgTAP nem SELECT nas tabelas; os resultados ficam em tabelas
-- temporárias, conferidas depois de voltar ao postgres.
CREATE TEMPORARY TABLE resolvido (caso text NOT NULL, escopo text, empresa_id uuid);
GRANT SELECT, INSERT ON token TO painel_leitor;
GRANT SELECT ON empresa_teste TO painel_leitor;
GRANT INSERT ON resolvido TO painel_leitor;

SET LOCAL ROLE painel_leitor;
INSERT INTO token (caso, valor)
SELECT caso.nome, analitico.gerar_credencial_empresa(operador.valor, empresa.id)
FROM token AS operador
CROSS JOIN empresa_teste AS empresa
CROSS JOIN (VALUES ('empresa_a'), ('empresa_a_2')) AS caso (nome)
WHERE operador.caso = 'operador' AND empresa.nome = 'Empresa Teste A';

INSERT INTO resolvido (caso, escopo, empresa_id)
SELECT t.caso, r.escopo, r.empresa_id
FROM token AS t
CROSS JOIN LATERAL analitico.resolver_acesso(t.valor) AS r;
RESET ROLE;

-- RNF-15: o token tem 43 caracteres de base64url sem preenchimento, que
-- codificam 32 bytes sorteados, 256 bits, acima dos 128 exigidos.
SELECT results_eq(
  $$
  SELECT caso, valor ~ '^[A-Za-z0-9_-]{43}$', octet_length(decode(translate(valor, '-_', '+/') || '=', 'base64'))
  FROM token
  ORDER BY caso
  $$,
  $$
  VALUES ('empresa_a', true, 32), ('empresa_a_2', true, 32), ('operador', true, 32)
  $$,
  'cada token é base64url de 32 bytes, 256 bits de entropia'
);
SELECT is(
  (SELECT count(DISTINCT valor) FROM token),
  3::bigint,
  'cada geração sorteia um token novo'
);

-- RNF-15: o banco guarda o SHA-256 do texto do token, o mesmo que a
-- resolução calcula, com o escopo pedido.
SELECT results_eq(
  $$
  SELECT t.caso, c.escopo, e.nome, c.revogado_em IS NULL
  FROM token AS t
  JOIN normalizado.credencial_acesso AS c ON c.hash = sha256(convert_to(t.valor, 'UTF8'))
  LEFT JOIN normalizado.empresa AS e ON e.id = c.empresa_id
  ORDER BY t.caso
  $$,
  $$
  VALUES ('empresa_a', 'empresa', 'Empresa Teste A', true),
         ('empresa_a_2', 'empresa', 'Empresa Teste A', true),
         ('operador', 'operador', NULL, true)
  $$,
  'cada credencial gerada é gravada pelo SHA-256 do token, com o escopo pedido'
);

-- RNF-15: 0 tokens em texto puro. A busca percorre toda tabela dos três
-- esquemas, atrás do texto do token, dos bytes desse texto e dos 32 bytes
-- que ele codifica, em hex, que é como um bytea aparece no texto da linha.
SELECT is_empty(
  $$
  SELECT format('%I.%I', n.nspname, c.relname), t.caso
  FROM pg_catalog.pg_class AS c
  JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
  CROSS JOIN token AS t
  CROSS JOIN LATERAL (
    SELECT (xpath('/row/n/text()', query_to_xml(format(
      'SELECT count(*) AS n FROM %I.%I AS linha WHERE strpos(linha::text, %L) > 0 OR strpos(linha::text, %L) > 0 OR strpos(linha::text, %L) > 0',
      n.nspname, c.relname, t.valor,
      encode(convert_to(t.valor, 'UTF8'), 'hex'),
      encode(decode(translate(t.valor, '-_', '+/') || '=', 'base64'), 'hex')
    ), false, true, '')))[1]::text::integer AS linhas
  ) AS busca
  WHERE n.nspname IN ('bruto', 'normalizado', 'analitico')
    AND c.relkind IN ('r', 'p')
    AND busca.linhas > 0
  $$,
  'nenhuma tabela dos três esquemas guarda um token gerado, em texto ou em bytes, nem os bytes que ele codifica'
);

-- O link gerado abre o painel da empresa (RF-44), e o segundo link não
-- invalida o primeiro.
SELECT results_eq(
  $$
  SELECT r.caso, r.escopo, e.nome
  FROM resolvido AS r
  LEFT JOIN normalizado.empresa AS e ON e.id = r.empresa_id
  ORDER BY r.caso
  $$,
  $$
  VALUES ('empresa_a', 'empresa', 'Empresa Teste A'),
         ('empresa_a_2', 'empresa', 'Empresa Teste A'),
         ('operador', 'operador', NULL)
  $$,
  'os links gerados resolvem para a empresa A, e a credencial do operador, para o operador'
);

-- Sem a credencial do operador, a geração é negada com 42501 e mensagem
-- genérica, que não diz se a credencial existe, foi revogada ou é de
-- empresa (ADR-0009 §4).
INSERT INTO token (caso, valor)
VALUES ('operador_revogado', translate(encode(extensions.gen_random_bytes(32), 'base64'), '+/=', '-_')),
       ('desconhecida', translate(encode(extensions.gen_random_bytes(32), 'base64'), '+/=', '-_'));
INSERT INTO normalizado.credencial_acesso (hash, escopo, revogado_em)
SELECT sha256(convert_to(valor, 'UTF8')), 'operador', now() FROM token WHERE caso = 'operador_revogado';

-- Com a credencial do operador, a geração exige empresa ativa: o link de
-- empresa inativa nunca abriria o painel (RF-44, RF-48).
CREATE TEMPORARY TABLE tentativa (caso text PRIMARY KEY, credencial text, empresa_id uuid);
INSERT INTO tentativa (caso, credencial, empresa_id)
SELECT v.caso, quem.valor, coalesce(alvo.id, v.empresa_avulsa)
FROM (
  VALUES
    ('empresa_a_para_b', 'empresa_a', 'Empresa Teste B', NULL::uuid),
    ('empresa_a_para_a', 'empresa_a', 'Empresa Teste A', NULL),
    ('operador_revogado', 'operador_revogado', 'Empresa Teste A', NULL),
    ('desconhecida', 'desconhecida', 'Empresa Teste A', NULL),
    ('nula', NULL, 'Empresa Teste A', NULL),
    ('operador_para_inativa', 'operador', 'Empresa Teste Inativa', NULL),
    ('operador_para_inexistente', 'operador', NULL, gen_random_uuid()),
    ('operador_para_nula', 'operador', NULL, NULL)
) AS v (caso, quem, empresa, empresa_avulsa)
LEFT JOIN token AS quem ON quem.caso = v.quem
LEFT JOIN empresa_teste AS alvo ON alvo.nome = v.empresa;

CREATE TEMPORARY TABLE negado (caso text PRIMARY KEY, estado text NOT NULL, mensagem text);
GRANT SELECT ON tentativa TO painel_leitor;
GRANT INSERT ON negado TO painel_leitor;

SET LOCAL ROLE painel_leitor;
DO $$
DECLARE
  item record;
BEGIN
  FOR item IN SELECT caso, credencial, empresa_id FROM tentativa LOOP
    BEGIN
      PERFORM analitico.gerar_credencial_empresa(item.credencial, item.empresa_id);
      INSERT INTO negado (caso, estado) VALUES (item.caso, 'aceito');
    EXCEPTION WHEN OTHERS THEN
      INSERT INTO negado (caso, estado, mensagem) VALUES (item.caso, SQLSTATE, SQLERRM);
    END;
  END LOOP;
END
$$;
RESET ROLE;

SELECT results_eq(
  $$ SELECT caso, estado, mensagem FROM negado ORDER BY caso $$,
  $$
  VALUES
    -- Sem a credencial do operador: 42501, com a mesma mensagem.
    ('desconhecida', '42501', 'acesso negado'),
    ('empresa_a_para_a', '42501', 'acesso negado'),
    ('empresa_a_para_b', '42501', 'acesso negado'),
    ('nula', '42501', 'acesso negado'),
    -- Com ela, mas sem empresa ativa: P0002.
    ('operador_para_inativa', 'P0002', 'empresa não encontrada ou inativa'),
    ('operador_para_inexistente', 'P0002', 'empresa não encontrada ou inativa'),
    ('operador_para_nula', 'P0002', 'empresa não encontrada ou inativa'),
    ('operador_revogado', '42501', 'acesso negado')
  $$,
  'sem a credencial do operador, a geração é negada com 42501 e mensagem genérica; com ela, só empresa ativa recebe link'
);
SELECT is_empty(
  $$
  SELECT c.id
  FROM normalizado.credencial_acesso AS c
  JOIN normalizado.empresa AS e ON e.id = c.empresa_id
  WHERE e.nome = 'Empresa Teste B'
  $$,
  'a credencial da empresa A não gera credencial da empresa B'
);
SELECT is_empty(
  $$
  SELECT c.id
  FROM normalizado.credencial_acesso AS c
  JOIN normalizado.empresa AS e ON e.id = c.empresa_id
  WHERE e.nome = 'Empresa Teste Inativa'
  $$,
  'nenhum link da empresa inativa é gravado'
);

SELECT * FROM finish();
ROLLBACK;
