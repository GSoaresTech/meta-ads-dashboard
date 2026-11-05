-- Geração da credencial de acesso ao painel: o banco sorteia o token, grava
-- só o hash SHA-256 e devolve o token uma única vez (ADR-0004; ADR-0009 §4;
-- RF-44; RNF-15).

-- O gen_random_bytes, que devolve bytes criptograficamente fortes, vem do
-- pgcrypto. O Supabase já o instala no esquema extensions; a criação deixa
-- a dependência explícita.
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

-- A única função que sorteia tokens. O link da empresa passa por
-- analitico.gerar_credencial_empresa, que exige o operador, e a primeira
-- credencial do operador é criada pelo postgres, pelo runbook, com
-- gerar_credencial('operador', NULL). O token nasce aqui e não no texto de
-- um comando SQL, para não ir ao histórico nem ao log de quem o executa.
--
-- SECURITY INVOKER e sem grant: só o postgres a executa (ADR-0009 §4).
CREATE FUNCTION normalizado.gerar_credencial(p_escopo text, p_empresa_id uuid)
RETURNS text
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
  -- 256 bits, acima dos 128 do RNF-15, como recomenda o ADR-0004.
  bytes_token CONSTANT integer := 32;
  token text;
BEGIN
  -- O link de empresa inativa nunca abriria o painel (RF-44, RF-48) e
  -- passaria a valer sozinho se a empresa voltasse a ser ativa.
  IF p_escopo = 'empresa' AND NOT EXISTS (
    SELECT FROM normalizado.empresa AS empresa
    WHERE empresa.id = p_empresa_id AND empresa.situacao = 'ativa'
  ) THEN
    RAISE EXCEPTION 'empresa não encontrada ou inativa' USING ERRCODE = 'no_data_found';
  END IF;

  -- base64url sem preenchimento. O PostgreSQL 17 só codifica em base64, com
  -- + e / e o = de preenchimento; os 44 caracteres de 32 bytes não chegam à
  -- quebra de linha, que o base64 insere a cada 76.
  token := translate(encode(extensions.gen_random_bytes(bytes_token), 'base64'), '+/=', '-_');
  INSERT INTO normalizado.credencial_acesso (hash, escopo, empresa_id)
  VALUES (sha256(convert_to(token, 'UTF8')), p_escopo, p_empresa_id);
  RETURN token;
END
$$;

REVOKE ALL ON FUNCTION normalizado.gerar_credencial(text, uuid) FROM PUBLIC;

-- A barreira de toda função de escrita da área do operador. A mensagem é a
-- mesma para credencial inexistente, revogada ou de empresa, para não
-- revelar qual é o caso (ADR-0009 §4).
CREATE FUNCTION normalizado.exigir_operador(p_credencial text)
RETURNS void
LANGUAGE plpgsql
STABLE
SET search_path = ''
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT FROM normalizado.resolver_credencial(p_credencial) AS credencial
    WHERE credencial.escopo = 'operador'
  ) THEN
    RAISE EXCEPTION 'acesso negado' USING ERRCODE = 'insufficient_privilege';
  END IF;
END
$$;

REVOKE ALL ON FUNCTION normalizado.exigir_operador(text) FROM PUBLIC;

-- O link de uma empresa, gerado pela área do operador (RF-44). Cada chamada
-- cria uma credencial nova, sem revogar as anteriores da empresa.
CREATE FUNCTION analitico.gerar_credencial_empresa(p_credencial text, p_empresa_id uuid)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  PERFORM normalizado.exigir_operador(p_credencial);
  RETURN normalizado.gerar_credencial('empresa', p_empresa_id);
END
$$;

REVOKE ALL ON FUNCTION analitico.gerar_credencial_empresa(text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analitico.gerar_credencial_empresa(text, uuid) TO painel_leitor;
