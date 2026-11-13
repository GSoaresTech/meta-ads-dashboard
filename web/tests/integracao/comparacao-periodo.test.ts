// @vitest-environment jsdom
import type { Client } from "pg";
import { afterAll, beforeAll, describe, expect, test } from "vitest";

import { formatarMoeda } from "@/lib/formatacao";
import { montarCaminho, type Nivel } from "@/lib/navegacao";

import {
  cadastrarEntidades,
  conectarBancoLocal,
  criarMassaAcesso,
  removerEntidades,
  removerMassaAcesso,
  type IdsEntidades,
  type MassaAcesso,
} from "./banco-local";
import { requisitar } from "./http";
import { acharSecao, lerCartoes } from "./leitura-pagina";

// Prova por HTTP a variação de cada métrica em relação ao período anterior
// equivalente, em todas as visões (RF-27; ADR-0021). As datas são fixas e já
// encerradas. O atalho "mês passado" depende do relógio do servidor, e o
// cálculo dele com data fixa fica no teste unitário do período: aqui, o mês
// inteiro em intervalo livre passa pela mesma regra.
const FUSO = "America/Sao_Paulo";
const TITULO_REAL = "Real brasileiro (BRL)";
const TITULO_DESTAQUE = "Resultado principal";
const CONSULTA_SETEMBRO =
  "periodo=intervalo&inicio=2026-09-01&fim=2026-09-30&granularidade=dia";
const CONSULTA_DEZ_DIAS =
  "periodo=intervalo&inicio=2026-09-10&fim=2026-09-19&granularidade=dia";
const CONSULTA_SEM_ANTERIOR =
  "periodo=intervalo&inicio=2026-08-01&fim=2026-08-10&granularidade=dia";

const CONTA = "Conta Exemplo Comparação";
const CAMPANHA = "Campanha Exemplo Comparação";
const ANUNCIO_CONSTANTE = "Anúncio Exemplo Constante";

// Cada dia de entrega custa 10. Em agosto, 2 compras por 20; em setembro, 4
// compras por 20. O dia 31/08 é a véspera dos 10 dias de 10 a 19/09, e só
// entra na comparação se ela começar no dia certo.
let cliente: Client;
let massa: MassaAcesso;
let ids: IdsEntidades;

beforeAll(async () => {
  cliente = await conectarBancoLocal();
  massa = await criarMassaAcesso(cliente, "Comparação com o Período Anterior");

  ids = await cadastrarEntidades(cliente, massa.empresaA, [
    {
      nome: CONTA,
      fusoHorario: FUSO,
      moeda: "BRL",
      campanhas: [
        {
          nome: CAMPANHA,
          objetivo: "OUTCOME_SALES",
          anuncios: [
            {
              nome: ANUNCIO_CONSTANTE,
              dias: ["2026-08-10", "2026-08-31", "2026-09-10"],
              acoesPorDia: { omni_purchase: 1 },
            },
            {
              nome: "Anúncio Exemplo Setembro",
              dias: ["2026-09-10"],
              acoesPorDia: { omni_purchase: 3 },
            },
          ],
        },
      ],
    },
  ]);
});

afterAll(async () => {
  await removerEntidades(cliente, [massa.empresaA, massa.empresaB]);
  await removerMassaAcesso(cliente, massa);
  await cliente.end();
});

async function abrir(
  nivel: Nivel,
  entidade: string | null,
  consulta: string,
): Promise<Document> {
  const endereco = `${montarCaminho(massa.empresaA, nivel, entidade === null ? null : ids[entidade])}?${consulta}`;
  const resposta = await requisitar(endereco, { credencial: massa.tokenA });
  expect(resposta.status, endereco).toBe(200);
  return new DOMParser().parseFromString(await resposta.text(), "text/html");
}

// O valor e a variação de cada cartão da seção, pelo rótulo.
function lerValores(
  documento: Document,
  titulo: string,
): Record<string, [string, string]> {
  return Object.fromEntries(
    Object.entries(lerCartoes(acharSecao(documento, titulo))).map(
      ([rotulo, [valor, variacao]]) => [rotulo, [valor, variacao]],
    ),
  );
}

function lerComparacao(documento: Document): string | undefined {
  return [...documento.querySelectorAll("main p")]
    .map((paragrafo) => paragrafo.textContent ?? "")
    .find((texto) => texto.startsWith("Comparado com"));
}

describe("RF-27: período anterior equivalente", () => {
  test("o mês inteiro de setembro compara com agosto inteiro, e a queda do custo é melhora", async () => {
    const documento = await abrir("campanha", CAMPANHA, CONSULTA_SETEMBRO);

    expect(lerComparacao(documento)).toBe(
      "Comparado com 01/08/2026 a 31/08/2026",
    );
    expect(lerValores(documento, TITULO_DESTAQUE)).toEqual({
      Compras: ["4", "↑ +100% · melhora em relação ao período anterior"],
      "Custo por compra": [
        formatarMoeda(5, "BRL"),
        "↓ -50% · melhora em relação ao período anterior",
      ],
    });
    expect(lerValores(documento, TITULO_REAL)["Investimento"]).toEqual([
      formatarMoeda(20, "BRL"),
      "0% em relação ao período anterior",
    ]);
  });

  test("um intervalo livre de 10 dias compara com os 10 dias imediatamente anteriores", async () => {
    const documento = await abrir("campanha", CAMPANHA, CONSULTA_DEZ_DIAS);

    expect(lerComparacao(documento)).toBe(
      "Comparado com 31/08/2026 a 09/09/2026",
    );
    expect(lerValores(documento, TITULO_DESTAQUE)).toEqual({
      Compras: ["4", "↑ +300% · melhora em relação ao período anterior"],
      "Custo por compra": [
        formatarMoeda(5, "BRL"),
        "↓ -50% · melhora em relação ao período anterior",
      ],
    });
  });

  test("sem dado no período anterior, a variação é travessão", async () => {
    const documento = await abrir("campanha", CAMPANHA, CONSULTA_SEM_ANTERIOR);

    expect(lerComparacao(documento)).toBe(
      "Comparado com 22/07/2026 a 31/07/2026",
    );
    expect(lerValores(documento, TITULO_DESTAQUE)).toEqual({
      Compras: ["1", "— em relação ao período anterior"],
      "Custo por compra": [
        formatarMoeda(10, "BRL"),
        "— em relação ao período anterior",
      ],
    });
  });

  // O investimento é indiferente: a variação aparece sem avaliação.
  test.each([
    ["Geral", "geral", null, "↑ +100% em relação ao período anterior"],
    ["conta", "conta", CONTA, "↑ +100% em relação ao período anterior"],
    [
      "anúncio",
      "anuncio",
      ANUNCIO_CONSTANTE,
      "0% em relação ao período anterior",
    ],
  ] as const)(
    "a visão %s compara a própria entidade",
    async (_visao, nivel, entidade, esperado) => {
      const documento = await abrir(nivel, entidade, CONSULTA_DEZ_DIAS);

      expect(lerValores(documento, TITULO_REAL)["Investimento"][1]).toBe(
        esperado,
      );
    },
  );
});
