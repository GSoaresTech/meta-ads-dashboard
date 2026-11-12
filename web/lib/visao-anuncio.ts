import type { ResumoMoeda } from "@/lib/resumo-desempenho";
import {
  listarMetricasCampanha,
  resumirCodigos,
  type LeiturasCampanha,
} from "@/lib/visao-campanha";

// A visão do anúncio, montada a partir das leituras de analitico
// (REQUIREMENTS §3.1). As métricas são as da campanha dele, resolvidas pelo
// catálogo com a sobrescrita, num bloco só: o investimento, o resultado, o KPI
// e o apoio, nessa ordem (ADR-0019). Nada aqui depende do objetivo (ADR-0007).

// O anúncio é de uma conta e tem uma moeda só, a da primeira linha do
// desempenho. Sem nenhuma linha, ele não teve entrega no intervalo.
export function montarVisaoAnuncio(leituras: LeiturasCampanha): ResumoMoeda[] {
  const moeda = leituras.totais.at(0)?.moeda;
  if (moeda === undefined) {
    return [];
  }

  const codigos = listarMetricasCampanha(leituras.campanha);
  return [{ moeda, metricas: resumirCodigos(codigos, moeda, leituras) }];
}
