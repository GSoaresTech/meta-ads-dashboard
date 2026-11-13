import { render, screen, within } from "@testing-library/react";
import { expect, test } from "vitest";

import { SeletorPeriodo } from "@/components/SeletorPeriodo";
import type { Selecao } from "@/lib/navegacao";

const CAMINHO = "/empresas/6f1c2d3e-0000-4000-8000-000000000001";
const INTERVALO = { inicio: "2026-10-01", fim: "2026-10-31" };
const INTERVALO_ANTERIOR = { inicio: "2026-09-01", fim: "2026-09-30" };

function montar(selecao: Selecao) {
  render(
    <SeletorPeriodo
      caminho={CAMINHO}
      selecao={selecao}
      intervalo={INTERVALO}
      intervaloAnterior={INTERVALO_ANTERIOR}
    />,
  );
  return {
    atalhos: within(
      screen.getByRole("navigation", { name: "Atalhos de período" }),
    ),
    granularidades: within(
      screen.getByRole("navigation", { name: "Granularidade" }),
    ),
  };
}

test("RF-26: os atalhos oferecidos são os sete do requisito, com rótulos de negócio", () => {
  const { atalhos } = montar({ periodo: "hoje", granularidade: "dia" });

  expect(
    atalhos.getAllByRole("link").map((ligacao) => ligacao.textContent),
  ).toEqual([
    "Hoje",
    "Ontem",
    "Últimos 7 dias",
    "Últimos 30 dias",
    "Este mês",
    "Mês passado",
    "Este ano",
  ]);
});

test("RF-25: as granularidades oferecidas são dia, semana, mês e ano", () => {
  const { granularidades } = montar({ periodo: "hoje", granularidade: "dia" });

  expect(
    granularidades.getAllByRole("link").map((ligacao) => ligacao.textContent),
  ).toEqual(["Dia", "Semana", "Mês", "Ano"]);
});

test("marca o atalho e a granularidade selecionados, e só eles", () => {
  const { atalhos, granularidades } = montar({
    periodo: "mes-passado",
    granularidade: "semana",
  });
  const lerMarcados = (ligacoes: HTMLElement[]) =>
    ligacoes
      .filter((ligacao) => ligacao.getAttribute("aria-current") === "true")
      .map((ligacao) => ligacao.textContent);

  expect(lerMarcados(atalhos.getAllByRole("link"))).toEqual(["Mês passado"]);
  expect(lerMarcados(granularidades.getAllByRole("link"))).toEqual(["Semana"]);
});

test("trocar o atalho mantém a granularidade, e trocar a granularidade mantém o atalho", () => {
  const { atalhos, granularidades } = montar({
    periodo: "este-ano",
    granularidade: "mes",
  });

  expect(
    atalhos.getByRole("link", { name: "Ontem" }).getAttribute("href"),
  ).toBe(`${CAMINHO}?periodo=ontem&granularidade=mes`);
  expect(
    granularidades.getByRole("link", { name: "Ano" }).getAttribute("href"),
  ).toBe(`${CAMINHO}?periodo=este-ano&granularidade=ano`);
});

test("com intervalo livre, nenhum atalho fica marcado, e a granularidade mantém as datas", () => {
  const { atalhos, granularidades } = montar({
    periodo: INTERVALO,
    granularidade: "dia",
  });

  expect(
    atalhos
      .getAllByRole("link")
      .filter((ligacao) => ligacao.hasAttribute("aria-current")),
  ).toEqual([]);
  expect(
    granularidades.getByRole("link", { name: "Semana" }).getAttribute("href"),
  ).toBe(
    `${CAMINHO}?periodo=intervalo&inicio=2026-10-01&fim=2026-10-31&granularidade=semana`,
  );
});

test("RF-35: o intervalo selecionado aparece no formato brasileiro", () => {
  montar({ periodo: "mes-passado", granularidade: "dia" });

  expect(screen.getByText("01/10/2026").getAttribute("datetime")).toBe(
    "2026-10-01",
  );
  expect(screen.getByText("31/10/2026").getAttribute("datetime")).toBe(
    "2026-10-31",
  );
});

test("o formulário do intervalo livre volta à mesma página, com as datas do intervalo atual", () => {
  montar({ periodo: "ontem", granularidade: "ano" });

  const formulario = screen.getByRole("form", { name: "Intervalo livre" });
  expect(formulario.getAttribute("action")).toBe(CAMINHO);
  expect(formulario.getAttribute("method")).toBe("get");
  expect(screen.getByLabelText<HTMLInputElement>("Início").value).toBe(
    "2026-10-01",
  );
  expect(screen.getByLabelText<HTMLInputElement>("Fim").value).toBe(
    "2026-10-31",
  );
});

test("RF-27: mostra o período anterior com que as métricas se comparam", () => {
  montar({ periodo: "mes-passado", granularidade: "dia" });

  const regiao = screen.getByRole("region", {
    name: "Período e granularidade",
  });
  expect(regiao.textContent).toContain("Comparado com 01/09/2026 a 30/09/2026");
});
