-- A resolução do resultado somava o investimento dos últimos 28 dias uma vez
-- por conjunto, e cada soma relia as métricas da janela. Com milhares de
-- conjuntos, a maioria sem investimento na janela, o custo passava de 1 s a cada
-- abertura das visões Geral e conta (RNF-06; ADR-0009 §4).
--
-- O investimento passa a ser somado uma só vez, por conjunto, e ligado depois.
-- A regra e o retorno não mudam (ADR-0007), e por isso o CREATE OR REPLACE mantém
-- os grants. Os comentários da função estão na migration que a criou.
CREATE OR REPLACE FUNCTION normalizado.resolver_resultado_campanha(p_empresa_id uuid)
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
  dia_conta AS (
    -- O hoje é o do fuso da conta, o mesmo das datas das métricas. A conta
    -- sem fuso ainda não teve extração e não tem métricas.
    SELECT conta.id AS conta_id, (now() AT TIME ZONE coalesce(conta.fuso_horario, 'UTC'))::date AS hoje
    FROM normalizado.conta_anuncio AS conta
    WHERE conta.empresa_id = p_empresa_id
  ),
  gasto AS (
    -- Uma linha por conjunto com investimento na janela. Os dois limites por
    -- fora deixam o índice (empresa_id, data) ler só a janela, e os de dentro
    -- são os exatos do fuso de cada conta.
    SELECT anuncio.conjunto_anuncio_id, sum(metrica.investimento) AS investimento
    FROM normalizado.metrica_diaria_anuncio AS metrica
    JOIN normalizado.anuncio AS anuncio
      ON anuncio.empresa_id = metrica.empresa_id AND anuncio.id = metrica.anuncio_id
    JOIN normalizado.conjunto_anuncio AS conjunto
      ON conjunto.empresa_id = anuncio.empresa_id AND conjunto.id = anuncio.conjunto_anuncio_id
    JOIN normalizado.campanha AS campanha
      ON campanha.empresa_id = conjunto.empresa_id AND campanha.id = conjunto.campanha_id
    JOIN dia_conta ON dia_conta.conta_id = campanha.conta_anuncio_id
    CROSS JOIN parametro
    WHERE metrica.empresa_id = p_empresa_id
      AND metrica.data > (SELECT min(dia_conta.hoje) FROM dia_conta) - (SELECT parametro.janela_investimento_dias FROM parametro)
      AND metrica.data <= (SELECT max(dia_conta.hoje) FROM dia_conta)
      AND metrica.data > dia_conta.hoje - parametro.janela_investimento_dias
      AND metrica.data <= dia_conta.hoje
    GROUP BY anuncio.conjunto_anuncio_id
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
    LEFT JOIN gasto ON gasto.conjunto_anuncio_id = conjunto.id
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
