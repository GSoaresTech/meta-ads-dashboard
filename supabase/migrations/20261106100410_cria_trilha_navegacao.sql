-- Trilha de navegação: o caminho de Geral até a entidade em foco, com o nome
-- de cada nível, para a trilha da página, e os fusos das contas que cada
-- nível abrange, para os atalhos de período (RF-23, RF-26; REQUIREMENTS
-- §3.3; ADR-0004; ADR-0009 §4).
--
-- Sai uma linha por nível, em ordem: o geral, com o nome da empresa, e, abaixo
-- dele, a conta, a campanha e o anúncio que levam à entidade em foco. O
-- conjunto de anúncios liga o anúncio à campanha, mas não é nível de
-- navegação (REQUIREMENTS §3.1).
--
-- Fusos: o geral abrange todas as contas da empresa, cada fuso uma vez, e os
-- demais níveis, só o da conta deles. A conta ainda sem a primeira extração
-- não tem fuso (ADR-0009 §2) e fica de fora. O painel escolhe, entre os
-- fusos, o de dia corrente mais atrasado, pelo relógio dele, e por isso a
-- função não lê a hora.
--
-- Parâmetro fora do domínio levanta 22023. Credencial inválida, revogada ou
-- de outra empresa, e entidade que não é da empresa ou do nível pedido,
-- devolvem zero linhas, sem erro, para que a rota responda 404 sem revelar se
-- a empresa ou a entidade existe (RF-46). O operador lê qualquer empresa
-- (ADR-0004).
CREATE FUNCTION analitico.obter_trilha(
  p_credencial text,
  p_empresa_id uuid,
  p_nivel text,
  p_entidade_id uuid
)
RETURNS TABLE (nivel text, entidade_id uuid, nome text, fusos_horarios text[])
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
  IF (p_nivel = 'geral') = (p_entidade_id IS NOT NULL) THEN
    RAISE EXCEPTION 'a entidade é nula só no nível geral' USING ERRCODE = 'invalid_parameter_value';
  END IF;

  IF NOT EXISTS (
    SELECT FROM normalizado.resolver_credencial(p_credencial) AS credencial
    WHERE credencial.escopo = 'operador' OR credencial.empresa_id = p_empresa_id
  ) THEN
    RETURN;
  END IF;

  RETURN QUERY
  WITH caminho AS (
    -- A conta, a campanha e o anúncio da entidade em foco, nulos abaixo
    -- dela. Sem linha, a entidade não é da empresa ou do nível pedido.
    SELECT NULL::uuid AS conta_id, NULL::uuid AS campanha_id, NULL::uuid AS anuncio_id
    WHERE p_nivel = 'geral'
    UNION ALL
    SELECT conta.id, NULL, NULL
    FROM normalizado.conta_anuncio AS conta
    WHERE p_nivel = 'conta' AND conta.empresa_id = p_empresa_id AND conta.id = p_entidade_id
    UNION ALL
    SELECT campanha.conta_anuncio_id, campanha.id, NULL
    FROM normalizado.campanha AS campanha
    WHERE p_nivel = 'campanha' AND campanha.empresa_id = p_empresa_id AND campanha.id = p_entidade_id
    UNION ALL
    SELECT campanha.conta_anuncio_id, campanha.id, anuncio.id
    FROM normalizado.anuncio AS anuncio
    JOIN normalizado.conjunto_anuncio AS conjunto
      ON conjunto.empresa_id = anuncio.empresa_id AND conjunto.id = anuncio.conjunto_anuncio_id
    JOIN normalizado.campanha AS campanha
      ON campanha.empresa_id = conjunto.empresa_id AND campanha.id = conjunto.campanha_id
    WHERE p_nivel = 'anuncio' AND anuncio.empresa_id = p_empresa_id AND anuncio.id = p_entidade_id
  ),
  conta_foco AS (
    SELECT conta.id, conta.nome, array_remove(ARRAY[conta.fuso_horario], NULL) AS fusos_horarios
    FROM caminho
    JOIN normalizado.conta_anuncio AS conta ON conta.empresa_id = p_empresa_id AND conta.id = caminho.conta_id
  ),
  linha AS (
    SELECT
      1 AS ordem,
      'geral' AS nivel,
      NULL::uuid AS entidade_id,
      empresa.nome,
      (
        SELECT coalesce(
          array_agg(DISTINCT conta.fuso_horario ORDER BY conta.fuso_horario)
            FILTER (WHERE conta.fuso_horario IS NOT NULL),
          '{}'
        )
        FROM normalizado.conta_anuncio AS conta
        WHERE conta.empresa_id = p_empresa_id
      ) AS fusos_horarios
    FROM caminho
    CROSS JOIN normalizado.empresa AS empresa
    WHERE empresa.id = p_empresa_id
    UNION ALL
    SELECT 2, 'conta', conta_foco.id, conta_foco.nome, conta_foco.fusos_horarios
    FROM conta_foco
    UNION ALL
    SELECT 3, 'campanha', campanha.id, campanha.nome, conta_foco.fusos_horarios
    FROM caminho
    JOIN normalizado.campanha AS campanha
      ON campanha.empresa_id = p_empresa_id AND campanha.id = caminho.campanha_id
    CROSS JOIN conta_foco
    UNION ALL
    SELECT 4, 'anuncio', anuncio.id, anuncio.nome, conta_foco.fusos_horarios
    FROM caminho
    JOIN normalizado.anuncio AS anuncio
      ON anuncio.empresa_id = p_empresa_id AND anuncio.id = caminho.anuncio_id
    CROSS JOIN conta_foco
  )
  SELECT linha.nivel, linha.entidade_id, linha.nome, linha.fusos_horarios
  FROM linha
  ORDER BY linha.ordem;
END
$$;

REVOKE ALL ON FUNCTION analitico.obter_trilha(text, uuid, text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analitico.obter_trilha(text, uuid, text, uuid) TO painel_leitor;
