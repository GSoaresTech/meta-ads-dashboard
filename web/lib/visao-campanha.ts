import {
  METRICA_INVESTIMENTO,
  resumirMetrica,
  type LeiturasResumo,
  type MetricaResumida,
  type ResumoMoeda,
} from "@/lib/resumo-desempenho";

// A visão da campanha, montada a partir das leituras de analitico
// (REQUIREMENTS §3.1). Quais métricas a campanha destaca e quais a apoiam vem
// da resolução do catálogo, já com a sobrescrita, e por isso nada aqui
// depende do objetivo (RF-31; ADR-0007).

// Tudo pelo código do catálogo. O resultado e o KPI são nulos na campanha sem
// resultado principal (§7.2).
export interface LeituraCampanha {
  objetivo: string;
  status: string;
  metricaResultado: string | null;
  metricaKpi: string | null;
  // Na ordem de exibição da regra.
  metricasApoio: string[];
}

export interface DestaqueCampanha {
  objetivo: string;
  status: string;
  moeda: string;
  // O resultado principal e o KPI, nessa ordem. Vazia sem resultado no
  // catálogo.
  metricas: MetricaResumida[];
}

export interface VisaoCampanha {
  // Nulo sem dados no intervalo, em que não há moeda nem valor a destacar.
  destaque: DestaqueCampanha | null;
  // O investimento e as métricas de apoio, como os totais das outras visões.
  resumos: ResumoMoeda[];
}

export interface LeiturasCampanha extends Pick<
  LeiturasResumo,
  "catalogo" | "totais" | "serie" | "anteriores"
> {
  campanha: LeituraCampanha;
}

function listarDestaque({
  metricaResultado,
  metricaKpi,
}: LeituraCampanha): string[] {
  return [metricaResultado, metricaKpi].filter((codigo) => codigo !== null);
}

// O investimento vem sempre, mesmo que a regra não o tenha no apoio, e uma
// métrica do destaque não se repete abaixo dele.
function listarApoio(campanha: LeituraCampanha): string[] {
  const destaque = new Set(listarDestaque(campanha));
  return [...new Set([METRICA_INVESTIMENTO, ...campanha.metricasApoio])].filter(
    (codigo) => !destaque.has(codigo),
  );
}

// As métricas que a tela da campanha lê da obter_desempenho.
export function listarMetricasCampanha(campanha: LeituraCampanha): string[] {
  return [
    ...new Set([
      METRICA_INVESTIMENTO,
      ...listarDestaque(campanha),
      ...campanha.metricasApoio,
    ]),
  ];
}

export function resumirCodigos(
  codigos: string[],
  moeda: string,
  leituras: LeiturasCampanha,
): MetricaResumida[] {
  return codigos.flatMap((codigo) => {
    const metrica = leituras.catalogo.find((item) => item.codigo === codigo);
    return metrica === undefined
      ? []
      : [resumirMetrica(metrica, moeda, leituras)];
  });
}

// A campanha é de uma conta e tem uma moeda só, a da primeira linha do
// desempenho. Sem nenhuma linha, ela não teve entrega no intervalo.
export function montarVisaoCampanha(leituras: LeiturasCampanha): VisaoCampanha {
  const moeda = leituras.totais.at(0)?.moeda;
  if (moeda === undefined) {
    return { destaque: null, resumos: [] };
  }

  const { campanha } = leituras;
  return {
    destaque: {
      objetivo: campanha.objetivo,
      status: campanha.status,
      moeda,
      metricas: resumirCodigos(listarDestaque(campanha), moeda, leituras),
    },
    resumos: [
      {
        moeda,
        metricas: resumirCodigos(listarApoio(campanha), moeda, leituras),
      },
    ],
  };
}
