import { afterEach, describe, expect, test, vi } from "vitest";

import {
  formatarData,
  formatarEixoMetrica,
  formatarLeituraMetrica,
  formatarMetrica,
  formatarMoeda,
  formatarNomeMoeda,
  formatarNumero,
  formatarPercentual,
  formatarPeriodo,
  formatarRotuloEixo,
} from "@/lib/formatacao";

// O Intl separa o símbolo do valor com espaço não separável (U+00A0): na tela
// é o "R$ 1.234,56" do RF-35, sem quebra de linha entre o símbolo e o valor.
const ESPACO = " ";

const TRAVESSAO = "—";

const VALORES_AUSENTES = [
  null,
  undefined,
  Number.NaN,
  Number.POSITIVE_INFINITY,
  Number.NEGATIVE_INFINITY,
];

// Um fuso atrás de UTC pega quem lê o dia em UTC e formata no fuso local; um
// fuso à frente pega o inverso, quem lê no fuso local e formata em UTC.
const FUSOS = [
  "America/Sao_Paulo",
  "Pacific/Pago_Pago",
  "Asia/Tokyo",
  "Pacific/Kiritimati",
  "UTC",
];

afterEach(() => {
  vi.unstubAllEnvs();
});

async function carregarModuloNoFuso(fuso: string) {
  vi.stubEnv("TZ", fuso);
  vi.resetModules();
  return import("@/lib/formatacao");
}

describe("formatarMoeda", () => {
  test.each([
    [1234.56, "BRL", `R$${ESPACO}1.234,56`],
    [1234567.89, "BRL", `R$${ESPACO}1.234.567,89`],
    [0.5, "BRL", `R$${ESPACO}0,50`],
    [-1234.56, "BRL", `-R$${ESPACO}1.234,56`],
    [1234.56, "USD", `US$${ESPACO}1.234,56`],
    [1234.56, "EUR", `€${ESPACO}1.234,56`],
  ])("%d em %s vira %s", (valor, moeda, esperado) => {
    expect(formatarMoeda(valor, moeda)).toBe(esperado);
  });

  test("segue as casas decimais de cada moeda, sem fixar duas", () => {
    expect(formatarMoeda(1234.56, "JPY")).toBe(`JP¥${ESPACO}1.235`);
  });

  test("zero é um valor, não ausência", () => {
    expect(formatarMoeda(0, "BRL")).toBe(`R$${ESPACO}0,00`);
  });

  test.each(VALORES_AUSENTES)("%s aparece como travessão", (valor) => {
    expect(formatarMoeda(valor, "BRL")).toBe(TRAVESSAO);
  });
});

describe("formatarNumero", () => {
  test.each([
    [1234, "1.234"],
    [1234567, "1.234.567"],
    [1.87, "1,87"],
    [1.8765, "1,88"],
    [2.5, "2,5"],
    [-1234, "-1.234"],
  ])("%d vira %s", (valor, esperado) => {
    expect(formatarNumero(valor)).toBe(esperado);
  });

  test("zero é um valor, não ausência", () => {
    expect(formatarNumero(0)).toBe("0");
  });

  test.each(VALORES_AUSENTES)("%s aparece como travessão", (valor) => {
    expect(formatarNumero(valor)).toBe(TRAVESSAO);
  });
});

describe("formatarPercentual", () => {
  test.each([
    [0.125, "12,5%"],
    [0.0087, "0,87%"],
    [0.0091, "0,91%"],
    [0.1, "10%"],
    [1, "100%"],
    [12.3456, "1.234,56%"],
    [-0.125, "-12,5%"],
  ])("%d vira %s", (valor, esperado) => {
    expect(formatarPercentual(valor)).toBe(esperado);
  });

  test("zero é um valor, não ausência", () => {
    expect(formatarPercentual(0)).toBe("0%");
  });

  test.each(VALORES_AUSENTES)("%s aparece como travessão", (valor) => {
    expect(formatarPercentual(valor)).toBe(TRAVESSAO);
  });
});

