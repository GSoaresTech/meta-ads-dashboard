import { render, screen, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { SerieTemporal } from "@/components/SerieTemporal";
import type { Metrica, PontoSerie } from "@/lib/resumo-desempenho";

// O Recharts mede o contêiner, que no jsdom não tem tamanho. O gráfico é
// conferido no navegador; aqui vale o que a tela mostra em volta dele.
vi.mock("@/components/GraficoSerie", () => ({
  GraficoSerie: () => <div data-testid="grafico" />,
}));

const INVESTIMENTO: Metrica = {
  codigo: "investimento",
  rotulo: "Investimento",
  explicacao: "Quanto foi gasto em anúncios no período.",
  unidade: "moeda",
  sentidoMelhora: "indiferente",
};

const PONTOS: PontoSerie[] = [
  { inicio: "2026-10-26", fim: "2026-11-01", valor: 70 },
  { inicio: "2026-11-02", fim: "2026-11-05", valor: null },
];

function lerLinhas(): string[][] {
  const [, ...linhas] = screen.getAllByRole("row", { hidden: true });
  return linhas.map((linha) =>
    within(linha)
      .getAllByRole("cell", { hidden: true })
      .map((celula) => celula.textContent ?? ""),
  );
}

test("RF-25: a tabela de dados tem um ponto por período, com o valor na unidade do catálogo", () => {
  render(
    <SerieTemporal
      metrica={INVESTIMENTO}
      moeda="BRL"
      granularidade="semana"
      pontos={PONTOS}
    />,
  );

  expect(
    screen.getByText("Investimento", { selector: "figcaption" }),
  ).toBeDefined();
  expect(screen.getByTestId("grafico")).toBeDefined();
  expect(lerLinhas()).toEqual([
    ["26/10/2026 a 01/11/2026", "R$ 70,00"],
    ["02/11/2026 a 05/11/2026", "—"],
  ]);
});

test("RF-30: a série tem a ajuda com a explicação do catálogo, fora da legenda", () => {
  render(
    <SerieTemporal
      metrica={INVESTIMENTO}
      moeda="BRL"
      granularidade="semana"
      pontos={PONTOS}
    />,
  );

  const legenda = screen.getByText("Investimento", { selector: "figcaption" });
  // O outro details da figura é o "Ver os dados", com a tabela.
  const ajuda = [
    ...(legenda.parentElement?.querySelectorAll("details") ?? []),
  ].find((elemento) => elemento.querySelector("table") === null);
  expect(ajuda?.querySelector("summary")?.textContent).toBe(
    "O que é isso? (Investimento)",
  );
  expect(ajuda?.querySelector("p")?.textContent).toBe(INVESTIMENTO.explicacao);
});

test("com um ponto só, não há linha para desenhar, e a tabela continua", () => {
  render(
    <SerieTemporal
      metrica={INVESTIMENTO}
      moeda="BRL"
      granularidade="ano"
      pontos={PONTOS.slice(0, 1)}
    />,
  );

  expect(screen.queryByTestId("grafico")).toBeNull();
  expect(lerLinhas()).toHaveLength(1);
});
