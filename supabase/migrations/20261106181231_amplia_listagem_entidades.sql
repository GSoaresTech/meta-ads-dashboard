-- A listagem das entidades filhas passa a trazer o que a lista de campanhas
-- da visão da conta exibe: o objetivo e o status em rótulo de negócio, e o
-- resultado principal e o KPI resolvidos (REQUIREMENTS §3.1; RF-37; ADR-0007;
-- ADR-0009 §4). O retorno muda, e por isso a função é recriada, com o grant.
--
-- As colunas novas valem só para as campanhas: as contas e os anúncios as
-- recebem nulas até a visão que as exibir. A função continua sem valor de
-- enum da API na saída, e metrica_resultado e metrica_kpi são códigos do
-- catálogo, de onde o painel lê o rótulo e a unidade. A campanha "Não
-- classificado" tem objetivo, mas não tem resultado nem KPI.
--
-- O restante não muda: p_nivel e p_entidade_pai_id são o nível e a entidade em
-- foco, como no obter_desempenho, e nivel é o das filhas. Os anúncios chegam à
-- campanha pelos conjuntos, que não são nível de navegação (REQUIREMENTS
-- §3.1). A ordem é a do nome, com as entidades ainda sem nome no fim. As
-- filhas saem todas, com ou sem entrega: quem quer só as do período cruza com
-- o obter_desempenho, cujas filhas aparecem só nos períodos com dados.
--
-- Parâmetro fora do domínio levanta 22023. Credencial inválida, revogada ou
-- de outra empresa, e entidade pai que não é da empresa ou do nível pedido,
-- devolvem zero linhas, sem erro (RF-46). O operador lê qualquer empresa
-- (ADR-0004).
DROP FUNCTION analitico.listar_entidades(text, uuid, text, uuid);

CREATE FUNCTION analitico.listar_entidades(
  p_credencial text,
  p_empresa_id uuid,
  p_nivel text,
  p_entidade_pai_id uuid
)
RETURNS TABLE (
  nivel text,
  entidade_id uuid,
  nome text,
  objetivo text,
  status text,
  metrica_resultado text,
  metrica_kpi text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
#variable_conflict use_column
BEGIN
  IF p_nivel IS NULL OR p_nivel NOT IN ('geral', 'conta', 'campanha', 'anuncio') THEN
    RAISE EXCEPTION 'nível inválido' USING ERRCODE = 'invalid_parameter_value';
  END IF;
  IF (p_nivel = 'geral') = (p_entidade_pai_id IS NOT NULL) THEN
    RAISE EXCEPTION 'a entidade pai é nula só no nível geral' USING ERRCODE = 'invalid_parameter_value';
  END IF;

  IF NOT EXISTS (
    SELECT FROM normalizado.resolver_credencial(p_credencial) AS credencial
    WHERE credencial.escopo = 'operador' OR credencial.empresa_id = p_empresa_id
  ) THEN
    RETURN;
  END IF;

  RETURN QUERY
  WITH filha AS (
    SELECT 'conta' AS nivel, conta.id AS entidade_id, conta.nome, NULL::text AS status_api
    FROM normalizado.conta_anuncio AS conta
    WHERE p_nivel = 'geral' AND conta.empresa_id = p_empresa_id
    UNION ALL
    SELECT 'campanha', campanha.id, campanha.nome, campanha.status
    FROM normalizado.campanha AS campanha
    WHERE p_nivel = 'conta' AND campanha.empresa_id = p_empresa_id AND campanha.conta_anuncio_id = p_entidade_pai_id
    UNION ALL
    SELECT 'anuncio', anuncio.id, anuncio.nome, NULL
    FROM normalizado.conjunto_anuncio AS conjunto
    JOIN normalizado.anuncio AS anuncio
      ON anuncio.empresa_id = conjunto.empresa_id AND anuncio.conjunto_anuncio_id = conjunto.id
    WHERE p_nivel = 'campanha' AND conjunto.empresa_id = p_empresa_id AND conjunto.campanha_id = p_entidade_pai_id
  ),
  resultado AS (
    -- A resolução percorre as campanhas da empresa, e só a conta as lista: a
    -- condição poupa o custo dela nos outros níveis.
    SELECT resolvido.campanha_id, resolvido.resultado_objetivo_id, resolvido.metrica_resultado, resolvido.metrica_kpi
    FROM normalizado.resolver_resultado_campanha(p_empresa_id) AS resolvido
    WHERE p_nivel = 'conta'
  )
  SELECT
    filha.nivel,
    filha.entidade_id,
    filha.nome,
    regra.nome_objetivo,
    rotulo.rotulo,
    resultado.metrica_resultado,
    resultado.metrica_kpi
  FROM filha
  LEFT JOIN resultado ON resultado.campanha_id = filha.entidade_id
  LEFT JOIN normalizado.resultado_objetivo AS regra ON regra.id = resultado.resultado_objetivo_id
  LEFT JOIN normalizado.rotulo_valor_api AS rotulo
    ON rotulo.dominio = 'status' AND rotulo.valor = filha.status_api
  ORDER BY filha.nome NULLS LAST, filha.entidade_id;
END
$$;

REVOKE ALL ON FUNCTION analitico.listar_entidades(text, uuid, text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analitico.listar_entidades(text, uuid, text, uuid) TO painel_leitor;
