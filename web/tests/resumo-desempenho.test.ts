import { describe, expect, test } from "vitest";

import {
  montarResumos,
  type LinhaDesempenho,
  type LinhaResultado,
  type Metrica,
} from "@/lib/resumo-desempenho";

const CATALOGO: Metrica[] = [
  {
    codigo: "cadastros",
    rotulo: "Cadastros",
    explicacao: "Explicação dos cadastros.",
    unidade: "quantidade",
    sentidoMelhora: "alta",
  },
  {
    codigo: "compras",
    rotulo: "Compras",
    explicacao: "Explicação das compras.",
    unidade: "quantidade",
    sentidoMelhora: "alta",
  },
  {
    codigo: "investimento",
    rotulo: "Investimento",
    explicacao: "Explicação do investimento.",
    unidade: "moeda",
    sentidoMelhora: "indiferente",
  },
  {
    codigo: "alcance",
    rotulo: "Pessoas alcançadas",
    explicacao: "Explicação do alcance.",
    unidade: "quantidade",
    sentidoMelhora: "alta",
  },
];

function montarLinha(
  moeda: string,
  metrica: string,
  valor: number | null,
  inicio = "2026-10-01",
): LinhaDesempenho {
  return { inicio, fim: inicio, moeda, metrica, valor };
}

const TOTAIS: LinhaDesempenho[] = [
  montarLinha("USD", "investimento", 20),
  montarLinha("USD", "compras", 1),
  montarLinha("USD", "cadastros", 5),
  montarLinha("BRL", "investimento", 30),
  montarLinha("BRL", "compras", 2),
  montarLinha("BRL", "cadastros", 7),
];

const SERIE: LinhaDesempenho[] = [
  montarLinha("BRL", "investimento", 10, "2026-10-01"),
  montarLinha("BRL", "investimento", 20, "2026-10-02"),
  montarLinha("USD", "investimento", 20, "2026-10-01"),
  montarLinha("BRL", "compras", 2, "2026-10-01"),
];

const RESULTADOS: LinhaResultado[] = [
  { moeda: "BRL", metrica: "compras" },
  { moeda: "USD", metrica: "cadastros" },
];

function montar(
  resultados: LinhaResultado[] = RESULTADOS,
  totais: LinhaDesempenho[] = TOTAIS,
  serie: LinhaDesempenho[] = SERIE,
  anteriores: LinhaDesempenho[] = [],
) {
  return montarResumos({
    catalogo: CATALOGO,
    resultados,
    totais,
    serie,
    anteriores,
  });
}

describe("montarResumos", () => {
  test("RF-34: cada moeda tem o próprio resumo, em ordem de código, sem total combinado", () => {
    const resumos = montar();

    expect(resumos.map((resumo) => resumo.moeda)).toEqual(["BRL", "USD"]);
    expect(resumos.map((resumo) => resumo.metricas[0].total)).toEqual([30, 20]);
  });

  test("o investimento vem primeiro, seguido só dos tipos de resultado da moeda", () => {
    const codigos = montar().map((resumo) =>
      resumo.metricas.map((item) => item.metrica.codigo),
    );

    expect(codigos).toEqual([
      ["investimento", "compras"],
      ["investimento", "cadastros"],
    ]);
  });

  test("os tipos seguem a ordem do catálogo, e não a da leitura", () => {
    const [resumo] = montar([
      { moeda: "BRL", metrica: "compras" },
      { moeda: "BRL", metrica: "cadastros" },
    ]);

    expect(resumo.metricas.map((item) => item.metrica.codigo)).toEqual([
      "investimento",
      "cadastros",
      "compras",
    ]);
  });

  test("a série de cada métrica leva só os pontos dela na moeda", () => {
    const [brl, usd] = montar();

    expect(brl.metricas[0].serie).toEqual([
      { inicio: "2026-10-01", fim: "2026-10-01", valor: 10 },
      { inicio: "2026-10-02", fim: "2026-10-02", valor: 20 },
    ]);
    expect(brl.metricas[1].serie).toEqual([
      { inicio: "2026-10-01", fim: "2026-10-01", valor: 2 },
    ]);
    expect(usd.metricas[0].serie).toEqual([
      { inicio: "2026-10-01", fim: "2026-10-01", valor: 20 },
    ]);
  });

  test("o tipo que a leitura de desempenho não traz fica sem total e sem série", () => {
    const [resumo] = montar([{ moeda: "BRL", metrica: "alcance" }]);

    expect(resumo.metricas[1]).toEqual({
      metrica: CATALOGO[3],
      total: undefined,
      anterior: undefined,
      serie: [],
    });
  });

  test("o total nulo continua nulo, diferente do total que não veio", () => {
    const [resumo] = montar(
      [{ moeda: "BRL", metrica: "compras" }],
      [
        montarLinha("BRL", "investimento", 30),
        montarLinha("BRL", "compras", null),
      ],
    );

    expect(resumo.metricas[1].total).toBeNull();
  });

  test("RF-27: cada métrica leva o total do período anterior na mesma moeda", () => {
    const [brl, usd] = montar(RESULTADOS, TOTAIS, SERIE, [
      montarLinha("BRL", "investimento", 25, "2026-09-01"),
      montarLinha("BRL", "compras", null, "2026-09-01"),
      montarLinha("USD", "investimento", 15, "2026-09-01"),
    ]);

    expect(brl.metricas.map(({ anterior }) => anterior)).toEqual([25, null]);
    expect(usd.metricas.map(({ anterior }) => anterior)).toEqual([
      15,
      undefined,
    ]);
  });

  test("a moeda sem dados no período anterior fica sem total anterior, e não sem resumo", () => {
    const resumos = montar(RESULTADOS, TOTAIS, SERIE, []);

    expect(resumos.map(({ moeda }) => moeda)).toEqual(["BRL", "USD"]);
    expect(
      resumos.flatMap(({ metricas }) =>
        metricas.map(({ anterior }) => anterior),
      ),
    ).toEqual([undefined, undefined, undefined, undefined]);
  });

  test("sem dados no intervalo, não há resumo", () => {
    expect(montar([], [], [])).toEqual([]);
  });
});
