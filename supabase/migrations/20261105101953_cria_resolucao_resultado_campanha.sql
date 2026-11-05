-- Resolução do resultado principal de cada campanha, com a precedência do
-- ADR-0007, num só lugar: as funções de analitico a usam para exibir, e a
-- etl_carga a executa para os avisos do RF-15 e a comparação do RF-16
-- (RF-14, RF-15; ADR-0009 §4).
--
-- A precedência, por conjunto de anúncios: objetivo + meta de otimização do
-- conjunto > objetivo + "qualquer" > "Não classificado". O objetivo legado
-- passa antes pelo equivalente atual (REQUIREMENTS §7.2). A campanha usa a
-- regra do conjunto com maior investimento nos últimos 28 dias, o que só
-- decide quando os conjuntos divergem; a sobrescrita, por fim, vence o par
-- resultado e KPI do catálogo.
--
-- Devolve uma linha por campanha da empresa:
-- - resultado_objetivo_id: a regra do catálogo, que dá o nome do objetivo e
--   as métricas de apoio mesmo com sobrescrita. A regra sem objetivo é
--   "Não classificado";
-- - metrica_resultado e metrica_kpi: os da sobrescrita, se houver, ou os da
--   regra, nulos em "Não classificado" e no resultado a confirmar;
-- - sobrescrita: se o par veio da sobrescrita.
--
-- Sem credencial e SECURITY INVOKER: quem chama é a etl_carga, com os
-- próprios grants, ou uma função de analitico, que já resolveu a empresa
-- pela credencial (ADR-0009 §4).
CREATE FUNCTION normalizado.resolver_resultado_campanha(p_empresa_id uuid)
RETURNS TABLE (
  campanha_id uuid,
  resultado_objetivo_id uuid,
  metrica_resultado text,
  metrica_kpi text,
  sobrescrita boolean
)
LANGUAGE sql
STABLE
SET search_path = ''
AS $$
  WITH parametro AS (
    -- A janela do critério de conjuntos divergentes (ADR-0007; Q-08): os 28
    -- dias até hoje, inclusive, que a carga horária já preenche.
    SELECT 28 AS janela_investimento_dias
  ),
  regra_conjunto AS (
    -- Uma linha por conjunto. A campanha sem conjunto entra uma vez, sem
    -- meta de otimização, e cai na regra de "qualquer" do objetivo.
    SELECT
      campanha.id AS campanha_id,
      conjunto.id_meta AS id_meta_conjunto,
      regra.id AS resultado_objetivo_id,
      coalesce(gasto.investimento, 0) AS investimento
    FROM normalizado.campanha AS campanha
    JOIN normalizado.conta_anuncio AS conta
      ON conta.empresa_id = campanha.empresa_id AND conta.id = campanha.conta_anuncio_id
    CROSS JOIN parametro
    -- O hoje é o do fuso da conta, o mesmo das datas das métricas. A conta
    -- sem fuso ainda não teve extração e não tem métricas.
    CROSS JOIN LATERAL (
      SELECT (now() AT TIME ZONE coalesce(conta.fuso_horario, 'UTC'))::date AS hoje
    ) AS dia
    LEFT JOIN normalizado.conjunto_anuncio AS conjunto
      ON conjunto.empresa_id = campanha.empresa_id AND conjunto.campanha_id = campanha.id
    LEFT JOIN normalizado.objetivo_equivalente AS equivalente
      ON equivalente.objetivo_legado = campanha.objetivo
    -- A regra específica, a de "qualquer" e, por fim, "Não classificado",
    -- que é a linha sem objetivo.
    LEFT JOIN LATERAL (
      SELECT candidata.id
      FROM normalizado.resultado_objetivo AS candidata
      WHERE candidata.objetivo IS NULL
         OR (
           candidata.objetivo = coalesce(equivalente.objetivo, campanha.objetivo)
           AND (candidata.meta_otimizacao IS NULL OR candidata.meta_otimizacao = conjunto.meta_otimizacao)
         )
      ORDER BY candidata.objetivo IS NULL, candidata.meta_otimizacao IS NULL
      LIMIT 1
    ) AS regra ON true
    LEFT JOIN LATERAL (
      SELECT sum(metrica.investimento) AS investimento
      FROM normalizado.anuncio AS anuncio
      JOIN normalizado.metrica_diaria_anuncio AS metrica
        ON metrica.empresa_id = anuncio.empresa_id AND metrica.anuncio_id = anuncio.id
      WHERE anuncio.empresa_id = conjunto.empresa_id
        AND anuncio.conjunto_anuncio_id = conjunto.id
        AND metrica.data > dia.hoje - parametro.janela_investimento_dias
        AND metrica.data <= dia.hoje
    ) AS gasto ON true
    WHERE campanha.empresa_id = p_empresa_id
  ),
  regra_campanha AS (
    -- O conjunto de maior investimento na janela. No empate, inclusive sem
    -- investimento, o de menor ID da Meta, em ordem numérica, para que a
    -- escolha não mude entre execuções.
    SELECT DISTINCT ON (regra_conjunto.campanha_id)
      regra_conjunto.campanha_id,
      regra_conjunto.resultado_objetivo_id
    FROM regra_conjunto
    ORDER BY
      regra_conjunto.campanha_id,
      regra_conjunto.investimento DESC,
      regra_conjunto.id_meta_conjunto::numeric
  )
  SELECT
    regra_campanha.campanha_id,
    regra_campanha.resultado_objetivo_id,
    CASE WHEN definida.campanha_id IS NULL THEN regra.metrica_resultado ELSE definida.metrica_resultado END,
    CASE WHEN definida.campanha_id IS NULL THEN regra.metrica_kpi ELSE definida.metrica_kpi END,
    definida.campanha_id IS NOT NULL
  FROM regra_campanha
  LEFT JOIN normalizado.resultado_objetivo AS regra ON regra.id = regra_campanha.resultado_objetivo_id
  LEFT JOIN normalizado.sobrescrita_resultado_campanha AS definida
    ON definida.empresa_id = p_empresa_id AND definida.campanha_id = regra_campanha.campanha_id
$$;

REVOKE ALL ON FUNCTION normalizado.resolver_resultado_campanha(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION normalizado.resolver_resultado_campanha(uuid) TO etl_carga;
