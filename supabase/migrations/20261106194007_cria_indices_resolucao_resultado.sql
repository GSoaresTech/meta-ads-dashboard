-- Índices da resolução do resultado de cada campanha, que vai da campanha aos
-- conjuntos e do conjunto aos anúncios em todas as campanhas da empresa,
-- inclusive as antigas, a cada abertura das visões Geral e conta (RNF-06;
-- ADR-0009 §4). Sem eles, cada conjunto percorre os anúncios da empresa, e o
-- tempo cresce com conjuntos × anúncios, sem depender do período na tela.
--
-- Sem CONCURRENTLY: a migration roda numa transação, e estas tabelas são
-- pequenas o bastante para que o bloqueio de escrita dure menos que um segundo.
-- As leituras do painel continuam durante a criação.
CREATE INDEX anuncio_empresa_id_conjunto_anuncio_id_idx
  ON normalizado.anuncio (empresa_id, conjunto_anuncio_id);
CREATE INDEX conjunto_anuncio_empresa_id_campanha_id_idx
  ON normalizado.conjunto_anuncio (empresa_id, campanha_id);

-- Para que o planejador escolha os índices já na primeira leitura, sem esperar
-- o autovacuum.
ANALYZE normalizado.anuncio;
ANALYZE normalizado.conjunto_anuncio;