describe("formatarData", () => {
  test("2026-10-29 vira 29/10/2026", () => {
    expect(formatarData("2026-10-29")).toBe("29/10/2026");
  });

  test("completa dia e mês com dois dígitos", () => {
    expect(formatarData("2026-03-05")).toBe("05/03/2026");
  });

  test.each([null, undefined])("%s aparece como travessão", (data) => {
    expect(formatarData(data)).toBe(TRAVESSAO);
  });

  // Sem esta prova, os testes de fuso abaixo passariam sem provar nada na CI,
  // que roda em UTC, se trocar o TZ não tivesse efeito no processo.
  test("o fuso do teste reproduz o recuo de um dia em UTC−3", () => {
    vi.stubEnv("TZ", "America/Sao_Paulo");

    const formatoIngenuo = new Intl.DateTimeFormat("pt-BR");

    expect(formatoIngenuo.format(new Date("2026-10-29"))).toBe("28/10/2026");
  });

  describe.each(FUSOS)("no fuso %s", (fuso) => {
    test("o processo está mesmo nesse fuso", async () => {
      await carregarModuloNoFuso(fuso);

      expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe(fuso);
    });

    test.each([
      ["2026-10-29", "29/10/2026"],
      ["2026-01-01", "01/01/2026"],
      ["2026-12-31", "31/12/2026"],
      ["2024-02-29", "29/02/2024"],
    ])("%s continua sendo %s", async (data, esperado) => {
      const modulo = await carregarModuloNoFuso(fuso);

      expect(modulo.formatarData(data)).toBe(esperado);
    });
  });
});

describe("formatarLeituraMetrica", () => {
  test("a métrica que a leitura não traz é 'Não disponível', e a razão sem denominador é o travessão (ADR-0013)", () => {
    expect(formatarLeituraMetrica(undefined, "moeda", "BRL")).toBe(
      "Não disponível",
    );
    expect(formatarLeituraMetrica(null, "moeda", "BRL")).toBe(TRAVESSAO);
  });

  test("o valor lido segue a unidade do catálogo", () => {
    expect(formatarLeituraMetrica(0, "quantidade", "BRL")).toBe("0");
    expect(formatarLeituraMetrica(20, "moeda", "USD")).toBe(
      `US$${ESPACO}20,00`,
    );
  });
});

describe("formatarMetrica", () => {
  test.each([
    ["moeda", 1234.56, `R$${ESPACO}1.234,56`],
    ["quantidade", 1234, "1.234"],
    ["percentual", 0.125, "12,5%"],
    ["razao", 2.5, "2,5"],
  ] as const)("segue a unidade do catálogo: %s", (unidade, valor, esperado) => {
    expect(formatarMetrica(valor, unidade, "BRL")).toBe(esperado);
  });

  test("usa a moeda da conta", () => {
    expect(formatarMetrica(20, "moeda", "USD")).toBe(`US$${ESPACO}20,00`);
  });

  test("zero é valor, e a ausência vira travessão em toda unidade", () => {
    expect(formatarMetrica(0, "quantidade", "BRL")).toBe("0");
    expect(formatarMetrica(null, "moeda", "BRL")).toBe(TRAVESSAO);
    expect(formatarMetrica(null, "percentual", "BRL")).toBe(TRAVESSAO);
  });
});

describe("formatarEixoMetrica", () => {
  test.each([
    ["moeda", 12000, `R$${ESPACO}12${ESPACO}mil`],
    ["quantidade", 1500000, `1,5${ESPACO}mi`],
    ["quantidade", 250, "250"],
    ["razao", 2.5, "2,5"],
    ["percentual", 0.125, "12,5%"],
  ] as const)("encurta o valor do eixo: %s %d", (unidade, valor, esperado) => {
    expect(formatarEixoMetrica(valor, unidade, "BRL")).toBe(esperado);
  });
});

describe("formatarPeriodo", () => {
  test("um dia aparece uma vez", () => {
    expect(formatarPeriodo("2026-10-29", "2026-10-29")).toBe("29/10/2026");
  });

  test("um período mostra os dois extremos", () => {
    expect(formatarPeriodo("2026-10-26", "2026-11-01")).toBe(
      "26/10/2026 a 01/11/2026",
    );
  });
});

describe("formatarRotuloEixo", () => {
  test.each([
    ["dia", "29/10"],
    ["semana", "29/10"],
    ["mes", "10/2026"],
    ["ano", "2026"],
  ] as const)("segue a granularidade: %s", (granularidade, esperado) => {
    expect(formatarRotuloEixo("2026-10-29", granularidade)).toBe(esperado);
  });

  test.each(FUSOS)("não recua de mês nem de ano no fuso %s", async (fuso) => {
    const modulo = await carregarModuloNoFuso(fuso);

    expect(modulo.formatarRotuloEixo("2026-01-01", "ano")).toBe("2026");
    expect(modulo.formatarRotuloEixo("2026-10-01", "mes")).toBe("10/2026");
  });
});

describe("formatarNomeMoeda", () => {
  test("escreve o nome da moeda em português", () => {
    expect(formatarNomeMoeda("BRL")).toBe("Real brasileiro");
    expect(formatarNomeMoeda("USD")).toBe("Dólar americano");
  });
});
