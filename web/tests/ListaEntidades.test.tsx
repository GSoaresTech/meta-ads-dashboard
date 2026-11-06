import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { ListaEntidades } from "@/components/ListaEntidades";
import type { Selecao } from "@/lib/navegacao";

const EMPRESA = "6f1c2d3e-0000-4000-8000-000000000001";
const ANUNCIO = "6f1c2d3e-0000-4000-8000-000000000002";

const SELECAO: Selecao = {
  periodo: { inicio: "2026-10-01", fim: "2026-10-10" },
  granularidade: "dia",
};

test("RF-23: cada filha é um link para o nível dela, que mantém a seleção", () => {
  render(
    <ListaEntidades
      empresaId={EMPRESA}
      nivel="anuncio"
      selecao={SELECAO}
      filhas={[
        { nivel: "anuncio", entidadeId: ANUNCIO, nome: "Anúncio Exemplo" },
      ]}
    />,
  );

  expect(screen.getByRole("heading", { name: "Anúncios" })).toBeDefined();
  expect(
    screen.getByRole("link", { name: "Anúncio Exemplo" }).getAttribute("href"),
  ).toBe(
    `/empresas/${EMPRESA}/anuncios/${ANUNCIO}?periodo=intervalo&inicio=2026-10-01&fim=2026-10-10&granularidade=dia`,
  );
});

test("a filha ainda sem nome aparece pelo nível", () => {
  render(
    <ListaEntidades
      empresaId={EMPRESA}
      nivel="anuncio"
      selecao={SELECAO}
      filhas={[{ nivel: "anuncio", entidadeId: ANUNCIO, nome: null }]}
    />,
  );

  expect(screen.getByRole("link", { name: "Anúncio sem nome" })).toBeDefined();
});

test.each([
  ["conta", "Nenhuma conta com entrega no período."],
  ["campanha", "Nenhuma campanha com entrega no período."],
  ["anuncio", "Nenhum anúncio com entrega no período."],
] as const)("sem filhas no período, a lista de %s avisa", (nivel, aviso) => {
  render(
    <ListaEntidades
      empresaId={EMPRESA}
      nivel={nivel}
      selecao={SELECAO}
      filhas={[]}
    />,
  );

  expect(screen.getByText(aviso)).toBeDefined();
  expect(screen.queryByRole("list")).toBeNull();
});
