import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { TabelaCampanhas } from "@/components/TabelaCampanhas";
import type { CampanhaListada } from "@/lib/campanhas";
import { formatarMoeda, ROTULO_NAO_DISPONIVEL } from "@/lib/formatacao";
import type { Selecao } from "@/lib/navegacao";
import type { Metrica } from "@/lib/resumo-desempenho";

const EMPRESA = "6f1c2d3e-0000-4000-8000-000000000001";
const CAMPANHA = "6f1c2d3e-0000-4000-8000-000000000002";

const SELECAO: Selecao = {
  periodo: { inicio: "2026-10-01", fim: "2026-10-10" },
  granularidade: "dia",
};

const COMPRAS: Metrica = {
  codigo: "compras",
  rotulo: "Compras",
  explicacao: "Explicação das compras.",
  unidade: "quantidade",
  sentidoMelhora: "alta",
};

const CUSTO_COMPRA: Metrica = {
  codigo: "custo_compra",
  rotulo: "Custo por compra",
  explicacao: "Explicação do custo por compra.",
  unidade: "moeda",
  sentidoMelhora: "queda",
};

const CAMPANHA_VENDAS: CampanhaListada = {
  nivel: "campanha",
  entidadeId: CAMPANHA,
  nome: "Campanha Exemplo",
  objetivo: "Vendas",
  status: "Pausada",
  moeda: "USD",
  resultado: { metrica: COMPRAS, valor: 6 },
  kpi: { metrica: CUSTO_COMPRA, valor: 5 },
};

function lerColunas(campanha: CampanhaListada): string[] {
  render(
    <TabelaCampanhas
      empresaId={EMPRESA}
      campanhas={[campanha]}
      selecao={SELECAO}
    />,
  );
  const [, linha] = screen.getAllByRole("row");
  return [...linha.children].map(lerTextoSemAjuda);
}

// O valor que a célula mostra, sem o texto da ajuda que vai junto.
function lerTextoSemAjuda(celula: Element): string {
  const copia = celula.cloneNode(true) as Element;
  copia.querySelectorAll("details").forEach((ajuda) => ajuda.remove());
  return copia.textContent ?? "";
}

function lerAjudas(): [string, string][] {
  const [, linha] = screen.getAllByRole("row");
  return [...linha.querySelectorAll("details")].map((ajuda) => [
    ajuda.querySelector("summary")?.textContent ?? "",
    ajuda.querySelector("p")?.textContent ?? "",
  ]);
}

test("RF-23: cada campanha é um link para a página dela, que mantém a seleção", () => {
  render(
    <TabelaCampanhas
      empresaId={EMPRESA}
      campanhas={[CAMPANHA_VENDAS]}
      selecao={SELECAO}
    />,
  );

  expect(screen.getByRole("heading", { name: "Campanhas" })).toBeDefined();
  expect(
    screen.getByRole("link", { name: "Campanha Exemplo" }).getAttribute("href"),
  ).toBe(
    `/empresas/${EMPRESA}/campanhas/${CAMPANHA}?periodo=intervalo&inicio=2026-10-01&fim=2026-10-10&granularidade=dia`,
  );
});

test("§3.1 e RF-37: cada linha traz o objetivo, o status, o resultado e o custo, com o rótulo do catálogo e na moeda da conta", () => {
  expect(lerColunas(CAMPANHA_VENDAS)).toEqual([
    "Campanha Exemplo",
    "Vendas",
    "Pausada",
    "Compras: 6",
    `Custo por compra: ${formatarMoeda(5, "USD")}`,
  ]);
});

test("RF-30: o resultado e o custo têm a ajuda com a explicação do catálogo", () => {
  lerColunas(CAMPANHA_VENDAS);

  expect(lerAjudas()).toEqual([
    ["O que é isso? (Compras)", COMPRAS.explicacao],
    ["O que é isso? (Custo por compra)", CUSTO_COMPRA.explicacao],
  ]);
});

test("o custo sem denominador é '—', e a métrica que a leitura não traz é 'Não disponível' (§7.1; ADR-0013)", () => {
  const colunas = lerColunas({
    ...CAMPANHA_VENDAS,
    resultado: { metrica: COMPRAS, valor: undefined },
    kpi: { metrica: CUSTO_COMPRA, valor: null },
  });

  expect(colunas.slice(3)).toEqual([
    `Compras: ${ROTULO_NAO_DISPONIVEL}`,
    "Custo por compra: —",
  ]);
});

test("a campanha sem resultado no catálogo fica sem o resultado e sem o custo (§7.2)", () => {
  const colunas = lerColunas({
    ...CAMPANHA_VENDAS,
    objetivo: "Não classificado",
    resultado: null,
    kpi: null,
  });

  expect(colunas.slice(1)).toEqual(["Não classificado", "Pausada", "—", "—"]);
  expect(lerAjudas()).toEqual([]);
});

test("a campanha ainda sem nome aparece pelo nível", () => {
  render(
    <TabelaCampanhas
      empresaId={EMPRESA}
      campanhas={[{ ...CAMPANHA_VENDAS, nome: null }]}
      selecao={SELECAO}
    />,
  );

  expect(screen.getByRole("link", { name: "Campanha sem nome" })).toBeDefined();
});

test("sem campanhas no período, a tabela dá lugar ao aviso", () => {
  render(
    <TabelaCampanhas empresaId={EMPRESA} campanhas={[]} selecao={SELECAO} />,
  );

  expect(
    screen.getByText("Nenhuma campanha com entrega no período."),
  ).toBeDefined();
  expect(screen.queryByRole("table")).toBeNull();
});
