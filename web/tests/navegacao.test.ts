import { describe, expect, test } from "vitest";

import {
  lerSelecao,
  montarCaminho,
  montarConsulta,
  montarEndereco,
  nomearEntidade,
  resolverIntervalo,
  SELECAO_PADRAO,
  type Selecao,
} from "@/lib/navegacao";
import { ATALHOS, GRANULARIDADES } from "@/lib/periodo";

const EMPRESA = "6f1c2d3e-0000-4000-8000-000000000001";
const ENTIDADE = "6f1c2d3e-0000-4000-8000-000000000002";

// O que o Next.js entrega como searchParams: a mesma chave repetida vira
// lista.
function lerConsulta(consulta: string): Selecao {
  const parametros: Record<string, string | string[]> = {};
  for (const [chave, valor] of new URLSearchParams(consulta)) {
    const anterior = parametros[chave];
    parametros[chave] =
      anterior === undefined ? valor : [anterior, valor].flat();
  }
  return lerSelecao(parametros);
}

describe("lerSelecao", () => {
  test("sem parâmetros, abre nos últimos 30 dias, por dia", () => {
    expect(lerSelecao({})).toEqual({
      periodo: "ultimos-30-dias",
      granularidade: "dia",
    });
    expect(SELECAO_PADRAO).toEqual(lerSelecao({}));
  });

  test.each(
    ATALHOS.flatMap((atalho) => GRANULARIDADES.map((g) => [atalho, g])),
  )("lê o atalho %s com a granularidade %s", (atalho, granularidade) => {
    expect(lerSelecao({ periodo: atalho, granularidade })).toEqual({
      periodo: atalho,
      granularidade,
    });
  });

  test("lê o intervalo livre com início e fim", () => {
    expect(
      lerSelecao({
        periodo: "intervalo",
        inicio: "2026-10-01",
        fim: "2026-10-10",
        granularidade: "semana",
      }),
    ).toEqual({
      periodo: { inicio: "2026-10-01", fim: "2026-10-10" },
      granularidade: "semana",
    });
  });

  test("um atalho ignora início e fim", () => {
    expect(
      lerSelecao({ periodo: "ontem", inicio: "2026-10-01", fim: "2026-10-10" }),
    ).toEqual({ periodo: "ontem", granularidade: "dia" });
  });

  test.each([
    ["atalho desconhecido", { periodo: "trimestre" }],
    ["intervalo sem fim", { periodo: "intervalo", inicio: "2026-10-01" }],
    [
      "intervalo invertido",
      { periodo: "intervalo", inicio: "2026-10-10", fim: "2026-10-01" },
    ],
    ["período repetido", { periodo: ["hoje", "ontem"] }],
  ])("%s volta ao período padrão e mantém a granularidade", (_d, periodo) => {
    expect(lerSelecao({ ...periodo, granularidade: "mes" })).toEqual({
      periodo: SELECAO_PADRAO.periodo,
      granularidade: "mes",
    });
  });

  test.each([
    ["desconhecida", "trimestre"],
    ["repetida", ["dia", "mes"]],
    ["o total do intervalo, que não é escolha da tela", "periodo"],
  ])("granularidade %s volta ao padrão", (_d, granularidade) => {
    expect(lerSelecao({ periodo: "hoje", granularidade })).toEqual({
      periodo: "hoje",
      granularidade: SELECAO_PADRAO.granularidade,
    });
  });
});

describe("montarConsulta", () => {
  test("RF-24: a consulta leva o período e a granularidade, e nada mais", () => {
    expect(
      montarConsulta({ periodo: "ultimos-7-dias", granularidade: "dia" }),
    ).toBe("periodo=ultimos-7-dias&granularidade=dia");
    expect(
      montarConsulta({
        periodo: { inicio: "2026-10-01", fim: "2026-10-10" },
        granularidade: "mes",
      }),
    ).toBe(
      "periodo=intervalo&inicio=2026-10-01&fim=2026-10-10&granularidade=mes",
    );
  });

  test("RF-24: recarregar a consulta devolve a mesma seleção", () => {
    const selecoes: Selecao[] = [
      ...ATALHOS.flatMap((periodo) =>
        GRANULARIDADES.map((granularidade) => ({ periodo, granularidade })),
      ),
      {
        periodo: { inicio: "2026-02-28", fim: "2026-03-01" },
        granularidade: "ano",
      },
    ];

    for (const selecao of selecoes) {
      expect(lerConsulta(montarConsulta(selecao))).toEqual(selecao);
    }
  });
});

describe("montarCaminho", () => {
  test("cada nível tem o próprio caminho, sob a empresa", () => {
    expect(montarCaminho(EMPRESA, "geral", null)).toBe(`/empresas/${EMPRESA}`);
    expect(montarCaminho(EMPRESA, "conta", ENTIDADE)).toBe(
      `/empresas/${EMPRESA}/contas/${ENTIDADE}`,
    );
    expect(montarCaminho(EMPRESA, "campanha", ENTIDADE)).toBe(
      `/empresas/${EMPRESA}/campanhas/${ENTIDADE}`,
    );
    expect(montarCaminho(EMPRESA, "anuncio", ENTIDADE)).toBe(
      `/empresas/${EMPRESA}/anuncios/${ENTIDADE}`,
    );
  });

  test("o endereço junta o caminho do nível e a consulta da seleção", () => {
    expect(
      montarEndereco(montarCaminho(EMPRESA, "campanha", ENTIDADE), {
        periodo: "este-mes",
        granularidade: "semana",
      }),
    ).toBe(
      `/empresas/${EMPRESA}/campanhas/${ENTIDADE}?periodo=este-mes&granularidade=semana`,
    );
  });
});

describe("resolverIntervalo", () => {
  test("o atalho é calculado a partir de hoje, e o intervalo livre fica como veio", () => {
    expect(resolverIntervalo("mes-passado", "2026-11-06")).toEqual({
      inicio: "2026-10-01",
      fim: "2026-10-31",
    });
    expect(
      resolverIntervalo(
        { inicio: "2025-01-01", fim: "2025-01-31" },
        "2026-11-06",
      ),
    ).toEqual({ inicio: "2025-01-01", fim: "2025-01-31" });
  });
});

describe("nomearEntidade", () => {
  test("usa o nome da entidade e, sem ele, o nível dela", () => {
    expect(
      nomearEntidade({
        nivel: "campanha",
        entidadeId: ENTIDADE,
        nome: "Campanha Exemplo",
      }),
    ).toBe("Campanha Exemplo");
    expect(
      nomearEntidade({ nivel: "anuncio", entidadeId: ENTIDADE, nome: null }),
    ).toBe("Anúncio sem nome");
  });
});
