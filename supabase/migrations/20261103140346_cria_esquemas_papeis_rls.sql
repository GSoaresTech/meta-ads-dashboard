-- Esquemas das três camadas e papéis de banco da ETL e do painel (ADR-0009
-- §3). Os grants por tabela e por função, o RLS e as políticas entram na
-- migration que cria cada tabela ou função.

-- Com o pg_net instalado, nossos papéis leriam a fila de requisições pelo que
-- PUBLIC recebe, e o Supabase não permite mudar os grants dela (R-30). Vem
-- antes de tudo para que uma recusa interrompa a migration sem criar nada.
DROP EXTENSION IF EXISTS pg_net;
DROP SCHEMA IF EXISTS net;

-- Esquemas próprios ficam fora de "Exposed schemas" e não recebem privilégio
-- padrão para anon, authenticated e service_role (R-29).
CREATE SCHEMA bruto;
CREATE SCHEMA normalizado;
CREATE SCHEMA analitico;

-- Papéis são do cluster, não do banco, e podem sobreviver a um reset. Sem
-- senha, o papel não autentica (R-33); a senha é definida fora do
-- repositório, com \password no psql (ADR-0009 §3).
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'etl_carga') THEN
    CREATE ROLE etl_carga LOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'painel_leitor') THEN
    CREATE ROLE painel_leitor LOGIN;
  END IF;
END
$$;

-- O criador de um papel não ganha SET ROLE sobre ele (R-34). Os testes pgTAP
-- precisam trocar de papel, mas o postgres não deve herdar nada dos dois.
GRANT etl_carga, painel_leitor TO postgres WITH INHERIT FALSE, SET TRUE;

GRANT USAGE ON SCHEMA bruto, normalizado TO etl_carga;
GRANT USAGE ON SCHEMA analitico TO painel_leitor;
