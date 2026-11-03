-- Entidades da Meta: a hierarquia campanha → conjunto → anúncio → criativo,
-- que liga as métricas ao objetivo e à meta de otimização (RF-01; ADR-0009 §2
-- e §3). A ETL não apaga entidades: uma entidade excluída na Meta fica com
-- status DELETED, e só o estado atual é guardado. A coluna execucao_id entra
-- com a tabela de execuções.
--
-- Os IDs da Meta são "numeric string" (R-35). O UNIQUE de id_meta é global,
-- porque cada entidade pertence a uma única conta, salvo em pagina. As FKs
-- compostas (empresa_id, <pai>_id) impedem apontar para outra empresa.
--
-- Objetivo, meta de otimização, chamada para ação e tipo de evento são
-- domínio aberto: só o formato dos enums da Meta, para que um valor novo não
-- quebre a carga (RF-15). O status é domínio fechado (R-35).

-- Uma Página não pertence a uma conta de anúncios e pode aparecer em
-- criativos de empresas diferentes; cada empresa guarda a própria cópia.
CREATE TABLE normalizado.pagina (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  empresa_id uuid NOT NULL REFERENCES normalizado.empresa (id),
  id_meta text NOT NULL,
  nome text,
  criado_em timestamptz NOT NULL DEFAULT now(),
  atualizado_em timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT pagina_empresa_id_id_meta_key UNIQUE (empresa_id, id_meta),
  CONSTRAINT pagina_empresa_id_id_key UNIQUE (empresa_id, id),
  CONSTRAINT pagina_id_meta_check CHECK (id_meta ~ '^[0-9]+$'),
  CONSTRAINT pagina_nome_check CHECK (nome = btrim(nome) AND nome <> '')
);

CREATE TABLE normalizado.campanha (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  empresa_id uuid NOT NULL REFERENCES normalizado.empresa (id),
  conta_anuncio_id uuid NOT NULL,
  id_meta text NOT NULL UNIQUE,
  nome text,
  objetivo text NOT NULL,
  status text NOT NULL,
  criado_em timestamptz NOT NULL DEFAULT now(),
  atualizado_em timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT campanha_empresa_id_id_key UNIQUE (empresa_id, id),
  CONSTRAINT campanha_conta_anuncio_fkey FOREIGN KEY (empresa_id, conta_anuncio_id)
    REFERENCES normalizado.conta_anuncio (empresa_id, id),
  CONSTRAINT campanha_id_meta_check CHECK (id_meta ~ '^[0-9]+$'),
  CONSTRAINT campanha_nome_check CHECK (nome = btrim(nome) AND nome <> ''),
  CONSTRAINT campanha_objetivo_check CHECK (objetivo ~ '^[A-Z][A-Z0-9_]*$'),
  CONSTRAINT campanha_status_check CHECK (status IN ('ACTIVE', 'PAUSED', 'DELETED', 'ARCHIVED'))
);

CREATE TABLE normalizado.conjunto_anuncio (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  empresa_id uuid NOT NULL REFERENCES normalizado.empresa (id),
  campanha_id uuid NOT NULL,
  id_meta text NOT NULL UNIQUE,
  nome text,
  meta_otimizacao text,
  status text NOT NULL,
  criado_em timestamptz NOT NULL DEFAULT now(),
  atualizado_em timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT conjunto_anuncio_empresa_id_id_key UNIQUE (empresa_id, id),
  CONSTRAINT conjunto_anuncio_campanha_fkey FOREIGN KEY (empresa_id, campanha_id)
    REFERENCES normalizado.campanha (empresa_id, id),
  CONSTRAINT conjunto_anuncio_id_meta_check CHECK (id_meta ~ '^[0-9]+$'),
  CONSTRAINT conjunto_anuncio_nome_check CHECK (nome = btrim(nome) AND nome <> ''),
  CONSTRAINT conjunto_anuncio_meta_otimizacao_check CHECK (meta_otimizacao ~ '^[A-Z][A-Z0-9_]*$'),
  CONSTRAINT conjunto_anuncio_status_check CHECK (status IN ('ACTIVE', 'PAUSED', 'DELETED', 'ARCHIVED'))
);

-- A tabela longa do attribution_spec do conjunto (R-35). A ETL substitui as
-- linhas do conjunto a cada atualização dele.
CREATE TABLE normalizado.janela_atribuicao_conjunto (
  empresa_id uuid NOT NULL REFERENCES normalizado.empresa (id),
  conjunto_anuncio_id uuid NOT NULL,
  tipo_evento text NOT NULL,
  janela_dias integer NOT NULL,
  PRIMARY KEY (empresa_id, conjunto_anuncio_id, tipo_evento),
  CONSTRAINT janela_atribuicao_conjunto_conjunto_anuncio_fkey FOREIGN KEY (empresa_id, conjunto_anuncio_id)
    REFERENCES normalizado.conjunto_anuncio (empresa_id, id),
  CONSTRAINT janela_atribuicao_conjunto_tipo_evento_check CHECK (tipo_evento ~ '^[A-Z][A-Z0-9_]*$'),
  CONSTRAINT janela_atribuicao_conjunto_janela_dias_check CHECK (janela_dias > 0)
);

