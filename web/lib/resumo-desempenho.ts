import type { UnidadeMetrica } from "@/lib/formatacao";

// O resumo da entidade em foco, montado a partir das leituras de analitico:
// um por moeda, porque valores de moedas diferentes nunca se somam (RF-34).

export const METRICA_INVESTIMENTO = "investimento";

export interface Metrica {
  codigo: string;
  rotulo: string;
  explicacao: string;
  unidade: UnidadeMetrica;
}

export interface LinhaResultado {
  moeda: string;
  metrica: string;
}

export interface LinhaDesempenho {
  inicio: string;
  fim: string;
  moeda: string;
  metrica: string;
  valor: number | null;
}

export type PontoSerie = Pick<LinhaDesempenho, "inicio" | "fim" | "valor">;

export interface MetricaResumida {
  metrica: Metrica;
  // Nulo é a razão sem denominador. Indefinido é a métrica que a leitura de
  // desempenho não traz, como o alcance (ADR-0013).
  total: number | null | undefined;
  serie: PontoSerie[];
}

export interface ResumoMoeda {
  moeda: string;
  metricas: MetricaResumida[];
}

export interface LeiturasResumo {
  // Na ordem de exibição, que é a da leitura do catálogo.
  catalogo: Metrica[];
  resultados: LinhaResultado[];
  // Uma linha por moeda e métrica, com o intervalo inteiro.
  totais: LinhaDesempenho[];
  // Em ordem de período.
  serie: LinhaDesempenho[];
}

function escolherMetricas(
  catalogo: Metrica[],
  resultados: LinhaResultado[],
  moeda: string,
): Metrica[] {
  const tipos = new Set(
    resultados
      .filter((resultado) => resultado.moeda === moeda)
      .map((resultado) => resultado.metrica),
  );

  return [
    ...catalogo.filter(({ codigo }) => codigo === METRICA_INVESTIMENTO),
    ...catalogo.filter(
      ({ codigo }) => codigo !== METRICA_INVESTIMENTO && tipos.has(codigo),
    ),
  ];
}

function resumirMetrica(
  metrica: Metrica,
  moeda: string,
  { totais, serie }: LeiturasResumo,
): MetricaResumida {
  const pertence = (linha: LinhaDesempenho) =>
    linha.moeda === moeda && linha.metrica === metrica.codigo;

  return {
    metrica,
    total: totais.find(pertence)?.valor,
    serie: serie
      .filter(pertence)
      .map(({ inicio, fim, valor }) => ({ inicio, fim, valor })),
  };
}

// As moedas são as que têm dados no intervalo: sem nenhum dado, não há resumo.
export function montarResumos(leituras: LeiturasResumo): ResumoMoeda[] {
  const moedas = [...new Set(leituras.totais.map(({ moeda }) => moeda))].sort();

  return moedas.map((moeda) => ({
    moeda,
    metricas: escolherMetricas(
      leituras.catalogo,
      leituras.resultados,
      moeda,
    ).map((metrica) => resumirMetrica(metrica, moeda, leituras)),
  }));
}
