-- Controle de execuções e camada bruta: o registro de cada execução por
-- empresa, as linhas afetadas, os avisos, as fatias da carga histórica e as
-- respostas da API como recebidas (RF-07, RF-09, RF-20; ADR-0005; ADR-0009 §2
-- e §3). A coluna execucao_id das contas e das entidades entra na migration
-- seguinte.

-- Uma linha por execução × empresa; o id é o execucao_id dos logs. Os
-- registros de início e de fim usam transações próprias, fora da carga, para
-- que a falha fique gravada depois do rollback dela (ADR-0009 §5).
CREATE TABLE normalizado.execucao_carga (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  empresa_id uuid NOT NULL REFERENCES normalizado.empresa (id),
  tipo text NOT NULL,
  status text NOT NULL DEFAULT 'em_andamento',
  iniciado_em timestamptz NOT NULL DEFAULT now(),
  terminado_em timestamptz,
  erro text,
  CONSTRAINT execucao_carga_empresa_id_id_key UNIQUE (empresa_id, id),
  CONSTRAINT execucao_carga_tipo_check CHECK (tipo IN ('horaria', 'diaria', 'historica')),
  CONSTRAINT execucao_carga_status_check CHECK (status IN ('em_andamento', 'sucesso', 'falha', 'ignorada')),
  CONSTRAINT execucao_carga_terminado_em_check CHECK ((status = 'em_andamento') = (terminado_em IS NULL)),
  CONSTRAINT execucao_carga_terminado_em_iniciado_em_check CHECK (terminado_em >= iniciado_em),
  -- Toda falha tem mensagem de erro não vazia (RF-20).
  CONSTRAINT execucao_carga_falha_erro_check CHECK (status <> 'falha' OR erro IS NOT NULL),
  CONSTRAINT execucao_carga_erro_check CHECK (erro = btrim(erro) AND erro <> '')
);

-- Área do operador (RF-51) e detecção de carga parada (RNF-13).
CREATE INDEX execucao_carga_empresa_id_iniciado_em_idx
  ON normalizado.execucao_carga (empresa_id, iniciado_em);

-- Gravada com o registro de fim (ADR-0009 §5).
CREATE TABLE normalizado.contagem_linhas_execucao (
  empresa_id uuid NOT NULL REFERENCES normalizado.empresa (id),
  execucao_id uuid NOT NULL,
  tabela text NOT NULL,
  linhas bigint NOT NULL,
  PRIMARY KEY (empresa_id, execucao_id, tabela),
  CONSTRAINT contagem_linhas_execucao_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id),
  CONSTRAINT contagem_linhas_execucao_tabela_check CHECK (tabela = btrim(tabela) AND tabela <> ''),
  CONSTRAINT contagem_linhas_execucao_linhas_check CHECK (linhas >= 0)
);

-- Avisos do RF-15 e do RF-16, com a campanha pelo id interno. Entram na
-- transação da carga, porque o aviso de uma carga desfeita não vale
-- (ADR-0009 §5).
CREATE TABLE normalizado.aviso_execucao (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  empresa_id uuid NOT NULL REFERENCES normalizado.empresa (id),
  execucao_id uuid NOT NULL,
  tipo text NOT NULL,
  campanha_id uuid,
  criado_em timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT aviso_execucao_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id),
  CONSTRAINT aviso_execucao_campanha_fkey FOREIGN KEY (empresa_id, campanha_id)
    REFERENCES normalizado.campanha (empresa_id, id),
  CONSTRAINT aviso_execucao_tipo_check CHECK (tipo IN ('objetivo_nao_classificado', 'divergencia_resultado'))
);

