-- Rastreio: a conta e as entidades da Meta guardam a última execução que
-- gravou a linha, com FK composta para execucao_carga, para que cada linha
-- chegue à resposta bruta da mesma execução (RF-09; ADR-0009 §1).
--
-- Nas entidades, a coluna é NOT NULL, porque só a ETL as grava, sempre numa
-- execução. Na conta, fica nula entre o cadastro, que informa só o ID
-- (RF-43), e a primeira extração.

ALTER TABLE normalizado.conta_anuncio
  ADD COLUMN execucao_id uuid,
  ADD CONSTRAINT conta_anuncio_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id);

ALTER TABLE normalizado.pagina
  ADD COLUMN execucao_id uuid NOT NULL,
  ADD CONSTRAINT pagina_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id);

ALTER TABLE normalizado.campanha
  ADD COLUMN execucao_id uuid NOT NULL,
  ADD CONSTRAINT campanha_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id);

ALTER TABLE normalizado.conjunto_anuncio
  ADD COLUMN execucao_id uuid NOT NULL,
  ADD CONSTRAINT conjunto_anuncio_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id);

ALTER TABLE normalizado.janela_atribuicao_conjunto
  ADD COLUMN execucao_id uuid NOT NULL,
  ADD CONSTRAINT janela_atribuicao_conjunto_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id);

ALTER TABLE normalizado.criativo
  ADD COLUMN execucao_id uuid NOT NULL,
  ADD CONSTRAINT criativo_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id);

ALTER TABLE normalizado.anuncio
  ADD COLUMN execucao_id uuid NOT NULL,
  ADD CONSTRAINT anuncio_execucao_carga_fkey FOREIGN KEY (empresa_id, execucao_id)
    REFERENCES normalizado.execucao_carga (empresa_id, id);

-- Nas entidades, a etl_carga já inclui e atualiza a linha inteira.
GRANT UPDATE (execucao_id) ON normalizado.conta_anuncio TO etl_carga;
