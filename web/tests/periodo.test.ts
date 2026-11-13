import { describe, expect, test } from "vitest";

import {
  ATALHOS,
  calcularIntervalo,
  lerIntervalo,
  obterFusoReferencia,
  obterHoje,
  type Atalho,
  type Intervalo,
} from "@/lib/periodo";

// RF-26: cada atalho seleciona o intervalo correto no fuso da conta, com o
// relógio fixo. 03:43 de Brasília de 06/11/2026 é 22:43 de 05/11/2026 em
// Los Angeles, que já saiu do horário de verão em 01/11/2026.
const MADRUGADA_BRASILIA = new Date("2026-11-06T06:43:00Z");
const SAO_PAULO = "America/Sao_Paulo";
const LOS_ANGELES = "America/Los_Angeles";

describe("obterFusoReferencia", () => {
  test("com contas em fusos diferentes, é o fuso da conta mais atrasada, em qualquer ordem", () => {
    expect(
      obterFusoReferencia(MADRUGADA_BRASILIA, [SAO_PAULO, LOS_ANGELES]),
    ).toBe(LOS_ANGELES);
    expect(
      obterFusoReferencia(MADRUGADA_BRASILIA, [LOS_ANGELES, SAO_PAULO]),
    ).toBe(LOS_ANGELES);
  });

  test("sem conta com fuso, é UTC, como na rotina diária", () => {
    expect(obterFusoReferencia(MADRUGADA_BRASILIA, [])).toBe("UTC");
  });
});

describe("obterHoje", () => {
  test("o dia corrente sai no fuso da conta, e não no do servidor", () => {
    expect(obterHoje(MADRUGADA_BRASILIA, [SAO_PAULO])).toBe("2026-11-06");
    expect(obterHoje(MADRUGADA_BRASILIA, [LOS_ANGELES])).toBe("2026-11-05");
  });

  test("com contas em fusos diferentes, vale o dia da conta mais atrasada, em qualquer ordem", () => {
    expect(obterHoje(MADRUGADA_BRASILIA, [SAO_PAULO, LOS_ANGELES])).toBe(
      "2026-11-05",
    );
    expect(obterHoje(MADRUGADA_BRASILIA, [LOS_ANGELES, SAO_PAULO])).toBe(
      "2026-11-05",
    );
  });

  test("sem conta com fuso, o dia é o de UTC, como na rotina diária", () => {
    const agora = new Date("2026-11-06T01:00:00Z");

    expect(obterHoje(agora, [])).toBe("2026-11-06");
    expect(obterHoje(agora, [SAO_PAULO])).toBe("2026-11-05");
  });
});

