import { render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { ResumoDesempenho } from "@/components/ResumoDesempenho";
import type { Metrica, ResumoMoeda } from "@/lib/resumo-desempenho";

vi.mock("@/components/GraficoSerie", () => ({
  GraficoSerie: () => <div data-testid="grafico" />,
}));

const INVESTIMENTO: Metrica = {
  codigo: "investimento",
  rotulo: "Investimento",
  explicacao: "Quanto foi gasto em anúncios no período.",
  unidade: "moeda",
};

const ALCANCE: Metrica = {
  codigo: "alcance",
  rotulo: "Pessoas alcançadas",
  explicacao: "Quantas pessoas diferentes viram os anúncios.",
  unidade: "quantidade",
};

const SERIE = [
  { inicio: "2026-10-01", fim: "2026-10-01", valor: 10 },
  { inicio: "2026-10-02", fim: "2026-10-02", valor: 20 },
];

const RESUMOS: ResumoMoeda[] = [
  {
    moeda: "BRL",
    metricas: [
      { metrica: INVESTIMENTO, total: 30, serie: SERIE },
      { metrica: ALCANCE, total: undefined, serie: [] },
    ],
  },
  {
    moeda: "USD",
    metricas: [{ metrica: INVESTIMENTO, total: 20, serie: SERIE }],
  },
];

test("RF-34: cada moeda tem a própria seção com o próprio total", () => {
  render(<ResumoDesempenho resumos={RESUMOS} granularidade="dia" />);

  const real = screen.getByRole("region", { name: "Real brasileiro (BRL)" });
  const dolar = screen.getByRole("region", { name: "Dólar americano (USD)" });

  expect(
    within(real).getByRole("article", { name: "Investimento" }).textContent,
  ).toContain("R$ 30,00");
  expect(
    within(dolar).getByRole("article", { name: "Investimento" }).textContent,
  ).toContain("US$ 20,00");
});

test("a métrica sem valor tem cartão, mas não tem série", () => {
  render(<ResumoDesempenho resumos={RESUMOS} granularidade="dia" />);

  const real = screen.getByRole("region", { name: "Real brasileiro (BRL)" });

  expect(
    within(real).getByRole("article", { name: "Pessoas alcançadas" }),
  ).toBeDefined();
  expect(
    within(real).queryByText("Pessoas alcançadas", { selector: "figcaption" }),
  ).toBeNull();
  expect(
    within(real).getByText("Investimento", { selector: "figcaption" }),
  ).toBeDefined();
});

test("sem dados no intervalo, a tela diz isso em vez de mostrar zeros", () => {
  render(<ResumoDesempenho resumos={[]} granularidade="dia" />);

  expect(screen.getByText("Nenhum dado no período.")).toBeDefined();
  expect(screen.queryByRole("article")).toBeNull();
});
