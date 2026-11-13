import { render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { DestaqueCampanha } from "@/components/DestaqueCampanha";
import { formatarMoeda } from "@/lib/formatacao";
import type { Metrica } from "@/lib/resumo-desempenho";
import type { DestaqueCampanha as Destaque } from "@/lib/visao-campanha";

vi.mock("@/components/GraficoSerie", () => ({
  GraficoSerie: () => <div data-testid="grafico" />,
}));

const COMPRAS: Metrica = {
  codigo: "compras",
  rotulo: "Compras",
  explicacao: "Quantas compras foram registradas e atribuídas aos anúncios.",
  unidade: "quantidade",
  sentidoMelhora: "alta",
};

const CUSTO_COMPRA: Metrica = {
  codigo: "custo_compra",
  rotulo: "Custo por compra",
  explicacao: "Quanto custou, em média, cada compra.",
  unidade: "moeda",
  sentidoMelhora: "queda",
};

const SERIE = [
  { inicio: "2026-09-01", fim: "2026-09-15", valor: 1 },
  { inicio: "2026-09-16", fim: "2026-09-30", valor: 3 },
];

const VENDAS: Destaque = {
  objetivo: "Vendas",
  status: "Ativa",
  moeda: "BRL",
  metricas: [
    { metrica: COMPRAS, total: 4, anterior: 2, serie: SERIE },
    { metrica: CUSTO_COMPRA, total: 25, anterior: 50, serie: SERIE },
  ],
};

function acharDestaque(): HTMLElement {
  return screen.getByRole("region", { name: "Resultado principal" });
}

test("RF-31: o resultado principal e o KPI aparecem em destaque, nessa ordem, na moeda da campanha", () => {
  render(<DestaqueCampanha destaque={VENDAS} granularidade="dia" />);

  const cartoes = within(acharDestaque()).getAllByRole("article");

  expect(
    cartoes.map((cartao) => cartao.querySelector("h3")?.textContent),
  ).toEqual(["Compras", "Custo por compra"]);
  expect(cartoes[0].textContent).toContain("4");
  expect(cartoes[1].textContent).toContain(formatarMoeda(25, "BRL"));
  expect(cartoes[1].textContent).toContain(CUSTO_COMPRA.explicacao);
});

test("RF-27: o resultado e o KPI mostram a variação, e a queda do custo é melhora", () => {
  render(<DestaqueCampanha destaque={VENDAS} granularidade="dia" />);

  const cartoes = within(acharDestaque()).getAllByRole("article");

  expect(cartoes[0].textContent).toContain("+100% · melhora");
  expect(cartoes[1].textContent).toContain("-50% · melhora");
});

test("o destaque diz o objetivo e o status da campanha, como chegam do banco", () => {
  render(<DestaqueCampanha destaque={VENDAS} granularidade="dia" />);

  const termos = within(acharDestaque()).getAllByRole("term");
  const definicoes = within(acharDestaque()).getAllByRole("definition");

  expect(termos.map((termo) => termo.textContent)).toEqual([
    "Objetivo",
    "Status",
  ]);
  expect(definicoes.map((definicao) => definicao.textContent)).toEqual([
    "Vendas",
    "Ativa",
  ]);
});

test("cada métrica em destaque tem a própria série", () => {
  render(<DestaqueCampanha destaque={VENDAS} granularidade="semana" />);

  const legendas = within(acharDestaque())
    .getAllByRole("figure")
    .map((figura) => figura.querySelector("figcaption")?.textContent);

  expect(legendas).toEqual(["Compras", "Custo por compra"]);
});

test("a métrica sem valor no desempenho tem cartão, mas não tem série (ADR-0013)", () => {
  render(
    <DestaqueCampanha
      destaque={{
        ...VENDAS,
        metricas: [
          { metrica: COMPRAS, total: undefined, anterior: 2, serie: [] },
        ],
      }}
      granularidade="dia"
    />,
  );

  expect(
    within(acharDestaque()).getByRole("article", { name: "Compras" })
      .textContent,
  ).toContain("Não disponível");
  expect(within(acharDestaque()).queryByRole("figure")).toBeNull();
});

test("sem resultado no catálogo, o destaque diz isso em vez de mostrar o número de outra métrica (§7.2)", () => {
  render(
    <DestaqueCampanha
      destaque={{ ...VENDAS, objetivo: "Não classificado", metricas: [] }}
      granularidade="dia"
    />,
  );

  expect(within(acharDestaque()).queryByRole("article")).toBeNull();
  expect(acharDestaque().textContent).toContain(
    "O objetivo desta campanha não tem resultado principal definido.",
  );
  expect(acharDestaque().textContent).toContain("Não classificado");
});
