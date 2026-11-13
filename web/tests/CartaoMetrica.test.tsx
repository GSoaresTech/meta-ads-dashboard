import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { CartaoMetrica } from "@/components/CartaoMetrica";
import type { Metrica } from "@/lib/resumo-desempenho";

const INVESTIMENTO: Metrica = {
  codigo: "investimento",
  rotulo: "Investimento",
  explicacao: "Quanto foi gasto em anúncios no período.",
  unidade: "moeda",
  sentidoMelhora: "indiferente",
};

const CUSTO_CADASTRO: Metrica = {
  codigo: "custo_cadastro",
  rotulo: "Custo por cadastro",
  explicacao: "Quanto custou, em média, cada cadastro.",
  unidade: "moeda",
  sentidoMelhora: "queda",
};

const CADASTROS: Metrica = {
  codigo: "cadastros",
  rotulo: "Cadastros",
  explicacao: "Quantas pessoas deixaram seus dados.",
  unidade: "quantidade",
  sentidoMelhora: "alta",
};

test("RF-30: mostra o rótulo do catálogo, com o valor na unidade dele", () => {
  render(
    <CartaoMetrica
      metrica={INVESTIMENTO}
      moeda="BRL"
      valor={1234.56}
      anterior={1000}
    />,
  );

  const cartao = screen.getByRole("article", { name: "Investimento" });
  expect(cartao.textContent).toContain("R$ 1.234,56");
});

test("RF-30: a explicação do catálogo fica na ajuda do cartão", () => {
  render(
    <CartaoMetrica
      metrica={INVESTIMENTO}
      moeda="BRL"
      valor={1234.56}
      anterior={1000}
    />,
  );

  const ajuda = screen.getByRole("article").querySelector("details");
  expect(ajuda?.querySelector("summary")?.textContent).toBe(
    "O que é isso? (Investimento)",
  );
  expect(ajuda?.querySelector("p")?.textContent).toBe(INVESTIMENTO.explicacao);
});

test("o zero aparece como valor", () => {
  render(
    <CartaoMetrica metrica={CADASTROS} moeda="BRL" valor={0} anterior={10} />,
  );

  expect(screen.getByRole("article").textContent).toContain("0");
});

test("o valor nulo aparece como travessão (REQUIREMENTS §7.1)", () => {
  render(
    <CartaoMetrica
      metrica={CADASTROS}
      moeda="BRL"
      valor={null}
      anterior={10}
    />,
  );

  expect(screen.getByRole("article").textContent).toContain("—");
});

test("a métrica que a leitura não traz aparece como não disponível (REQUIREMENTS §3.3)", () => {
  render(
    <CartaoMetrica
      metrica={CADASTROS}
      moeda="BRL"
      valor={undefined}
      anterior={10}
    />,
  );

  expect(screen.getByRole("article").textContent).toContain("Não disponível");
});

// O parágrafo da variação vem logo abaixo do valor.
function lerVariacao(): string {
  return screen.getByRole("article").querySelectorAll("p")[1].textContent;
}

test("RF-27: mostra a variação em relação ao período anterior, com a seta e a avaliação", () => {
  render(
    <CartaoMetrica
      metrica={CADASTROS}
      moeda="BRL"
      valor={150}
      anterior={120}
    />,
  );

  expect(lerVariacao()).toBe("↑ +25% · melhora em relação ao período anterior");
});

test("RF-27: numa métrica de custo, a queda aparece como melhora", () => {
  render(
    <CartaoMetrica
      metrica={CUSTO_CADASTRO}
      moeda="BRL"
      valor={20}
      anterior={25}
    />,
  );

  expect(lerVariacao()).toContain("↓ -20% · melhora");
});

test("RF-27: numa métrica de custo, a alta aparece como piora", () => {
  render(
    <CartaoMetrica
      metrica={CUSTO_CADASTRO}
      moeda="BRL"
      valor={30}
      anterior={25}
    />,
  );

  expect(lerVariacao()).toContain("↑ +20% · piora");
});

test("a variação da métrica indiferente aparece sem avaliação", () => {
  render(
    <CartaoMetrica
      metrica={INVESTIMENTO}
      moeda="BRL"
      valor={1250}
      anterior={1000}
    />,
  );

  expect(lerVariacao()).toBe("↑ +25% em relação ao período anterior");
});

test("a variação zero aparece sem seta e sem avaliação", () => {
  render(
    <CartaoMetrica metrica={CADASTROS} moeda="BRL" valor={10} anterior={10} />,
  );

  expect(lerVariacao()).toBe("0% em relação ao período anterior");
});

test.each([
  ["sem dado no período anterior", undefined],
  ["com o anterior zero", 0],
  ["com o anterior nulo", null],
])("RF-27: %s, a variação é travessão", (_descricao, anterior) => {
  render(
    <CartaoMetrica
      metrica={CADASTROS}
      moeda="BRL"
      valor={10}
      anterior={anterior}
    />,
  );

  expect(lerVariacao()).toBe("— em relação ao período anterior");
});
