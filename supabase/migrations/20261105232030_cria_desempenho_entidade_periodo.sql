-- Desempenho por entidade e período: os números de que o painel precisa para
-- os totais, as séries e as listas de contas, campanhas e anúncios (RF-23,
-- RF-25, RF-32, RF-33, RF-34; ADR-0004; ADR-0009 §4).
--
-- A entidade em foco é a empresa (nível geral), uma conta, uma campanha ou um
-- anúncio. Saem as linhas dela, que repetem p_nivel e p_entidade_id, e as de
-- cada entidade filha: as contas no geral, as campanhas na conta e os
-- anúncios na campanha. O anúncio não tem filhas. Cada linha é uma entidade ×
-- período × moeda × métrica, pelo código do catálogo, de onde vêm o rótulo, a
-- unidade e a explicação (ADR-0007).
--
-- Agregação (REQUIREMENTS §7.1):
-- - as métricas aditivas somam os dias e as entidades. A base ausente fica
--   NULL, e a ação ausente é zero, porque a API omite os tipos sem ocorrência
--   (CLAUDE.md §5);
-- - cada derivada é recalculada a partir das somas do mesmo recorte, com os
--   operandos do catálogo, e fica NULL com denominador zero ou NULL;
-- - alcance e frequência ficam de fora, assim como toda derivada que dependa
--   deles: não se somam entre dias e vêm do alcance por período (ADR-0006).
--
-- Moeda (RF-34): toda linha traz a moeda da conta. No geral, a empresa tem um
-- total por moeda, inclusive nas métricas sem dinheiro, para que cada razão
-- use só contas da mesma moeda.
--
-- Períodos: sempre pela tabela de calendário (CLAUDE.md §5). inicio_periodo e
-- fim_periodo são o dia, a semana ISO, o mês, o ano ou o intervalo inteiro,
-- cortados no intervalo pedido. A entidade em foco tem todo período do
-- intervalo, em cada moeda com dados nele: sem entrega, as aditivas são zero
-- e as razões ficam nulas, para que a série tenha um ponto por período sem
-- que o painel leia o calendário (RF-25). As filhas aparecem só nos períodos
-- com dados, e o intervalo sem nenhum dado devolve zero linhas.

