-- Alcance e frequência por entidade e período: o alcance extraído por semana
-- ISO, mês e ano, as métricas que dependem dele ou o motivo de cada "Não
-- disponível" (REQUIREMENTS §3.3; RF-33; ADR-0006; ADR-0009 §4; ADR-0016).
--
-- As entidades, os períodos e as moedas são os da obter_desempenho, para que
-- o painel junte as duas leituras: a entidade em foco em todo período do
-- intervalo, em cada moeda com entrega nele, e as filhas só nos períodos com
-- entrega. O intervalo sem nenhuma entrega devolve zero linhas.
--
-- As métricas vêm do catálogo (ADR-0007): as bases não aditivas, como o
-- alcance, e as derivadas com um operando entre elas, como a frequência e o
-- custo por mil pessoas alcançadas. As demais ficam com a obter_desempenho.
-- O alcance e as impressões vêm da mesma resposta da API (ADR-0006), e o
-- investimento é a soma dos dias que o alcance cobre.
--
-- Em cada entidade e período, nesta ordem (ADR-0016):
-- 1. o Geral de empresa com mais de uma conta cadastrada não tem alcance
--    (varias_contas);
-- 2. a linha extraída que começa no primeiro dia do período exibido, termina
--    dentro dele e é de uma semana, um mês ou um ano que o contém dá o
--    valor, apurado até o fim dela. Assim o período em andamento, extraído
--    só até a última rotina diária, também tem valor. Entre as que servem,
--    vale a extraída até mais tarde;
-- 3. sem linha extraída, a semana, o mês ou o ano inteiro, ou o período em
--    andamento desde o primeiro dia até hoje, está fora do limite de 37
--    meses quando começa antes do primeiro dia que a carga histórica
--    extrairia hoje (limite_historico), tem alcance zero sem entrega e, com
--    entrega, ainda não foi extraído (nao_extraido);
-- 4. o resto é período livre (periodo_livre).

