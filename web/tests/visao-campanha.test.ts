import { describe, expect, test } from "vitest";

import type { LinhaDesempenho, Metrica } from "@/lib/resumo-desempenho";
import {
  listarMetricasCampanha,
  montarVisaoCampanha,
  type LeituraCampanha,
} from "@/lib/visao-campanha";

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

// Em ordem de rótulo, como a listar_metricas devolve, que não é a ordem do
// apoio no catálogo.
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

const NAO_CLASSIFICADA: LeituraCampanha = {
  objetivo: "Não classificado",
  status: "Pausada",
  metricaResultado: null,
  metricaKpi: null,
  metricasApoio: ["investimento", "impressoes", "cliques_link"],
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

function lerCodigos(metricas: { metrica: Metrica }[]): string[] {
  return metricas.map(({ metrica }) => metrica.codigo);
}

describe("listarMetricasCampanha", () => {
  test("o investimento, o resultado, o KPI e o apoio, sem repetição", () => {
    expect(listarMetricasCampanha(VENDAS)).toEqual([
      "investimento",
      "compras",
      "custo_compra",
      "valor_compras",
      "roas",
      "cliques_link",
    ]);
    expect(listarMetricasCampanha(NAO_CLASSIFICADA)).toEqual([
      "investimento",
      "impressoes",
      "cliques_link",
    ]);
  });
});

describe("montarVisaoCampanha", () => {
  test("RF-31: o destaque é o resultado principal e o KPI resolvidos, com o total e a série", () => {
    const { destaque } = montarVisaoCampanha({
      catalogo: CATALOGO,
      campanha: VENDAS,
      totais: TOTAIS,
      serie: SERIE,
      anteriores: [],
    });

    expect(destaque).toMatchObject({
      objetivo: "Vendas",
      status: "Ativa",
      moeda: "BRL",
    });
    expect(
      destaque?.metricas.map(({ metrica, total }) => [metrica, total]),
    ).toEqual([
      [criarMetrica("compras"), 4],
      [criarMetrica("custo_compra", "moeda"), 25],
    ]);
    expect(destaque?.metricas[0].serie).toEqual([
      { inicio: "2026-09-01", fim: "2026-09-15", valor: 1 },
      { inicio: "2026-09-16", fim: "2026-09-30", valor: 3 },
    ]);
  });

  test("RF-27: o destaque e o apoio levam o total do período anterior de cada métrica", () => {
    const { destaque, resumos } = montarVisaoCampanha({
      catalogo: CATALOGO,
      campanha: VENDAS,
      totais: TOTAIS,
      serie: SERIE,
      anteriores: [
        criarLinha("investimento", 80, "2026-08-01", "2026-08-31"),
        criarLinha("compras", 2, "2026-08-01", "2026-08-31"),
        criarLinha("custo_compra", 40, "2026-08-01", "2026-08-31"),
      ],
    });

    expect(destaque?.metricas.map(({ anterior }) => anterior)).toEqual([2, 40]);
    expect(
      resumos[0].metricas.map(({ metrica, anterior }) => [
        metrica.codigo,
        anterior,
      ]),
    ).toEqual([
      ["investimento", 80],
      ["valor_compras", undefined],
      ["roas", undefined],
      ["cliques_link", undefined],
    ]);
  });

  test("o apoio começa pelo investimento e segue a ordem da regra, e não a do rótulo", () => {
    const { resumos } = montarVisaoCampanha({
      catalogo: CATALOGO,
      campanha: VENDAS,
      totais: TOTAIS,
      serie: SERIE,
      anteriores: [],
    });

    expect(resumos).toHaveLength(1);
    expect(resumos[0].moeda).toBe("BRL");
    expect(lerCodigos(resumos[0].metricas)).toEqual([
      "investimento",
      "valor_compras",
      "roas",
      "cliques_link",
    ]);
    expect(resumos[0].metricas[0].total).toBe(100);
  });

  test("a métrica do destaque não se repete no apoio", () => {
    const sobrescrita: LeituraCampanha = {
      ...VENDAS,
      metricaResultado: "cliques_link",
      metricaKpi: "investimento",
    };

    const { destaque, resumos } = montarVisaoCampanha({
      catalogo: CATALOGO,
      campanha: sobrescrita,
      totais: TOTAIS,
      serie: SERIE,
      anteriores: [],
    });

    expect(lerCodigos(destaque?.metricas ?? [])).toEqual([
      "cliques_link",
      "investimento",
    ]);
    expect(lerCodigos(resumos[0].metricas)).toEqual(["valor_compras", "roas"]);
  });

  test("a campanha sem resultado no catálogo não tem destaque de métrica, e o investimento do apoio aparece uma vez (§7.2)", () => {
    const { destaque, resumos } = montarVisaoCampanha({
      catalogo: CATALOGO,
      campanha: NAO_CLASSIFICADA,
      totais: TOTAIS,
      serie: SERIE,
      anteriores: [],
    });

    expect(destaque).toEqual({
      objetivo: "Não classificado",
      status: "Pausada",
      moeda: "BRL",
      metricas: [],
    });
    expect(lerCodigos(resumos[0].metricas)).toEqual([
      "investimento",
      "impressoes",
      "cliques_link",
    ]);
  });

  test("a métrica que a leitura de desempenho não traz fica sem total e sem série (ADR-0013)", () => {
    const reconhecimento: LeituraCampanha = {
      ...VENDAS,
      metricaResultado: "alcance",
    };

    const { destaque } = montarVisaoCampanha({
      catalogo: CATALOGO,
      campanha: reconhecimento,
      totais: TOTAIS,
      serie: SERIE,
      anteriores: [],
    });

    expect(destaque?.metricas[0]).toEqual({
      metrica: criarMetrica("alcance"),
      total: undefined,
      anterior: undefined,
      serie: [],
    });
  });

  test("a razão sem denominador continua nula, diferente da métrica ausente", () => {
    const { destaque } = montarVisaoCampanha({
      catalogo: CATALOGO,
      campanha: VENDAS,
      totais: [criarLinha("investimento", 0), criarLinha("custo_compra", null)],
      serie: [],
      anteriores: [],
    });

    expect(destaque?.metricas.map(({ total }) => total)).toEqual([
      undefined,
      null,
    ]);
  });

  test("sem dados no intervalo, não há destaque nem resumo", () => {
    expect(
      montarVisaoCampanha({
        catalogo: CATALOGO,
        campanha: VENDAS,
        totais: [],
        serie: [],
        anteriores: [],
      }),
    ).toEqual({ destaque: null, resumos: [] });
  });
});
