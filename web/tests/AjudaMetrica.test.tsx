import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { AjudaMetrica } from "@/components/AjudaMetrica";
import type { Metrica } from "@/lib/resumo-desempenho";

const INVESTIMENTO: Metrica = {
  codigo: "investimento",
  rotulo: "Investimento",
  explicacao: "Quanto foi gasto em anúncios no período.",
  unidade: "moeda",
  sentidoMelhora: "indiferente",
};

function lerControle(): HTMLElement {
  return screen.getByText("O que é isso?", {
    exact: false,
    selector: "summary",
  });
}

test("RF-30: a ajuda traz a explicação do catálogo", () => {
  render(<AjudaMetrica metrica={INVESTIMENTO} />);

  const ajuda = lerControle().parentElement;

  expect(ajuda?.querySelector("p")?.textContent).toBe(INVESTIMENTO.explicacao);
});

// O leitor de tela lê o texto oculto junto, e o nome não se repete entre as
// ajudas de uma mesma página.
test("o controle diz de qual métrica é a ajuda", () => {
  render(<AjudaMetrica metrica={INVESTIMENTO} />);

  expect(lerControle().textContent).toBe("O que é isso? (Investimento)");
});

// O summary é o controle nativo do details: o navegador o põe na ordem do
// teclado, abre com Enter ou espaço e informa ao leitor de tela se está aberto.
test("a ajuda começa fechada, recebe o foco e abre pelo controle", () => {
  render(<AjudaMetrica metrica={INVESTIMENTO} />);
  const controle = lerControle();
  const ajuda = controle.parentElement as HTMLDetailsElement;

  expect(ajuda.tagName).toBe("DETAILS");
  expect(ajuda.firstElementChild).toBe(controle);
  expect(ajuda.open).toBe(false);

  controle.focus();
  expect(document.activeElement).toBe(controle);

  fireEvent.click(controle);
  expect(ajuda.open).toBe(true);
});