-- A agregação, sem credencial: só a função de analitico abaixo a chama,
-- depois de validar os parâmetros e de resolver a empresa pela credencial.
-- SECURITY INVOKER e sem grant (ADR-0009 §4). Como a agregar_desempenho, é
-- planejada a cada chamada com os valores dos parâmetros: na mesma conexão,
-- a partir da sexta chamada o plano genérico triplicava o tempo do Geral em
-- 37 meses por semana e passava do RNF-06 com a massa da empresa de
-- referência.
CREATE FUNCTION normalizado.agregar_alcance(
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
  valor numeric,
  fim_apurado date,
  motivo text
)
LANGUAGE plpgsql
STABLE
SET search_path = ''
SET plan_cache_mode = force_custom_plan
AS $$
#variable_conflict use_column
BEGIN
  RETURN QUERY
  WITH parametro AS (
    -- A Meta aceita o since a partir de hoje menos 37 meses, no mesmo dia do
    -- mês (R-19). A carga histórica soma uma margem de um dia, porque não
    -- sabemos em que fuso a Meta conta o hoje: os mesmos HISTORICO_MAXIMO_MESES
    -- e MARGEM_LIMITE_HISTORICO_DIAS de etl/configuracao.py.
    SELECT 37 AS historico_maximo_meses, 1 AS margem_limite_historico_dias
  ),
  periodo AS (
    -- Cada dia do intervalo e a chave do período a que pertence, pelo
    -- calendário (CLAUDE.md §5), como na obter_desempenho.
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
    -- O período exibido, cortado no intervalo.
    SELECT periodo.chave, min(periodo.data) AS inicio, max(periodo.data) AS fim
    FROM periodo
    GROUP BY periodo.chave
  ),
  periodo_calendario AS (
    -- A semana ISO, o mês e o ano que começam no intervalo, com o último dia
    -- de cada um. A ordem desempata o extraído até o mesmo dia.
    SELECT 'semana' AS tipo_periodo, calendario.inicio_semana AS inicio, max(calendario.data) AS fim, 1 AS ordem
    FROM normalizado.calendario AS calendario
    WHERE calendario.inicio_semana BETWEEN p_inicio AND p_fim
    GROUP BY calendario.inicio_semana
    UNION ALL
    SELECT 'mes', calendario.inicio_mes, max(calendario.data), 2
    FROM normalizado.calendario AS calendario
    WHERE calendario.inicio_mes BETWEEN p_inicio AND p_fim
    GROUP BY calendario.inicio_mes
    UNION ALL
    SELECT 'ano', min(calendario.data), max(calendario.data), 3
    FROM normalizado.calendario AS calendario
    GROUP BY calendario.ano
    HAVING min(calendario.data) BETWEEN p_inicio AND p_fim
  ),
  coincidencia AS (
    -- Cada período exibido e os de calendário que começam no mesmo dia e o
    -- contêm, com a indicação de que ele é o período de calendário inteiro.
    SELECT
      limite.chave,
      calendario.tipo_periodo,
      calendario.ordem,
      calendario.inicio,
      limite.fim,
      calendario.fim = limite.fim AS inteiro
    FROM limite
    JOIN periodo_calendario AS calendario
      ON calendario.inicio = limite.inicio AND calendario.fim >= limite.fim
  ),
  conta_empresa AS (
    SELECT count(*) AS contas
    FROM normalizado.conta_anuncio AS conta
    WHERE conta.empresa_id = p_empresa_id
  ),
  anuncio_entidade AS (
    -- Cada anúncio da entidade em foco, uma vez pela filha a que pertence e
    -- uma vez pela própria entidade em foco; o anúncio em foco não tem
    -- filhas. A chave do alcance é a entidade cuja linha extraída vale, e a
    -- chave da entidade troca o NULL do Geral pela empresa, para as junções.
    -- O fuso, que dá o limite de 37 meses, é o da conta da chave do alcance.
    SELECT
      anuncio.id AS anuncio_id,
      entidade.nivel,
      entidade.entidade_id,
      coalesce(entidade.entidade_id, p_empresa_id) AS chave_entidade,
      entidade.chave_alcance,
      CASE WHEN entidade.chave_alcance IS NOT NULL THEN conta.fuso_horario END AS fuso_horario,
      conta.moeda
    FROM normalizado.anuncio AS anuncio
    JOIN normalizado.conjunto_anuncio AS conjunto
      ON conjunto.empresa_id = anuncio.empresa_id AND conjunto.id = anuncio.conjunto_anuncio_id
    JOIN normalizado.campanha AS campanha
      ON campanha.empresa_id = conjunto.empresa_id AND campanha.id = conjunto.campanha_id
    JOIN normalizado.conta_anuncio AS conta
      ON conta.empresa_id = campanha.empresa_id AND conta.id = campanha.conta_anuncio_id
    CROSS JOIN conta_empresa
    CROSS JOIN LATERAL (
      VALUES
        (
          CASE p_nivel WHEN 'geral' THEN 'conta' WHEN 'conta' THEN 'campanha' ELSE 'anuncio' END,
          CASE p_nivel WHEN 'geral' THEN conta.id WHEN 'conta' THEN campanha.id ELSE anuncio.id END,
          CASE p_nivel WHEN 'geral' THEN conta.id WHEN 'conta' THEN campanha.id ELSE anuncio.id END,
          true
        ),
        -- No Geral, a linha de alcance é a da conta, e só na empresa com uma
        -- conta cadastrada (ADR-0016).
        (
          p_nivel,
          p_entidade_id,
          CASE WHEN p_nivel <> 'geral' THEN p_entidade_id WHEN conta_empresa.contas = 1 THEN conta.id END,
          false
        )
    ) AS entidade (nivel, entidade_id, chave_alcance, filha)
    WHERE anuncio.empresa_id = p_empresa_id
      AND CASE p_nivel
        WHEN 'geral' THEN true
        WHEN 'conta' THEN conta.id = p_entidade_id
        WHEN 'campanha' THEN campanha.id = p_entidade_id
        ELSE anuncio.id = p_entidade_id
      END
      AND NOT (entidade.filha AND p_nivel = 'anuncio')
  ),
  dia_entidade AS (
    -- O investimento de cada entidade em cada dia com métrica. A soma
    -- ignora o NULL, e o dia sem nenhum valor fica NULL.
    SELECT
      entidade.nivel,
      entidade.entidade_id,
      entidade.chave_entidade,
      entidade.chave_alcance,
      entidade.fuso_horario,
      entidade.moeda,
      periodo.chave,
      diaria.data,
      sum(diaria.investimento) AS investimento
    FROM normalizado.metrica_diaria_anuncio AS diaria
    JOIN anuncio_entidade AS entidade ON entidade.anuncio_id = diaria.anuncio_id
    JOIN periodo ON periodo.data = diaria.data
    WHERE diaria.empresa_id = p_empresa_id
      AND diaria.data BETWEEN p_inicio AND p_fim
    GROUP BY
      entidade.nivel, entidade.entidade_id, entidade.chave_entidade, entidade.chave_alcance,
      entidade.fuso_horario, entidade.moeda, periodo.chave, diaria.data
  ),
  entidade_periodo AS (
    -- Como na obter_desempenho, as filhas aparecem só nos períodos com
    -- entrega, e a entidade em foco em todo período do intervalo, em cada
    -- moeda com entrega nele.
    SELECT DISTINCT
      dia.nivel, dia.entidade_id, dia.chave_entidade, dia.chave_alcance, dia.fuso_horario, dia.moeda, dia.chave
    FROM dia_entidade AS dia
    WHERE dia.nivel <> p_nivel
    UNION ALL
    SELECT foco.nivel, foco.entidade_id, foco.chave_entidade, foco.chave_alcance, foco.fuso_horario, foco.moeda, limite.chave
    FROM (
      SELECT DISTINCT dia.nivel, dia.entidade_id, dia.chave_entidade, dia.chave_alcance, dia.fuso_horario, dia.moeda
      FROM dia_entidade AS dia
      WHERE dia.nivel = p_nivel
    ) AS foco
    CROSS JOIN limite
  ),
  entregue AS (
    SELECT DISTINCT dia.chave_entidade, dia.moeda, dia.chave
    FROM dia_entidade AS dia
  ),
  extraido AS (
    -- As linhas de alcance que começam no intervalo. Os IDs internos não se
    -- repetem entre níveis, e a primeira entidade preenchida identifica a
    -- linha.
    SELECT
      coalesce(alcance.conta_anuncio_id, alcance.campanha_id, alcance.anuncio_id) AS chave_alcance,
      alcance.tipo_periodo,
      alcance.inicio_periodo,
      alcance.fim_periodo,
      alcance.alcance,
      alcance.impressoes
    FROM normalizado.alcance_periodo AS alcance
    WHERE alcance.empresa_id = p_empresa_id
      AND alcance.inicio_periodo BETWEEN p_inicio AND p_fim
  ),
  apurado AS (
    -- A linha extraída que dá o valor de cada entidade e período (regra 2).
    SELECT DISTINCT ON (linha.chave_entidade, linha.moeda, linha.chave)
      linha.chave_entidade,
      linha.moeda,
      linha.chave,
      extraido.fim_periodo,
      extraido.alcance,
      extraido.impressoes
    FROM entidade_periodo AS linha
    JOIN coincidencia ON coincidencia.chave = linha.chave
    JOIN extraido
      ON extraido.chave_alcance = linha.chave_alcance
     AND extraido.tipo_periodo = coincidencia.tipo_periodo
     AND extraido.inicio_periodo = coincidencia.inicio
     AND extraido.fim_periodo <= coincidencia.fim
    ORDER BY linha.chave_entidade, linha.moeda, linha.chave, extraido.fim_periodo DESC, coincidencia.ordem
  ),
  investimento_apurado AS (
    -- O investimento dos dias que o alcance cobre, sem os dias do período
    -- em andamento que ele ainda não cobre.
    SELECT apurado.chave_entidade, apurado.moeda, apurado.chave, sum(dia.investimento) AS investimento
    FROM apurado
    JOIN dia_entidade AS dia
      ON dia.chave_entidade = apurado.chave_entidade
     AND dia.moeda = apurado.moeda
     AND dia.chave = apurado.chave
    WHERE dia.data <= apurado.fim_periodo
    GROUP BY apurado.chave_entidade, apurado.moeda, apurado.chave
  ),
  dia_conta AS (
    -- Hoje no fuso de cada conta e o primeiro dia que a carga histórica
    -- extrairia hoje: o mesmo cálculo de calcular_limite_historico, em
    -- etl/carga_historica.py, com o dia contado a partir do dia 1 do mês do
    -- limite, o que leva para o mês seguinte o dia que não existe nele. Sem
    -- fuso, a linha é do Geral de várias contas, que não tem alcance.
    SELECT
      fuso.fuso_horario,
      min(dia.data) AS hoje,
      max(
        (dia.inicio_mes - make_interval(months => parametro.historico_maximo_meses))::date
        + (dia.data - dia.inicio_mes)
      ) AS limite_historico
    FROM (SELECT DISTINCT linha.fuso_horario FROM entidade_periodo AS linha) AS fuso
    CROSS JOIN parametro
    JOIN normalizado.calendario AS dia
      ON dia.data BETWEEN (now() AT TIME ZONE fuso.fuso_horario)::date
                      AND (now() AT TIME ZONE fuso.fuso_horario)::date + parametro.margem_limite_historico_dias
    GROUP BY fuso.fuso_horario
  ),
  sem_linha AS (
    -- Os períodos exibidos sem linha extraída da entidade que são uma
    -- semana, um mês ou um ano inteiro, ou o período em andamento desde o
    -- primeiro dia até hoje (regra 3).
    SELECT DISTINCT linha.chave_entidade, linha.moeda, linha.chave
    FROM entidade_periodo AS linha
    JOIN dia_conta ON dia_conta.fuso_horario = linha.fuso_horario
    JOIN coincidencia
      ON coincidencia.chave = linha.chave
     AND (coincidencia.inteiro OR dia_conta.hoje BETWEEN coincidencia.inicio AND coincidencia.fim)
    WHERE NOT EXISTS (
      SELECT FROM extraido
      WHERE extraido.chave_alcance = linha.chave_alcance
        AND extraido.tipo_periodo = coincidencia.tipo_periodo
        AND extraido.inicio_periodo = coincidencia.inicio
    )
  ),
  situacao AS (
    SELECT
      linha.nivel,
      linha.entidade_id,
      limite.inicio,
      limite.fim,
      linha.moeda,
      apurado.fim_periodo AS fim_extraido,
      apurado.alcance,
      apurado.impressoes,
      investimento_apurado.investimento,
      CASE
        WHEN linha.chave_alcance IS NULL THEN 'varias_contas'
        WHEN apurado.chave IS NOT NULL THEN NULL
        WHEN sem_linha.chave IS NULL THEN 'periodo_livre'
        WHEN limite.inicio < dia_conta.limite_historico THEN 'limite_historico'
        WHEN entregue.chave IS NOT NULL THEN 'nao_extraido'
      END AS motivo
    FROM entidade_periodo AS linha
    JOIN limite ON limite.chave = linha.chave
    LEFT JOIN dia_conta ON dia_conta.fuso_horario = linha.fuso_horario
    LEFT JOIN apurado
      ON apurado.chave_entidade = linha.chave_entidade AND apurado.moeda = linha.moeda AND apurado.chave = linha.chave
    LEFT JOIN investimento_apurado
      ON investimento_apurado.chave_entidade = linha.chave_entidade
     AND investimento_apurado.moeda = linha.moeda
     AND investimento_apurado.chave = linha.chave
    LEFT JOIN sem_linha
      ON sem_linha.chave_entidade = linha.chave_entidade
     AND sem_linha.moeda = linha.moeda
     AND sem_linha.chave = linha.chave
    LEFT JOIN entregue
      ON entregue.chave_entidade = linha.chave_entidade AND entregue.moeda = linha.moeda AND entregue.chave = linha.chave
  ),
  operando AS (
    -- Os operandos de cada entidade e período com valor: os da linha
    -- extraída ou, no período sem linha e sem entrega da regra 3, zero,
    -- porque a API omite o período sem entrega (R-20).
    SELECT
      situacao.nivel,
      situacao.entidade_id,
      situacao.inicio,
      situacao.fim,
      situacao.moeda,
      situacao.motivo,
      CASE WHEN situacao.motivo IS NULL THEN coalesce(situacao.fim_extraido, situacao.fim) END AS fim_apurado,
      CASE WHEN situacao.fim_extraido IS NULL THEN 0 ELSE situacao.alcance END AS alcance,
      CASE WHEN situacao.fim_extraido IS NULL THEN 0 ELSE situacao.impressoes END AS impressoes,
      CASE WHEN situacao.fim_extraido IS NULL THEN 0 ELSE situacao.investimento END AS investimento
    FROM situacao
  ),
  metrica_alcance AS (
    -- As métricas que dependem do alcance, pelo catálogo, com o campo de
    -- cada operando.
    SELECT
      metrica.codigo,
      metrica.tipo,
      metrica.campo_base,
      numerador.campo_base AS campo_numerador,
      denominador.campo_base AS campo_denominador,
      metrica.fator
    FROM normalizado.metrica AS metrica
    LEFT JOIN normalizado.metrica AS numerador ON numerador.codigo = metrica.numerador
    LEFT JOIN normalizado.metrica AS denominador ON denominador.codigo = metrica.denominador
    WHERE (metrica.tipo = 'base' AND NOT metrica.aditiva)
       OR (numerador.tipo = 'base' AND NOT numerador.aditiva)
       OR (denominador.tipo = 'base' AND NOT denominador.aditiva)
  )
  SELECT
    operando.nivel,
    operando.entidade_id,
    operando.inicio,
    operando.fim,
    operando.moeda,
    metrica.codigo,
    CASE
      WHEN operando.motivo IS NOT NULL THEN NULL
      WHEN metrica.tipo = 'base' THEN calculo.base
      ELSE calculo.numerador / nullif(calculo.denominador, 0) * metrica.fator
    END,
    operando.fim_apurado,
    operando.motivo
  FROM operando
  CROSS JOIN metrica_alcance AS metrica
  -- Um operando de campo novo precisa entrar nesta lista. Sem ele, a métrica
  -- sairia nula, e o alcance_frequencia_test.sql falha.
  CROSS JOIN LATERAL (
    SELECT
      max(campo.valor) FILTER (WHERE campo.nome = metrica.campo_base) AS base,
      max(campo.valor) FILTER (WHERE campo.nome = metrica.campo_numerador) AS numerador,
      max(campo.valor) FILTER (WHERE campo.nome = metrica.campo_denominador) AS denominador
    FROM (
      VALUES
        ('alcance', operando.alcance::numeric),
        ('impressoes', operando.impressoes::numeric),
        ('investimento', operando.investimento)
    ) AS campo (nome, valor)
  ) AS calculo;
END
$$;

REVOKE ALL ON FUNCTION normalizado.agregar_alcance(uuid, text, uuid, date, date, text) FROM PUBLIC;

-- A porta do painel. Parâmetro fora do domínio levanta 22023; credencial
-- inválida, revogada ou de outra empresa devolve zero linhas, sem erro,
-- para que a rota responda 404 sem revelar se a empresa existe (RF-46). O
-- operador lê qualquer empresa (ADR-0004).
CREATE FUNCTION analitico.obter_alcance(
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
  valor numeric,
  fim_apurado date,
  motivo text
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
  FROM normalizado.agregar_alcance(p_empresa_id, p_nivel, p_entidade_id, p_inicio, p_fim, p_granularidade);
END
$$;

REVOKE ALL ON FUNCTION analitico.obter_alcance(text, uuid, text, uuid, date, date, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analitico.obter_alcance(text, uuid, text, uuid, date, date, text) TO painel_leitor;