-- Uma linha por conta × mês da carga histórica (RF-07). A marca concluida é
-- gravada na mesma transação dos dados da fatia, e a retomada começa pela
-- primeira fatia não concluída (ADR-0009 §5). O instante de cada mudança é o
-- da execução, por execucao_id.
CREATE TABLE normalizado.fatia_historica (
  empresa_id uuid NOT NULL REFERENCES normalizado.empresa (id),
  conta_anuncio_id uuid NOT NULL,
  mes_referencia date NOT NULL,
  status text NOT NULL DEFAULT 'pendente',
  execucao_id uuid NOT NULL,
  PRIMARY KEY (empresa_id, conta_anuncio_id, mes_referencia),
  CONSTRAINT fatia_historica_conta_anuncio_fkey FOREIGN KEY (empresa_id, conta_anuncio_id)
    REFERENCES normalizado.conta_anuncio (empresa_id, id),
  CONSTRAINT fatia_historica_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id),
  -- extract só valida a linha; o agrupamento por mês vem de calendario
  -- (CLAUDE.md §5).
  CONSTRAINT fatia_historica_mes_referencia_check CHECK (extract(day FROM mes_referencia) = 1),
  CONSTRAINT fatia_historica_status_check CHECK (status IN ('pendente', 'concluida', 'falha'))
);

-- Uma linha por resposta (página) recebida da Meta, como recebida, fora da
-- 3FN (RF-09; ADR-0005). A retenção apaga pela data de referência (RF-21).
CREATE TABLE bruto.resposta_api (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  empresa_id uuid NOT NULL REFERENCES normalizado.empresa (id),
  execucao_id uuid NOT NULL,
  conta_anuncio_id uuid NOT NULL,
  endpoint text NOT NULL,
  parametros jsonb NOT NULL,
  -- A última data coberta por uma consulta de insights; nas de cadastro, que
  -- não têm intervalo, a data da extração no fuso da conta. Assim a retenção
  -- alcança toda linha.
  data_referencia date NOT NULL,
  resposta jsonb NOT NULL,
  recebido_em timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT resposta_api_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id),
  CONSTRAINT resposta_api_conta_anuncio_fkey FOREIGN KEY (empresa_id, conta_anuncio_id)
    REFERENCES normalizado.conta_anuncio (empresa_id, id),
  CONSTRAINT resposta_api_endpoint_check CHECK (endpoint = btrim(endpoint) AND endpoint <> ''),
  -- O operador ? só compara a chave inteira, no primeiro nível: um texto ou
  -- uma lista com 'access_token=...' escaparia da conferência do token.
  CONSTRAINT resposta_api_parametros_objeto_check CHECK (jsonb_typeof(parametros) = 'object'),
  -- O token vai no cabeçalho de autorização e nunca é gravado.
  CONSTRAINT resposta_api_parametros_access_token_check CHECK (NOT parametros ? 'access_token')
);

CREATE INDEX resposta_api_data_referencia_idx ON bruto.resposta_api (data_referencia);

ALTER TABLE normalizado.execucao_carga ENABLE ROW LEVEL SECURITY;
ALTER TABLE normalizado.contagem_linhas_execucao ENABLE ROW LEVEL SECURITY;
ALTER TABLE normalizado.aviso_execucao ENABLE ROW LEVEL SECURITY;
ALTER TABLE normalizado.fatia_historica ENABLE ROW LEVEL SECURITY;
ALTER TABLE bruto.resposta_api ENABLE ROW LEVEL SECURITY;

-- Os grants limitam a política aos comandos da ETL (ADR-0009 §3).
CREATE POLICY etl_carga_acessa ON normalizado.execucao_carga
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON normalizado.contagem_linhas_execucao
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON normalizado.aviso_execucao
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON normalizado.fatia_historica
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON bruto.resposta_api
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);

-- O registro de fim atualiza a execução, e a carga histórica marca as
-- fatias. Contagens e avisos só entram. No bruto, o DELETE é da retenção.
GRANT SELECT, INSERT, UPDATE ON normalizado.execucao_carga, normalizado.fatia_historica TO etl_carga;
GRANT SELECT, INSERT ON normalizado.contagem_linhas_execucao, normalizado.aviso_execucao TO etl_carga;
GRANT SELECT, INSERT, DELETE ON bruto.resposta_api TO etl_carga;
