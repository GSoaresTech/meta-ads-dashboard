import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { CartaoMetrica } from "@/components/CartaoMetrica";
import type { Metrica } from "@/lib/resumo-desempenho";

const INVESTIMENTO: Metrica = {
  codigo: "investimento",
  rotulo: "Investimento",
  explicacao: "Quanto foi gasto em anúncios no período.",
  unidade: "moeda",
};

const CADASTROS: Metrica = {
  codigo: "cadastros",
  rotulo: "Cadastros",
  explicacao: "Quantas pessoas deixaram seus dados.",
  unidade: "quantidade",
};

test("RF-30: mostra o rótulo do catálogo, com o valor na unidade dele", () => {
  render(<CartaoMetrica metrica={INVESTIMENTO} moeda="BRL" valor={1234.56} />);

  const cartao = screen.getByRole("article", { name: "Investimento" });
  expect(cartao.textContent).toContain("R$ 1.234,56");
});

test("RF-30: a explicação do catálogo fica na ajuda do cartão", () => {
  render(<CartaoMetrica metrica={INVESTIMENTO} moeda="BRL" valor={1234.56} />);

  const ajuda = screen.getByRole("article").querySelector("details");
  expect(ajuda?.querySelector("summary")?.textContent).toBe(
    "O que é isso? (Investimento)",
  );
  expect(ajuda?.querySelector("p")?.textContent).toBe(INVESTIMENTO.explicacao);
});

test("o zero aparece como valor", () => {
  render(<CartaoMetrica metrica={CADASTROS} moeda="BRL" valor={0} />);

  expect(screen.getByRole("article").textContent).toContain("0");
});

test("o valor nulo aparece como travessão (REQUIREMENTS §7.1)", () => {
  render(<CartaoMetrica metrica={CADASTROS} moeda="BRL" valor={null} />);

  expect(screen.getByRole("article").textContent).toContain("—");
});

test("a métrica que a leitura não traz aparece como não disponível (REQUIREMENTS §3.3)", () => {
  render(<CartaoMetrica metrica={CADASTROS} moeda="BRL" valor={undefined} />);

  expect(screen.getByRole("article").textContent).toContain("Não disponível");
});