-- Reutilizável por vários anúncios (N:1). A Página vem do actor_id do
-- criativo (R-35) e pode faltar.
CREATE TABLE normalizado.criativo (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  empresa_id uuid NOT NULL REFERENCES normalizado.empresa (id),
  conta_anuncio_id uuid NOT NULL,
  pagina_id uuid,
  id_meta text NOT NULL UNIQUE,
  titulo text,
  texto text,
  chamada_acao text,
  -- Token "Post ID", não um número (R-35): sem CHECK numérico.
  id_publicacao_facebook text,
  link_publicacao_facebook text,
  id_midia_instagram text,
  link_publicacao_instagram text,
  -- Caminho no Storage, derivado do id interno e nunca do ID da Meta (RF-38).
  caminho_miniatura text,
  criado_em timestamptz NOT NULL DEFAULT now(),
  atualizado_em timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT criativo_empresa_id_id_key UNIQUE (empresa_id, id),
  CONSTRAINT criativo_conta_anuncio_fkey FOREIGN KEY (empresa_id, conta_anuncio_id)
    REFERENCES normalizado.conta_anuncio (empresa_id, id),
  CONSTRAINT criativo_pagina_fkey FOREIGN KEY (empresa_id, pagina_id)
    REFERENCES normalizado.pagina (empresa_id, id),
  CONSTRAINT criativo_id_meta_check CHECK (id_meta ~ '^[0-9]+$'),
  CONSTRAINT criativo_titulo_check CHECK (titulo = btrim(titulo) AND titulo <> ''),
  CONSTRAINT criativo_texto_check CHECK (texto = btrim(texto) AND texto <> ''),
  CONSTRAINT criativo_chamada_acao_check CHECK (chamada_acao ~ '^[A-Z][A-Z0-9_]*$'),
  CONSTRAINT criativo_id_publicacao_facebook_check
    CHECK (id_publicacao_facebook = btrim(id_publicacao_facebook) AND id_publicacao_facebook <> ''),
  CONSTRAINT criativo_link_publicacao_facebook_check
    CHECK (link_publicacao_facebook = btrim(link_publicacao_facebook) AND link_publicacao_facebook <> ''),
  CONSTRAINT criativo_id_midia_instagram_check
    CHECK (id_midia_instagram = btrim(id_midia_instagram) AND id_midia_instagram <> ''),
  CONSTRAINT criativo_link_publicacao_instagram_check
    CHECK (link_publicacao_instagram = btrim(link_publicacao_instagram) AND link_publicacao_instagram <> ''),
  CONSTRAINT criativo_caminho_miniatura_check
    CHECK (caminho_miniatura = btrim(caminho_miniatura) AND caminho_miniatura <> '')
);

-- Não guarda campanha nem conta, deriváveis pelo conjunto.
CREATE TABLE normalizado.anuncio (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  empresa_id uuid NOT NULL REFERENCES normalizado.empresa (id),
  conjunto_anuncio_id uuid NOT NULL,
  criativo_id uuid NOT NULL,
  id_meta text NOT NULL UNIQUE,
  nome text,
  status text NOT NULL,
  criado_em timestamptz NOT NULL DEFAULT now(),
  atualizado_em timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT anuncio_empresa_id_id_key UNIQUE (empresa_id, id),
  CONSTRAINT anuncio_conjunto_anuncio_fkey FOREIGN KEY (empresa_id, conjunto_anuncio_id)
    REFERENCES normalizado.conjunto_anuncio (empresa_id, id),
  CONSTRAINT anuncio_criativo_fkey FOREIGN KEY (empresa_id, criativo_id)
    REFERENCES normalizado.criativo (empresa_id, id),
  CONSTRAINT anuncio_id_meta_check CHECK (id_meta ~ '^[0-9]+$'),
  CONSTRAINT anuncio_nome_check CHECK (nome = btrim(nome) AND nome <> ''),
  CONSTRAINT anuncio_status_check CHECK (status IN ('ACTIVE', 'PAUSED', 'DELETED', 'ARCHIVED'))
);

ALTER TABLE normalizado.pagina ENABLE ROW LEVEL SECURITY;
ALTER TABLE normalizado.campanha ENABLE ROW LEVEL SECURITY;
ALTER TABLE normalizado.conjunto_anuncio ENABLE ROW LEVEL SECURITY;
ALTER TABLE normalizado.janela_atribuicao_conjunto ENABLE ROW LEVEL SECURITY;
ALTER TABLE normalizado.criativo ENABLE ROW LEVEL SECURITY;
ALTER TABLE normalizado.anuncio ENABLE ROW LEVEL SECURITY;

-- Os grants limitam a política aos comandos da ETL (ADR-0009 §3).
CREATE POLICY etl_carga_acessa ON normalizado.pagina
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON normalizado.campanha
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON normalizado.conjunto_anuncio
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON normalizado.janela_atribuicao_conjunto
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON normalizado.criativo
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);
CREATE POLICY etl_carga_acessa ON normalizado.anuncio
  FOR ALL TO etl_carga USING (true) WITH CHECK (true);

-- Sem DELETE nas entidades, que só mudam de status. As janelas do conjunto são
-- substituídas, apagando e incluindo.
GRANT SELECT, INSERT, UPDATE
  ON normalizado.pagina, normalizado.campanha, normalizado.conjunto_anuncio,
     normalizado.criativo, normalizado.anuncio
  TO etl_carga;
GRANT SELECT, INSERT, DELETE ON normalizado.janela_atribuicao_conjunto TO etl_carga;
