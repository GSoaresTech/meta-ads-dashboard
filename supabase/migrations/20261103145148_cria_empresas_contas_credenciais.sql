-- Empresas, contas de anúncio e credenciais de acesso ao painel: a base do
-- multiempresa e do acesso por link (ADR-0002; ADR-0004; ADR-0009 §2 e §3).

CREATE TABLE normalizado.empresa (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  nome text NOT NULL,
  situacao text NOT NULL DEFAULT 'ativa',
  criado_em timestamptz NOT NULL DEFAULT now(),
  atualizado_em timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT empresa_nome_check CHECK (nome = btrim(nome) AND nome <> ''),
  CONSTRAINT empresa_situacao_check CHECK (situacao IN ('ativa', 'inativa'))
);

-- Nome, fuso e moeda ficam nulos entre o cadastro, que informa só o ID
-- (RF-43), e a primeira extração. A coluna execucao_id entra com a tabela de
-- execuções.
CREATE TABLE normalizado.conta_anuncio (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  empresa_id uuid NOT NULL REFERENCES normalizado.empresa (id),
  -- O account_id da Meta, sem o prefixo act_ (R-35).
  id_meta text NOT NULL UNIQUE,
  nome text,
  fuso_horario text,
  moeda text,
  situacao text NOT NULL DEFAULT 'ativa',
  criado_em timestamptz NOT NULL DEFAULT now(),
  atualizado_em timestamptz NOT NULL DEFAULT now(),
  -- Alvo das FKs compostas das tabelas filhas (ADR-0009 §1).
  CONSTRAINT conta_anuncio_empresa_id_id_key UNIQUE (empresa_id, id),
  CONSTRAINT conta_anuncio_id_meta_check CHECK (id_meta ~ '^[0-9]+$'),
  CONSTRAINT conta_anuncio_nome_check CHECK (nome = btrim(nome) AND nome <> ''),
  -- Só o formato; a existência na base IANA é conferida pelo trigger abaixo.
  CONSTRAINT conta_anuncio_fuso_horario_check CHECK (fuso_horario ~ '^[A-Za-z0-9_+/-]+$'),
  CONSTRAINT conta_anuncio_moeda_check CHECK (moeda ~ '^[A-Z]{3}$'),
  CONSTRAINT conta_anuncio_fuso_moeda_check CHECK ((fuso_horario IS NULL) = (moeda IS NULL)),
  CONSTRAINT conta_anuncio_situacao_check CHECK (situacao IN ('ativa', 'inativa'))
);

-- Um CHECK não consulta a base IANA, e o AT TIME ZONE aceita especificações
-- POSIX, como 'XYZ+3', que não são nomes IANA. O trigger confere o nome em
-- pg_timezone_names. Um CHECK com função seria reavaliado ao restaurar um
-- dump, e um nome retirado do tzdata de um Postgres mais novo impediria a
-- restauração; o trigger vale só para a escrita.
CREATE FUNCTION normalizado.validar_fuso_horario()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_timezone_names WHERE name = NEW.fuso_horario) THEN
    RAISE EXCEPTION 'fuso horário fora da base IANA'
      USING ERRCODE = 'check_violation',
            TABLE = TG_TABLE_NAME,
            COLUMN = 'fuso_horario';
  END IF;
  RETURN NEW;
END
$$;

REVOKE ALL ON FUNCTION normalizado.validar_fuso_horario() FROM PUBLIC;

CREATE TRIGGER conta_anuncio_valida_fuso_horario
BEFORE INSERT OR UPDATE OF fuso_horario ON normalizado.conta_anuncio
FOR EACH ROW
WHEN (NEW.fuso_horario IS NOT NULL)
EXECUTE FUNCTION normalizado.validar_fuso_horario();

-- Uma linha por link de empresa ou credencial de operador. Só o hash SHA-256
-- do token é guardado, e o token em texto puro não cabe em nenhuma coluna
-- (RNF-15). Não há coluna que identifique quem recebeu o link (ADR-0009 §6).
CREATE TABLE normalizado.credencial_acesso (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  hash bytea NOT NULL UNIQUE,
  escopo text NOT NULL,
  -- Nulo só na credencial do operador, que não pertence a uma empresa.
  empresa_id uuid REFERENCES normalizado.empresa (id),
  criado_em timestamptz NOT NULL DEFAULT now(),
  revogado_em timestamptz,
  CONSTRAINT credencial_acesso_hash_check CHECK (octet_length(hash) = 32),
  CONSTRAINT credencial_acesso_escopo_check CHECK (escopo IN ('empresa', 'operador')),
  CONSTRAINT credencial_acesso_escopo_empresa_check CHECK ((escopo = 'empresa') = (empresa_id IS NOT NULL)),
  CONSTRAINT credencial_acesso_revogado_em_check CHECK (revogado_em >= criado_em)
);

ALTER TABLE normalizado.empresa ENABLE ROW LEVEL SECURITY;
ALTER TABLE normalizado.conta_anuncio ENABLE ROW LEVEL SECURITY;
-- Sem política: só as funções de analitico, donas do postgres, leem as
-- credenciais (ADR-0004).
ALTER TABLE normalizado.credencial_acesso ENABLE ROW LEVEL SECURITY;

-- Os grants limitam a política aos comandos da ETL (ADR-0009 §3).
CREATE POLICY etl_carga_acessa ON normalizado.empresa
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON normalizado.conta_anuncio
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);

GRANT SELECT ON normalizado.empresa TO etl_carga;
-- A ETL só preenche o que vem da extração. Empresa, ID e situação são do
-- cadastro da área do operador.
GRANT SELECT, UPDATE (nome, fuso_horario, moeda, atualizado_em)
  ON normalizado.conta_anuncio TO etl_carga;
