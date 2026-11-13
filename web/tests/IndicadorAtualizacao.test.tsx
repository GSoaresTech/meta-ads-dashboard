import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { IndicadorAtualizacao } from "@/components/IndicadorAtualizacao";

const ULTIMA_CARGA = new Date("2026-11-13T17:17:00Z");
const SAO_PAULO = "America/Sao_Paulo";

function montar(
  propriedades: Partial<Parameters<typeof IndicadorAtualizacao>[0]> = {},
) {
  render(
    <IndicadorAtualizacao
      ultimaCargaEm={ULTIMA_CARGA}
      fuso={SAO_PAULO}
      desatualizada={false}
      parcial={false}
      {...propriedades}
    />,
  );
  return screen.getByRole("region", { name: "Atualização dos dados" });
}

test("RF-28: exibe o horário da última carga bem-sucedida no fuso da página", () => {
  const indicador = montar();

  expect(indicador.textContent).toContain("13/11/2026, 14:17 BRT");
  expect(indicador.querySelector("time")?.getAttribute("dateTime")).toBe(
    "2026-11-13T17:17:00.000Z",
  );
});

test("RF-28: a carga em dia e o intervalo sem hoje não têm aviso nem marca", () => {
  const indicador = montar();

  expect(indicador.textContent).not.toMatch(/desatualizados/i);
  expect(indicador.textContent).not.toMatch(/parciais/i);
});

test('RF-28: a carga atrasada mostra o aviso "dados desatualizados"', () => {
  const indicador = montar({ desatualizada: true });

  expect(indicador.textContent).toContain(
    "Dados desatualizados Nenhuma atualização nas últimas 3 horas",
  );
});

test("RF-28: sem carga bem-sucedida, diz que não houve atualização e avisa do atraso", () => {
  const indicador = montar({ ultimaCargaEm: null, desatualizada: true });

  expect(indicador.querySelector("time")).toBeNull();
  expect(indicador.textContent).toContain("Nenhuma atualização concluída");
  expect(indicador.textContent).toMatch(/dados desatualizados/i);
});

test("RF-28: o intervalo que inclui hoje mostra a marca de dados parciais", () => {
  const indicador = montar({ parcial: true });

  expect(indicador.textContent).toContain(
    "Dados parciais O dia de hoje ainda está em andamento",
  );
});
