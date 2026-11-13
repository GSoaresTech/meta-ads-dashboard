import { describe, expect, test } from "vitest";

import { avaliarVariacao, calcularVariacao } from "@/lib/variacao";

describe("calcularVariacao", () => {
  test("RF-27: é a variação relativa ao período anterior, como fração", () => {
    expect(calcularVariacao(150, 120)).toBeCloseTo(0.25);
    expect(calcularVariacao(90, 120)).toBeCloseTo(-0.25);
    expect(calcularVariacao(120, 120)).toBe(0);
  });

  test("a variação menor que a casa exibida é zero, para que a seta e a avaliação concordem com o número", () => {
    expect(calcularVariacao(10004, 10000)).toBe(0);
    expect(calcularVariacao(9996, 10000)).toBe(0);
    expect(calcularVariacao(10006, 10000)).toBeCloseTo(0.001);
  });

  test("o atual zero é queda de 100%", () => {
    expect(calcularVariacao(0, 40)).toBe(-1);
  });

  test.each([
    ["sem o valor anterior, que a leitura não trouxe", 10, undefined],
    ["com o anterior nulo, a razão sem denominador", 10, null],
    ["com o anterior zero, que não tem base de comparação", 10, 0],
    ["sem o valor atual", undefined, 10],
    ["com o atual nulo", null, 10],
  ])("RF-27: não há variação %s", (_descricao, atual, anterior) => {
    expect(calcularVariacao(atual, anterior)).toBeNull();
  });
});

describe("avaliarVariacao", () => {
  test("RF-27: nas métricas de custo, a queda é melhora e a alta é piora", () => {
    expect(avaliarVariacao(-0.1, "queda")).toBe("melhora");
    expect(avaliarVariacao(0.1, "queda")).toBe("piora");
  });

  test("nas métricas que melhoram na alta, a alta é melhora e a queda é piora", () => {
    expect(avaliarVariacao(0.1, "alta")).toBe("melhora");
    expect(avaliarVariacao(-0.1, "alta")).toBe("piora");
  });

  test("a métrica indiferente, a variação zero e a ausente não são avaliadas", () => {
    expect(avaliarVariacao(0.1, "indiferente")).toBeNull();
    expect(avaliarVariacao(-0.1, "indiferente")).toBeNull();
    expect(avaliarVariacao(0, "alta")).toBeNull();
    expect(avaliarVariacao(null, "queda")).toBeNull();
  });
});
