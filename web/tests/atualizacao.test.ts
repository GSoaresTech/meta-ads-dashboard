import { describe, expect, test } from "vitest";

import {
  alcancaHoje,
  estaDesatualizada,
  LIMITE_ATUALIZACAO_HORAS,
} from "@/lib/atualizacao";
import { obterHoje } from "@/lib/periodo";

// RF-28: o relógio entra como parâmetro, e os testes fixam o instante.
const MADRUGADA_BRASILIA = new Date("2026-11-06T06:43:00Z");
const SAO_PAULO = "America/Sao_Paulo";
const LOS_ANGELES = "America/Los_Angeles";
const AGORA = new Date("2026-11-13T17:00:00Z");
const MILISSEGUNDOS_HORA = 60 * 60 * 1000;

function voltarHoras(horas: number): Date {
  return new Date(AGORA.getTime() - horas * MILISSEGUNDOS_HORA);
}

describe("estaDesatualizada", () => {
  test("o limite do atraso é de 3 horas", () => {
    expect(LIMITE_ATUALIZACAO_HORAS).toBe(3);
  });

  test("a carga de 1 hora atrás está em dia", () => {
    expect(estaDesatualizada(voltarHoras(1), AGORA)).toBe(false);
  });

  test("a carga de exatamente 3 horas atrás ainda está em dia, porque o aviso é para mais de 3 horas", () => {
    expect(estaDesatualizada(voltarHoras(3), AGORA)).toBe(false);
  });

  test("a carga de 3 horas e 1 minuto atrás está desatualizada", () => {
    expect(estaDesatualizada(voltarHoras(3 + 1 / 60), AGORA)).toBe(true);
  });

  test("a empresa sem nenhuma carga bem-sucedida está desatualizada", () => {
    expect(estaDesatualizada(null, AGORA)).toBe(true);
  });
});

describe("alcancaHoje", () => {
  const HOJE = "2026-11-13";

  test.each([
    ["só hoje", "2026-11-13", "2026-11-13"],
    ["este mês, até hoje", "2026-11-01", "2026-11-13"],
    ["intervalo livre que passa de hoje", "2026-11-10", "2026-11-20"],
  ])("%s tem dados parciais", (_, inicio, fim) => {
    expect(alcancaHoje({ inicio, fim }, HOJE)).toBe(true);
  });

  test.each([
    ["ontem", "2026-11-12", "2026-11-12"],
    ["últimos 7 dias, que terminam ontem", "2026-11-06", "2026-11-12"],
  ])("%s não tem dados parciais", (_, inicio, fim) => {
    expect(alcancaHoje({ inicio, fim }, HOJE)).toBe(false);
  });

  // Às 03:43 de Brasília de 06/11/2026, o "hoje" do Geral com uma conta em
  // Brasília e outra em Los Angeles é 05/11, e o 06/11 já corre em Brasília.
  test("no Geral com fusos diferentes, o dia corrente da conta adiantada tem dados parciais", () => {
    const hojeGeral = obterHoje(MADRUGADA_BRASILIA, [SAO_PAULO, LOS_ANGELES]);

    expect(
      alcancaHoje({ inicio: "2026-11-06", fim: "2026-11-06" }, hojeGeral),
    ).toBe(true);
  });
});
