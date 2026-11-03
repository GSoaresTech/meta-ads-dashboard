-- Dados do banco local, carregados pelo supabase db reset depois das
-- migrations. Nunca vão para produção (ADR-0010). Só empresas fictícias e IDs
-- inventados, no formato do account_id da Meta (CLAUDE.md §4).

WITH empresa_exemplo AS (
  INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Exemplo') RETURNING id
),
empresa_exemplo_2 AS (
  INSERT INTO normalizado.empresa (nome) VALUES ('Empresa Exemplo 2') RETURNING id
)
INSERT INTO normalizado.conta_anuncio (empresa_id, id_meta, nome, fuso_horario, moeda)
-- Contas em duas moedas na mesma empresa, o caso do RF-34.
SELECT id, '900000000000001', 'Conta Exemplo Brasil', 'America/Sao_Paulo', 'BRL' FROM empresa_exemplo
UNION ALL
SELECT id, '90000000000000002', 'Conta Exemplo EUA', 'America/New_York', 'USD' FROM empresa_exemplo
UNION ALL
SELECT id, '900000000000000003', 'Conta Exemplo 2', 'America/Sao_Paulo', 'BRL' FROM empresa_exemplo_2;
