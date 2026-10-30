-- Prova que o ambiente local de testes de banco funciona antes de existir
-- qualquer schema: o Postgres em execução tem a versão principal de
-- supabase/config.toml. Um volume antigo de outra versão faria os testes
-- rodarem contra um banco diferente do que declaramos.
BEGIN;
SELECT plan(1);

SELECT IS(
  current_setting('server_version_num')::INTEGER / 10000,
  17,
  'Postgres local na versão principal declarada em supabase/config.toml'
);

SELECT * FROM finish();
ROLLBACK;