-- A agregação, sem credencial: só a função de analitico abaixo a chama,
-- depois de validar os parâmetros e de resolver a empresa pela credencial.
-- SECURITY INVOKER e sem grant (ADR-0009 §4).
--
-- Desempenho (RNF-06), medido com a massa da empresa de referência:
-- - cada chamada é planejada com os valores dos parâmetros. O plano
--   genérico não conhece o nível, o intervalo nem a granularidade e, nos
--   últimos 30 dias, ficou mais de dez vezes mais lento;
-- - o work_mem cobre a ordenação e o hash das ações de 37 meses dia a dia,
--   que com 4 MB iam para o disco. É um teto, não uma reserva;
-- - as junções são todas por igualdade. Como as estimativas sobre as CTEs
--   erram nos dois sentidos, o planejador escolhia laços aninhados quando
--   subestimava e ordenações de texto quando superestimava, e os dois
--   passavam do RNF-06. O hash foi o melhor plano em todos os cenários.
CREATE FUNCTION normalizado.agregar_desempenho(
  p_empresa_id uuid,
  p_nivel text,
  p_entidade_id uuid,
  p_inicio date,
  p_fim date,
  p_granularidade text
)
RETURNS TABLE (
  nivel text,
  entidade_id uuid,
  inicio_periodo date,
  fim_periodo date,
  moeda text,
  metrica text,
  valor numeric
)
LANGUAGE plpgsql
STABLE
SET search_path = ''
SET plan_cache_mode = force_custom_plan
SET work_mem = '16MB'
SET enable_nestloop = off
SET enable_mergejoin = off
AS $$
#variable_conflict use_column
BEGIN
  RETURN QUERY
  WITH periodo AS (
    -- Cada dia do intervalo e a chave do período a que pertence.
    SELECT
      calendario.data,
      CASE p_granularidade
        WHEN 'dia' THEN calendario.data
        WHEN 'semana' THEN calendario.inicio_semana
        WHEN 'mes' THEN calendario.inicio_mes
        WHEN 'ano' THEN make_date(calendario.ano, 1, 1)
        ELSE p_inicio
      END AS chave
    FROM normalizado.calendario AS calendario
    WHERE calendario.data BETWEEN p_inicio AND p_fim
  ),
  limite AS (
    -- O período cortado no intervalo: a semana que começa antes do início
    -- vem só com os dias pedidos.
    SELECT periodo.chave, min(periodo.data) AS inicio, max(periodo.data) AS fim
    FROM periodo
    GROUP BY periodo.chave
  ),
  anuncio_foco AS (
    -- Os anúncios da entidade em foco, cada um com a filha a que pertence e
    -- a moeda da conta. No anúncio em foco, a filha é ele mesmo.
    SELECT
      anuncio.id AS anuncio_id,
      CASE p_nivel WHEN 'geral' THEN conta.id WHEN 'conta' THEN campanha.id ELSE anuncio.id END AS filha_id,
      conta.moeda
    FROM normalizado.anuncio AS anuncio
    JOIN normalizado.conjunto_anuncio AS conjunto
      ON conjunto.empresa_id = anuncio.empresa_id AND conjunto.id = anuncio.conjunto_anuncio_id
    JOIN normalizado.campanha AS campanha
      ON campanha.empresa_id = conjunto.empresa_id AND campanha.id = conjunto.campanha_id
    JOIN normalizado.conta_anuncio AS conta
      ON conta.empresa_id = campanha.empresa_id AND conta.id = campanha.conta_anuncio_id
    WHERE anuncio.empresa_id = p_empresa_id
      AND CASE p_nivel
        WHEN 'geral' THEN true
        WHEN 'conta' THEN conta.id = p_entidade_id
        WHEN 'campanha' THEN campanha.id = p_entidade_id
        ELSE anuncio.id = p_entidade_id
      END
  ),
  -- Todo recorte com dia de métrica, com as colunas aditivas somadas. O
  -- alcance do dia nunca é somado (ADR-0006). A soma ignora o NULL, e o
  -- recorte sem nenhum valor fica NULL. As ações só existem com o dia, pela
  -- FK.
  recorte AS (
    SELECT
      periodo.chave,
      foco.filha_id,
      foco.moeda,
      sum(diaria.investimento) AS investimento,
      sum(diaria.impressoes) AS impressoes
    FROM normalizado.metrica_diaria_anuncio AS diaria
    JOIN anuncio_foco AS foco ON foco.anuncio_id = diaria.anuncio_id
    JOIN periodo ON periodo.data = diaria.data
    WHERE diaria.empresa_id = p_empresa_id
      AND diaria.data BETWEEN p_inicio AND p_fim
    GROUP BY periodo.chave, foco.filha_id, foco.moeda
  ),
  base AS (
    -- O catálogo escolhe, pelo campo_base, quais colunas somadas são
    -- métricas.
    SELECT
      recorte.chave,
      recorte.filha_id,
      recorte.moeda,
      metrica.codigo AS metrica,
      -- Uma métrica base aditiva nova precisa do WHEN da coluna dela. Sem
      -- ele, sairia nula, e o desempenho_test.sql falha.
      CASE metrica.campo_base
        WHEN 'investimento' THEN recorte.investimento
        WHEN 'impressoes' THEN recorte.impressoes
      END AS valor
    FROM recorte
    JOIN normalizado.metrica AS metrica ON metrica.tipo = 'base' AND metrica.aditiva
  ),
  acao AS (
    SELECT
      periodo.chave,
      foco.filha_id,
      metrica.codigo AS metrica,
      sum(CASE metrica.medida_acao WHEN 'quantidade' THEN acao.quantidade ELSE acao.valor END) AS valor
    FROM normalizado.acao_diaria_anuncio AS acao
    JOIN normalizado.metrica AS metrica
      ON metrica.tipo = 'acao' AND metrica.aditiva AND metrica.tipo_acao = acao.tipo_acao
    JOIN anuncio_foco AS foco ON foco.anuncio_id = acao.anuncio_id
    JOIN periodo ON periodo.data = acao.data
    WHERE acao.empresa_id = p_empresa_id
      AND acao.data BETWEEN p_inicio AND p_fim
    GROUP BY periodo.chave, foco.filha_id, metrica.codigo
  ),
  aditiva_filha AS (
    SELECT base.chave, base.filha_id, base.moeda, base.metrica, base.valor
    FROM base
    UNION ALL
    -- A ação sem linha no recorte é zero.
    SELECT recorte.chave, recorte.filha_id, recorte.moeda, metrica.codigo, coalesce(acao.valor, 0)
    FROM recorte
    CROSS JOIN normalizado.metrica AS metrica
    LEFT JOIN acao
      ON acao.chave = recorte.chave AND acao.filha_id = recorte.filha_id AND acao.metrica = metrica.codigo
    WHERE metrica.tipo = 'acao'
      AND metrica.aditiva
  ),
  proprio AS (
    SELECT aditiva_filha.chave, aditiva_filha.moeda, aditiva_filha.metrica, sum(aditiva_filha.valor) AS valor
    FROM aditiva_filha
    GROUP BY aditiva_filha.chave, aditiva_filha.moeda, aditiva_filha.metrica
  ),
  aditiva AS (
    -- As filhas e a entidade em foco, que é a soma delas por moeda. A chave
    -- da entidade troca o NULL do geral pela empresa, para as junções, e
    -- sozinha já distingue os níveis, porque os IDs internos não se repetem.
    SELECT
      CASE p_nivel WHEN 'geral' THEN 'conta' WHEN 'conta' THEN 'campanha' ELSE 'anuncio' END AS nivel,
      aditiva_filha.filha_id AS entidade_id,
      aditiva_filha.filha_id AS chave_entidade,
      aditiva_filha.chave,
      aditiva_filha.moeda,
      aditiva_filha.metrica,
      aditiva_filha.valor
    FROM aditiva_filha
    WHERE p_nivel <> 'anuncio'
    UNION ALL
    -- O período sem nenhum recorte é zero; o recorte com a soma nula, como
    -- o de impressões não informadas, continua nulo.
    SELECT
      p_nivel,
      p_entidade_id,
      coalesce(p_entidade_id, p_empresa_id),
      limite.chave,
      moeda.moeda,
      metrica.codigo,
      CASE WHEN proprio.metrica IS NULL THEN 0 ELSE proprio.valor END
    FROM limite
    CROSS JOIN (SELECT DISTINCT recorte.moeda FROM recorte) AS moeda
    CROSS JOIN normalizado.metrica AS metrica
    LEFT JOIN proprio
      ON proprio.chave = limite.chave AND proprio.moeda = moeda.moeda AND proprio.metrica = metrica.codigo
    WHERE metrica.tipo IN ('base', 'acao')
      AND metrica.aditiva
  ),
  -- MATERIALIZED: as poucas derivadas viram uma tabela pequena na junção com
  -- as aditivas, em vez de uma consulta ao catálogo por linha.
  derivada AS MATERIALIZED (
    -- As derivadas cujos dois operandos são aditivos.
    SELECT metrica.codigo, metrica.numerador, metrica.denominador, metrica.fator
    FROM normalizado.metrica AS metrica
    JOIN normalizado.metrica AS numerador ON numerador.codigo = metrica.numerador
    JOIN normalizado.metrica AS denominador ON denominador.codigo = metrica.denominador
    WHERE metrica.tipo = 'derivada'
      AND numerador.aditiva
      AND denominador.aditiva
  ),
  resultado AS (
    SELECT aditiva.nivel, aditiva.entidade_id, aditiva.chave, aditiva.moeda, aditiva.metrica, aditiva.valor
    FROM aditiva
    UNION ALL
    SELECT
      numerador.nivel,
      numerador.entidade_id,
      numerador.chave,
      numerador.moeda,
      derivada.codigo,
      numerador.valor / nullif(denominador.valor, 0) * derivada.fator
    FROM derivada
    JOIN aditiva AS numerador ON numerador.metrica = derivada.numerador
    JOIN aditiva AS denominador
      ON denominador.chave_entidade = numerador.chave_entidade
     AND denominador.chave = numerador.chave
     AND denominador.moeda = numerador.moeda
     AND denominador.metrica = derivada.denominador
  )
  SELECT resultado.nivel, resultado.entidade_id, limite.inicio, limite.fim, resultado.moeda, resultado.metrica, resultado.valor
  FROM resultado
  JOIN limite ON limite.chave = resultado.chave;
