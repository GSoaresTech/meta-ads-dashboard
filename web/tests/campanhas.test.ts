import { describe, expect, test } from "vitest";

import {
  listarTiposResultado,
  montarCampanhas,
  type LinhaCampanha,
  type LinhaDesempenhoCampanha,
} from "@/lib/campanhas";
import type { Metrica } from "@/lib/resumo-desempenho";

const CATALOGO: Metrica[] = [
  {
    codigo: "compras",
    rotulo: "Compras",
    explicacao: "Explicação das compras.",
    unidade: "quantidade",
    sentidoMelhora: "alta",
  },
  {
    codigo: "custo_compra",
    rotulo: "Custo por compra",
    explicacao: "Explicação do custo por compra.",
    unidade: "moeda",
    sentidoMelhora: "queda",
  },
  {
    codigo: "alcance",
    rotulo: "Pessoas alcançadas",
    explicacao: "Explicação do alcance.",
    unidade: "quantidade",
    sentidoMelhora: "alta",
  },
  {
    codigo: "custo_mil_alcance",
    rotulo: "Custo por mil pessoas alcançadas",
    explicacao: "Explicação do custo por mil.",
    unidade: "moeda",
    sentidoMelhora: "queda",
  },
];

function montarCampanha(
  entidadeId: string,
  metricaResultado: string | null,
  metricaKpi: string | null,
): LinhaCampanha {
  return {
    nivel: "campanha",
    entidadeId,
    nome: `Campanha ${entidadeId}`,
    objetivo: "Vendas",
    status: "Ativa",
    metricaResultado,
    metricaKpi,
  };
}

function montarValor(
  entidadeId: string,
  metrica: string,
  valor: number | null,
): LinhaDesempenhoCampanha {
  return { entidadeId, moeda: "BRL", metrica, valor };
}

describe("montarCampanhas", () => {
  test("cada campanha traz o resultado e o KPI do catálogo, com o valor do período", () => {
    const [campanha] = montarCampanhas(
      [montarCampanha("a", "compras", "custo_compra")],
      [montarValor("a", "compras", 6), montarValor("a", "custo_compra", 5)],
      CATALOGO,
    );

    expect(campanha).toMatchObject({
      entidadeId: "a",
      nome: "Campanha a",
      objetivo: "Vendas",
      status: "Ativa",
      moeda: "BRL",
    });
    expect(campanha.resultado?.metrica.rotulo).toBe("Compras");
    expect(campanha.resultado?.valor).toBe(6);
    expect(campanha.kpi?.metrica.rotulo).toBe("Custo por compra");
    expect(campanha.kpi?.valor).toBe(5);
  });

  test("a campanha sem entrega no período fica de fora, e a ordem é a da listagem", () => {
    const campanhas = montarCampanhas(
      [
        montarCampanha("b", "compras", "custo_compra"),
        montarCampanha("sem-entrega", "compras", "custo_compra"),
        montarCampanha("a", "compras", "custo_compra"),
      ],
      [montarValor("a", "compras", 1), montarValor("b", "compras", 2)],
      CATALOGO,
    );

    expect(campanhas.map(({ entidadeId }) => entidadeId)).toEqual(["b", "a"]);
  });

  test("a razão sem denominador fica nula, diferente da métrica que a leitura não traz (§7.1; ADR-0013)", () => {
    const [semCompras, reconhecimento] = montarCampanhas(
      [
        montarCampanha("a", "compras", "custo_compra"),
        montarCampanha("b", "alcance", "custo_mil_alcance"),
      ],
      [
        montarValor("a", "compras", 0),
        montarValor("a", "custo_compra", null),
        montarValor("b", "investimento", 10),
      ],
      CATALOGO,
    );

    expect(semCompras.kpi?.valor).toBeNull();
    expect(reconhecimento.resultado?.valor).toBeUndefined();
    expect(reconhecimento.kpi?.valor).toBeUndefined();
  });

  test("a campanha 'Não classificado' não tem resultado nem KPI", () => {
    const [campanha] = montarCampanhas(
      [montarCampanha("a", null, null)],
      [montarValor("a", "investimento", 10)],
      CATALOGO,
    );

    expect(campanha.resultado).toBeNull();
    expect(campanha.kpi).toBeNull();
  });
});

describe("listarTiposResultado", () => {
  test("os tipos são os resultados das campanhas listadas, na moeda delas, sem as que não têm resultado", () => {
    const campanhas = montarCampanhas(
      [
        montarCampanha("a", "compras", "custo_compra"),
        montarCampanha("b", "compras", "custo_compra"),
        montarCampanha("c", "alcance", "custo_mil_alcance"),
        montarCampanha("d", null, null),
        montarCampanha("sem-entrega", "custo_compra", null),
      ],
      [
        montarValor("a", "investimento", 1),
        montarValor("b", "investimento", 1),
        montarValor("c", "investimento", 1),
        montarValor("d", "investimento", 1),
      ],
      CATALOGO,
    );

    expect(listarTiposResultado(campanhas)).toEqual([
      { moeda: "BRL", metrica: "compras" },
      { moeda: "BRL", metrica: "compras" },
      { moeda: "BRL", metrica: "alcance" },
    ]);
  });
});
