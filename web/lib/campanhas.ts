import type { EntidadeFilha } from "@/lib/navegacao";
import type {
  LinhaDesempenho,
  LinhaResultado,
  Metrica,
  MetricaResumida,
} from "@/lib/resumo-desempenho";

// A lista de campanhas da visão da conta, montada a partir das leituras de
// analitico (REQUIREMENTS §3.1). O objetivo e o status já chegam em rótulo de
// negócio, e o valor da API nunca sai do banco (RF-37; ADR-0007).

// Os códigos são nulos na campanha sem resultado no catálogo (§7.2).
export interface LinhaCampanha extends EntidadeFilha {
  objetivo: string;
  status: string;
  metricaResultado: string | null;
  metricaKpi: string | null;
}

export interface LinhaDesempenhoCampanha extends Pick<
  LinhaDesempenho,
  "moeda" | "metrica" | "valor"
> {
  entidadeId: string | null;
}

export interface MetricaMedida {
  metrica: Metrica;
  valor: MetricaResumida["total"];
}

export interface CampanhaListada extends EntidadeFilha {
  objetivo: string;
  status: string;
  moeda: string;
  resultado: MetricaMedida | null;
  kpi: MetricaMedida | null;
}

function medirMetrica(
  codigo: string | null,
  valores: LinhaDesempenhoCampanha[],
  catalogo: Metrica[],
): MetricaMedida | null {
  const metrica = catalogo.find((item) => item.codigo === codigo);
  return metrica === undefined
    ? null
    : {
        metrica,
        valor: valores.find((linha) => linha.metrica === codigo)?.valor,
      };
}

// A entrega é a do desempenho: a filha aparece só com dados no período, e sem
// linha a campanha fica de fora (RF-23; ADR-0009 §4). A moeda vem da mesma
// linha, porque a campanha sem entrega não tem valor a formatar.
export function montarCampanhas(
  campanhas: LinhaCampanha[],
  desempenho: LinhaDesempenhoCampanha[],
  catalogo: Metrica[],
): CampanhaListada[] {
  return campanhas.flatMap(({ metricaResultado, metricaKpi, ...campanha }) => {
    const valores = desempenho.filter(
      ({ entidadeId }) => entidadeId === campanha.entidadeId,
    );
    const moeda = valores.at(0)?.moeda;
    if (moeda === undefined) {
      return [];
    }
    return [
      {
        ...campanha,
        moeda,
        resultado: medirMetrica(metricaResultado, valores, catalogo),
        kpi: medirMetrica(metricaKpi, valores, catalogo),
      },
    ];
  });
}

// Os tipos de resultado da conta são os das campanhas com entrega nela, a
// regra do Geral restrita à conta (ADR-0013). A repetição não importa: quem
// lê escolhe as métricas pelo conjunto dos códigos.
export function listarTiposResultado(
  campanhas: CampanhaListada[],
): LinhaResultado[] {
  return campanhas.flatMap(({ moeda, resultado }) =>
    resultado === null ? [] : [{ moeda, metrica: resultado.metrica.codigo }],
  );
}