END
$$;

REVOKE ALL ON FUNCTION normalizado.agregar_desempenho(uuid, text, uuid, date, date, text) FROM PUBLIC;

-- A porta do painel. Parâmetro fora do domínio levanta 22023; credencial
-- inválida, revogada ou de outra empresa devolve zero linhas, sem erro, para
-- que a rota responda 404 sem revelar se a empresa existe (RF-46). O
-- operador lê qualquer empresa (ADR-0004).
CREATE FUNCTION analitico.obter_desempenho(
  p_credencial text,
  p_empresa_id uuid,
  p_nivel text,
  p_entidade_id uuid,
  p_inicio date,
  p_fim date,
  p_granularidade text
)
RETURNS TABLE (
  nivel text,
  entidade_id uuid,
  inicio_periodo date,
  fim_periodo date,
  moeda text,
  metrica text,
  valor numeric
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  IF p_nivel IS NULL OR p_nivel NOT IN ('geral', 'conta', 'campanha', 'anuncio') THEN
    RAISE EXCEPTION 'nível inválido' USING ERRCODE = 'invalid_parameter_value';
  END IF;
  IF (p_nivel = 'geral') = (p_entidade_id IS NOT NULL) THEN
    RAISE EXCEPTION 'a entidade é nula só no nível geral' USING ERRCODE = 'invalid_parameter_value';
  END IF;
  IF p_granularidade IS NULL OR p_granularidade NOT IN ('dia', 'semana', 'mes', 'ano', 'periodo') THEN
    RAISE EXCEPTION 'granularidade inválida' USING ERRCODE = 'invalid_parameter_value';
  END IF;
  IF p_inicio IS NULL OR p_fim IS NULL OR p_inicio > p_fim THEN
    RAISE EXCEPTION 'intervalo inválido' USING ERRCODE = 'invalid_parameter_value';
  END IF;

  IF NOT EXISTS (
    SELECT FROM normalizado.resolver_credencial(p_credencial) AS credencial
    WHERE credencial.escopo = 'operador' OR credencial.empresa_id = p_empresa_id
  ) THEN
    RETURN;
  END IF;

  RETURN QUERY
  SELECT *
  FROM normalizado.agregar_desempenho(p_empresa_id, p_nivel, p_entidade_id, p_inicio, p_fim, p_granularidade);
END
$$;

REVOKE ALL ON FUNCTION analitico.obter_desempenho(text, uuid, text, uuid, date, date, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analitico.obter_desempenho(text, uuid, text, uuid, date, date, text) TO painel_leitor;
