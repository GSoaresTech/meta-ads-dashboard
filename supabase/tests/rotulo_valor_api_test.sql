-- Prova o catálogo de rótulos dos valores de enum da API: o painel nunca
-- mostra o valor da Meta, e todo status que o banco aceita tem rótulo de
-- negócio (RF-37; RNF-02; ADR-0007; ADR-0009 §1 e §2).
BEGIN;
SELECT plan(16);

-- Estrutura
SELECT has_table('normalizado', 'rotulo_valor_api', 'a tabela rotulo_valor_api existe');
SELECT col_is_pk(
  'normalizado', 'rotulo_valor_api', ARRAY['dominio', 'valor'],
  'rotulo_valor_api tem PK (dominio, valor), um rótulo por valor de cada domínio'
);
SELECT col_not_null('normalizado', 'rotulo_valor_api', coluna, format('rotulo_valor_api.%s é NOT NULL', coluna))
FROM unnest(ARRAY['dominio', 'valor', 'rotulo']) AS coluna;

-- Restrições
SELECT throws_ok(
  format($$ INSERT INTO normalizado.rotulo_valor_api (dominio, valor, rotulo) VALUES (%L, %L, %L) $$, dominio, valor, rotulo),
  '23514',
  NULL,
  descricao
)
FROM (
  VALUES
    ('objetivo', 'VALOR_TESTE', 'Rótulo', 'o domínio fora da lista é recusado: o objetivo vem de resultado_objetivo'),
    ('status', ' VALOR_TESTE', 'Rótulo', 'o valor não aparado é recusado'),
    ('status', '', 'Rótulo', 'o valor vazio é recusado'),
    ('status', 'VALOR_TESTE', ' Rótulo', 'o rótulo não aparado é recusado'),
    ('status', 'VALOR_TESTE', '', 'o rótulo vazio é recusado')
) AS caso (dominio, valor, rotulo, descricao);

-- Conteúdo: RF-37 dá "Ativa" como exemplo, e a campanha é o que a tela mostra.
SELECT results_eq(
  $$ SELECT valor, rotulo FROM normalizado.rotulo_valor_api WHERE dominio = 'status' ORDER BY valor $$,
  $$
  VALUES
    ('ACTIVE', 'Ativa'),
    ('ARCHIVED', 'Arquivada'),
    ('DELETED', 'Excluída'),
    ('PAUSED', 'Pausada')
  $$,
  'cada status da API tem o rótulo de negócio'
);

-- O status é domínio fechado: quem acrescenta um valor ao CHECK de uma
-- entidade precisa acrescentar o rótulo, ou a tela ficaria sem texto. A
-- consulta lê o CHECK, e não uma lista, para valer também para esse valor.
SELECT is_empty(
  format(
    $$
    SELECT aceito.valor[1]
    FROM regexp_matches(%L, '''([A-Z_]+)''', 'g') AS aceito (valor)
    WHERE NOT EXISTS (
      SELECT FROM normalizado.rotulo_valor_api AS rotulo
      WHERE rotulo.dominio = 'status' AND rotulo.valor = aceito.valor[1]
    )
    $$,
    pg_get_constraintdef(restricao.oid)
  ),
  format('todo status aceito por %s tem rótulo', restricao.conrelid::regclass)
)
FROM pg_catalog.pg_constraint AS restricao
WHERE restricao.conname IN ('campanha_status_check', 'conjunto_anuncio_status_check', 'anuncio_status_check');

-- O catálogo é global e só lido: a ETL lê, como nas demais tabelas de
-- catálogo, e o painel chega a ele só pelas funções de analitico
-- (ADR-0009 §3). O teste geral de privilégios cobre o RLS e os demais papéis.
SELECT ok(
  has_table_privilege('etl_carga', 'normalizado.rotulo_valor_api', 'SELECT'),
  'etl_carga lê rotulo_valor_api'
);
SELECT ok(
  NOT has_table_privilege('etl_carga', 'normalizado.rotulo_valor_api', 'INSERT, UPDATE, DELETE, TRUNCATE'),
  'etl_carga não escreve em rotulo_valor_api'
);

SELECT * FROM finish();
ROLLBACK;
