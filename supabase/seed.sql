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

-- Uma carga diária concluída por empresa, que gravou as contas e as
-- entidades abaixo (ADR-0009 §1, Rastreio).
INSERT INTO normalizado.execucao_carga (empresa_id, tipo, status, terminado_em)
SELECT id, 'diaria', 'sucesso', now() FROM normalizado.empresa;

UPDATE normalizado.conta_anuncio AS c
SET execucao_id = x.id
FROM normalizado.execucao_carga AS x
WHERE x.empresa_id = c.empresa_id;

-- Uma hierarquia por conta, com objetivos diferentes, e um criativo
-- reutilizado por dois anúncios (N:1). Página, campanhas e textos fictícios.
INSERT INTO normalizado.pagina (empresa_id, id_meta, nome, execucao_id)
SELECT x.empresa_id, v.id_meta, v.nome, x.id
FROM normalizado.execucao_carga AS x
JOIN normalizado.empresa AS e ON e.id = x.empresa_id
JOIN (
  VALUES
    ('Empresa Exemplo', '910000000000001', 'Página Exemplo'),
    ('Empresa Exemplo 2', '910000000000002', 'Página Exemplo 2')
) AS v (empresa, id_meta, nome) ON v.empresa = e.nome;

INSERT INTO normalizado.campanha (empresa_id, conta_anuncio_id, id_meta, nome, objetivo, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, v.nome, v.objetivo, v.status, c.execucao_id
FROM normalizado.conta_anuncio AS c
JOIN (
  VALUES
    ('900000000000001', '920000000000000001', 'Campanha Exemplo Vendas', 'OUTCOME_SALES', 'ACTIVE'),
    ('90000000000000002', '920000000000000002', 'Campanha Exemplo Cadastros', 'OUTCOME_LEADS', 'PAUSED'),
    ('900000000000000003', '920000000000000003', 'Campanha Exemplo Tráfego', 'OUTCOME_TRAFFIC', 'ACTIVE')
) AS v (conta, id_meta, nome, objetivo, status) ON v.conta = c.id_meta;

INSERT INTO normalizado.conjunto_anuncio (empresa_id, campanha_id, id_meta, nome, meta_otimizacao, status, execucao_id)
SELECT c.empresa_id, c.id, v.id_meta, v.nome, v.meta_otimizacao, c.status, c.execucao_id
FROM normalizado.campanha AS c
JOIN (
  VALUES
    ('920000000000000001', '930000000000000001', 'Conjunto Exemplo Vendas', 'OFFSITE_CONVERSIONS'),
    ('920000000000000002', '930000000000000002', 'Conjunto Exemplo Cadastros', 'LEAD_GENERATION'),
    ('920000000000000003', '930000000000000003', 'Conjunto Exemplo Tráfego', 'LINK_CLICKS')
) AS v (campanha, id_meta, nome, meta_otimizacao) ON v.campanha = c.id_meta;

INSERT INTO normalizado.janela_atribuicao_conjunto (empresa_id, conjunto_anuncio_id, tipo_evento, janela_dias, execucao_id)
SELECT empresa_id, id, j.tipo_evento, j.janela_dias, execucao_id
FROM normalizado.conjunto_anuncio
CROSS JOIN (VALUES ('CLICK_THROUGH', 7), ('VIEW_THROUGH', 1)) AS j (tipo_evento, janela_dias);

INSERT INTO normalizado.criativo (empresa_id, conta_anuncio_id, pagina_id, id_meta, titulo, texto, chamada_acao, execucao_id)
SELECT c.empresa_id, c.id, p.id, v.id_meta, v.titulo, v.texto, v.chamada_acao, c.execucao_id
FROM normalizado.conta_anuncio AS c
JOIN normalizado.pagina AS p ON p.empresa_id = c.empresa_id
JOIN (
  VALUES
    ('900000000000001', '940000000000000001', 'Produto Exemplo', 'Texto de anúncio fictício para vendas.', 'SHOP_NOW'),
    ('90000000000000002', '940000000000000002', 'Cadastro Exemplo', 'Texto de anúncio fictício para cadastros.', 'SIGN_UP'),
    ('900000000000000003', '940000000000000003', 'Site Exemplo', 'Texto de anúncio fictício para tráfego.', 'LEARN_MORE')
) AS v (conta, id_meta, titulo, texto, chamada_acao) ON v.conta = c.id_meta;

INSERT INTO normalizado.anuncio (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, nome, status, execucao_id)
SELECT j.empresa_id, j.id, k.id, v.id_meta, v.nome, j.status, j.execucao_id
FROM (
  VALUES
    ('930000000000000001', '940000000000000001', '950000000000000001', 'Anúncio Exemplo Vendas A'),
    ('930000000000000001', '940000000000000001', '950000000000000002', 'Anúncio Exemplo Vendas B'),
    ('930000000000000002', '940000000000000002', '950000000000000003', 'Anúncio Exemplo Cadastros'),
    ('930000000000000003', '940000000000000003', '950000000000000004', 'Anúncio Exemplo Tráfego')
) AS v (conjunto, criativo, id_meta, nome)
JOIN normalizado.conjunto_anuncio AS j ON j.id_meta = v.conjunto
JOIN normalizado.criativo AS k ON k.id_meta = v.criativo;