describe("calcularIntervalo", () => {
  const casos: [string, Atalho, Intervalo][] = [
    ["hoje", "hoje", { inicio: "2026-11-06", fim: "2026-11-06" }],
    ["ontem", "ontem", { inicio: "2026-11-05", fim: "2026-11-05" }],
    [
      "últimos 7 dias, terminando ontem",
      "ultimos-7-dias",
      { inicio: "2026-10-30", fim: "2026-11-05" },
    ],
    [
      "últimos 30 dias, terminando ontem",
      "ultimos-30-dias",
      { inicio: "2026-10-07", fim: "2026-11-05" },
    ],
    [
      "este mês, até hoje",
      "este-mes",
      { inicio: "2026-11-01", fim: "2026-11-06" },
    ],
    [
      "mês passado, inteiro",
      "mes-passado",
      { inicio: "2026-10-01", fim: "2026-10-31" },
    ],
    [
      "este ano, até hoje",
      "este-ano",
      { inicio: "2026-01-01", fim: "2026-11-06" },
    ],
  ];

  test.each(casos)("%s", (_descricao, atalho, esperado) => {
    expect(calcularIntervalo(atalho, "2026-11-06")).toEqual(esperado);
  });

  test("cada atalho tem um caso acima", () => {
    expect(casos.map(([, atalho]) => atalho).sort()).toEqual(
      [...ATALHOS].sort(),
    );
  });

  test("os últimos 7 e 30 dias têm exatamente 7 e 30 dias", () => {
    const contarDias = ({ inicio, fim }: Intervalo) =>
      (Date.parse(fim) - Date.parse(inicio)) / 86_400_000 + 1;

    expect(contarDias(calcularIntervalo("ultimos-7-dias", "2026-11-06"))).toBe(
      7,
    );
    expect(contarDias(calcularIntervalo("ultimos-30-dias", "2026-11-06"))).toBe(
      30,
    );
  });

  test("no primeiro dia do ano, ontem e o mês passado ficam no ano anterior", () => {
    const hoje = "2026-01-01";

    expect(calcularIntervalo("ontem", hoje)).toEqual({
      inicio: "2025-12-31",
      fim: "2025-12-31",
    });
    expect(calcularIntervalo("ultimos-7-dias", hoje)).toEqual({
      inicio: "2025-12-25",
      fim: "2025-12-31",
    });
    expect(calcularIntervalo("mes-passado", hoje)).toEqual({
      inicio: "2025-12-01",
      fim: "2025-12-31",
    });
    expect(calcularIntervalo("este-mes", hoje)).toEqual({
      inicio: "2026-01-01",
      fim: "2026-01-01",
    });
    expect(calcularIntervalo("este-ano", hoje)).toEqual({
      inicio: "2026-01-01",
      fim: "2026-01-01",
    });
  });

  test("em ano bissexto, o mês passado de março termina em 29 de fevereiro", () => {
    expect(calcularIntervalo("mes-passado", "2028-03-01")).toEqual({
      inicio: "2028-02-01",
      fim: "2028-02-29",
    });
    expect(calcularIntervalo("ultimos-30-dias", "2028-03-01")).toEqual({
      inicio: "2028-01-31",
      fim: "2028-02-29",
    });
  });

  test("o mesmo instante dá meses diferentes em contas de fusos diferentes", () => {
    const agora = new Date("2026-12-01T02:00:00Z");

    expect(
      calcularIntervalo("este-mes", obterHoje(agora, [SAO_PAULO])),
    ).toEqual({ inicio: "2026-11-01", fim: "2026-11-30" });
    expect(calcularIntervalo("este-mes", obterHoje(agora, []))).toEqual({
      inicio: "2026-12-01",
      fim: "2026-12-01",
    });
  });

  test("ao descer do Geral para a conta adiantada, nas horas de diferença, o atalho é recalculado e cobre outro mês", () => {
    const viradaDoMes = new Date("2026-12-01T04:00:00Z");
    const hojeGeral = obterHoje(viradaDoMes, [SAO_PAULO, LOS_ANGELES]);
    const hojeConta = obterHoje(viradaDoMes, [SAO_PAULO]);

    expect(calcularIntervalo("este-mes", hojeGeral)).toEqual({
      inicio: "2026-11-01",
      fim: "2026-11-30",
    });
    expect(calcularIntervalo("este-mes", hojeConta)).toEqual({
      inicio: "2026-12-01",
      fim: "2026-12-01",
    });
  });

  test("RF-26: no Geral com contas em São Paulo e Los Angeles, às 03:43 de Brasília de 06/11/2026, hoje é 05/11 e ontem é 04/11", () => {
    const hoje = obterHoje(MADRUGADA_BRASILIA, [SAO_PAULO, LOS_ANGELES]);

    expect(calcularIntervalo("hoje", hoje)).toEqual({
      inicio: "2026-11-05",
      fim: "2026-11-05",
    });
    expect(calcularIntervalo("ontem", hoje)).toEqual({
      inicio: "2026-11-04",
      fim: "2026-11-04",
    });
  });
});

describe("lerIntervalo", () => {
  test("aceita dois dias em AAAA-MM-DD, com o início até o fim", () => {
    expect(lerIntervalo("2026-10-01", "2026-10-10")).toEqual({
      inicio: "2026-10-01",
      fim: "2026-10-10",
    });
    expect(lerIntervalo("2026-10-01", "2026-10-01")).toEqual({
      inicio: "2026-10-01",
      fim: "2026-10-01",
    });
  });

  test.each([
    ["início depois do fim", "2026-10-10", "2026-10-01"],
    ["dia que não existe", "2026-02-30", "2026-03-01"],
    ["mês que não existe", "2026-13-01", "2026-12-31"],
    ["ano que o banco não aceita", "0000-01-01", "2026-01-01"],
    ["outro formato", "01/10/2026", "2026-10-10"],
    ["texto com dia no meio", "x2026-10-01", "2026-10-10"],
    ["início ausente", undefined, "2026-10-10"],
    ["fim repetido na URL", "2026-10-01", ["2026-10-10", "2026-10-11"]],
  ])("recusa %s", (_descricao, inicio, fim) => {
    expect(lerIntervalo(inicio, fim)).toBeNull();
  });
});
