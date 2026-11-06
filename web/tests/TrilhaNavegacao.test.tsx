import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { TrilhaNavegacao } from "@/components/TrilhaNavegacao";
import type { NivelTrilha, Selecao } from "@/lib/navegacao";

const EMPRESA = "6f1c2d3e-0000-4000-8000-000000000001";
const CONTA = "6f1c2d3e-0000-4000-8000-000000000002";
const CAMPANHA = "6f1c2d3e-0000-4000-8000-000000000003";

const SELECAO: Selecao = { periodo: "este-mes", granularidade: "semana" };
const CONSULTA = "periodo=este-mes&granularidade=semana";

function montarItem(
  nivel: NivelTrilha["nivel"],
  entidadeId: string | null,
  nome: string | null,
): NivelTrilha {
  return { nivel, entidadeId, nome, fusosHorarios: [] };
}

test("RF-23: os níveis acima são links que mantêm a seleção, e o nível em foco é o atual", () => {
  render(
    <TrilhaNavegacao
      empresaId={EMPRESA}
      selecao={SELECAO}
      trilha={[
        montarItem("geral", null, "Empresa Exemplo"),
        montarItem("conta", CONTA, "Conta Exemplo"),
        montarItem("campanha", CAMPANHA, "Campanha Exemplo"),
      ]}
    />,
  );

  expect(screen.getByRole("link", { name: "Geral" }).getAttribute("href")).toBe(
    `/empresas/${EMPRESA}?${CONSULTA}`,
  );
  expect(
    screen.getByRole("link", { name: "Conta Exemplo" }).getAttribute("href"),
  ).toBe(`/empresas/${EMPRESA}/contas/${CONTA}?${CONSULTA}`);
  expect(screen.queryByRole("link", { name: "Campanha Exemplo" })).toBeNull();
  expect(
    screen.getByText("Campanha Exemplo").getAttribute("aria-current"),
  ).toBe("page");
});

test("o primeiro nível se chama Geral, e não pelo nome da empresa", () => {
  render(
    <TrilhaNavegacao
      empresaId={EMPRESA}
      selecao={SELECAO}
      trilha={[montarItem("geral", null, "Empresa Exemplo")]}
    />,
  );

  expect(screen.getByText("Geral").getAttribute("aria-current")).toBe("page");
  expect(screen.queryByText("Empresa Exemplo")).toBeNull();
});

test("a conta ainda sem nome aparece pelo nível", () => {
  render(
    <TrilhaNavegacao
      empresaId={EMPRESA}
      selecao={SELECAO}
      trilha={[
        montarItem("geral", null, "Empresa Exemplo"),
        montarItem("conta", CONTA, null),
      ]}
    />,
  );

  expect(screen.getByText("Conta sem nome")).toBeDefined();
});
