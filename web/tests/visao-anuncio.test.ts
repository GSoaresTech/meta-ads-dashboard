import { describe, expect, test } from "vitest";

import type { LinhaDesempenho, Metrica } from "@/lib/resumo-desempenho";
import { montarVisaoAnuncio } from "@/lib/visao-anuncio";
import type { LeituraCampanha } from "@/lib/visao-campanha";

function criarMetrica(
  codigo: string,
  unidade: Metrica["unidade"] = "quantidade",
): Metrica {
  return {
    codigo,
    rotulo: `Rótulo ${codigo}`,
    explicacao: `Explicação ${codigo}`,
    unidade,
    sentidoMelhora: "alta",
  };
}

// Em ordem de rótulo, como a listar_metricas devolve, que não é a ordem de
// exibição do anúncio.
const CATALOGO = [
  criarMetrica("alcance"),
  criarMetrica("cliques_link"),
  criarMetrica("compras"),
  criarMetrica("custo_compra", "moeda"),
  criarMetrica("impressoes"),
  criarMetrica("investimento", "moeda"),
  criarMetrica("roas", "razao"),
  criarMetrica("valor_compras", "moeda"),
];

const VENDAS: LeituraCampanha = {
  objetivo: "Vendas",
  status: "Ativa",
  metricaResultado: "compras",
  metricaKpi: "custo_compra",
  metricasApoio: ["valor_compras", "roas", "cliques_link"],
};

function criarLinha(
  metrica: string,
  valor: number | null,
  inicio = "2026-09-01",
  fim = "2026-09-30",
): LinhaDesempenho {
  return { inicio, fim, moeda: "BRL", metrica, valor };
}

const TOTAIS = [
  criarLinha("investimento", 100),
  criarLinha("compras", 4),
  criarLinha("custo_compra", 25),
  criarLinha("valor_compras", 300),
  criarLinha("roas", 3),
  criarLinha("cliques_link", 40),
  criarLinha("impressoes", 1000),
];

const SERIE = [
  criarLinha("compras", 1, "2026-09-01", "2026-09-15"),
  criarLinha("investimento", 40, "2026-09-01", "2026-09-15"),
  criarLinha("compras", 3, "2026-09-16", "2026-09-30"),
  criarLinha("investimento", 60, "2026-09-16", "2026-09-30"),
];

function lerCodigos(
  resumos: ReturnType<typeof montarVisaoAnuncio>,
): string[][] {
  return resumos.map(({ metricas }) =>
    metricas.map(({ metrica }) => metrica.codigo),
  );
}

describe("montarVisaoAnuncio", () => {
  test("o investimento, o resultado, o KPI e o apoio da campanha, com o total e a série de cada um", () => {
    const resumos = montarVisaoAnuncio({
      catalogo: CATALOGO,
      campanha: VENDAS,
      totais: TOTAIS,
      serie: SERIE,
      anteriores: [],
    });

    expect(resumos.map(({ moeda }) => moeda)).toEqual(["BRL"]);
    expect(
      resumos[0].metricas.map(({ metrica, total }) => [metrica.codigo, total]),
    ).toEqual([
      ["investimento", 100],
      ["compras", 4],
      ["custo_compra", 25],
      ["valor_compras", 300],
      ["roas", 3],
      ["cliques_link", 40],
    ]);
    expect(resumos[0].metricas[1].serie).toEqual([
      { inicio: "2026-09-01", fim: "2026-09-15", valor: 1 },
      { inicio: "2026-09-16", fim: "2026-09-30", valor: 3 },
    ]);
  });

  test("a métrica que a sobrescrita leva ao resultado e a regra traz no apoio aparece uma vez", () => {
    const resumos = montarVisaoAnuncio({
      catalogo: CATALOGO,
      campanha: {
        ...VENDAS,
        metricaResultado: "cliques_link",
        metricaKpi: null,
      },
      totais: TOTAIS,
      serie: SERIE,
      anteriores: [],
    });

    expect(lerCodigos(resumos)).toEqual([
      ["investimento", "cliques_link", "valor_compras", "roas"],
    ]);
  });

  test("sem resultado no catálogo, o anúncio mostra o investimento uma vez e o apoio, sem outra métrica no lugar do resultado (§7.2)", () => {
    const resumos = montarVisaoAnuncio({
      catalogo: CATALOGO,
      campanha: {
        objetivo: "Não classificado",
        status: "Pausada",
        metricaResultado: null,
        metricaKpi: null,
        metricasApoio: ["investimento", "impressoes", "cliques_link"],
      },
      totais: TOTAIS,
      serie: SERIE,
      anteriores: [],
    });

    expect(lerCodigos(resumos)).toEqual([
      ["investimento", "impressoes", "cliques_link"],
    ]);
  });

  test("a métrica que a leitura de desempenho não traz tem total indefinido e série vazia (ADR-0013)", () => {
    const resumos = montarVisaoAnuncio({
      catalogo: CATALOGO,
      campanha: { ...VENDAS, metricaResultado: "alcance", metricaKpi: null },
      totais: TOTAIS,
      serie: SERIE,
      anteriores: [],
    });

    expect(resumos[0].metricas[1]).toEqual({
      metrica: criarMetrica("alcance"),
      total: undefined,
      anterior: undefined,
      serie: [],
    });
  });

  test("sem nenhum dado no intervalo, não há resumo", () => {
    expect(
      montarVisaoAnuncio({
        catalogo: CATALOGO,
        campanha: VENDAS,
        totais: [],
        serie: [],
        anteriores: [],
      }),
    ).toEqual([]);
  });
});
