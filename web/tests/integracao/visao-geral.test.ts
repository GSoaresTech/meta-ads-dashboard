// @vitest-environment jsdom
import type { Client } from "pg";
import { afterAll, beforeAll, describe, expect, test } from "vitest";

import { formatarMoeda } from "@/lib/formatacao";
import { calcularIntervalo, obterHoje } from "@/lib/periodo";

import {
  cadastrarEntidades,
  conectarBancoLocal,
  criarMassaAcesso,
  removerEntidades,
  removerMassaAcesso,
  type MassaAcesso,
} from "./banco-local";
import { requisitar } from "./http";
import {
  acharSecao,
  lerCartoes,
  lerSerie,
  lerValorMoeda,
} from "./leitura-pagina";

// Prova a visão Geral por HTTP: os totais e as séries por moeda, os tipos de
// resultado e o catálogo (REQUIREMENTS §3.1 e §3.3; RF-25, RF-30, RF-34;
// ADR-0013). As datas de setembro são fixas e já encerradas; a empresa B usa
// o relógio, porque o critério do RF-25 fala de "este ano".
const FUSO = "America/Sao_Paulo";
const TITULO_REAL = "Real brasileiro (BRL)";
const TITULO_DOLAR = "Dólar americano (USD)";
const INVESTIMENTO_DIARIO = 10;

// Os campos e enums da API que a tela nunca mostra (RNF-02), inclusive os
// tipos de ação gravados nesta massa.
const CAMPOS_API = [
  "spend",
  "impressions",
  "reach",
  "frequency",
  "clicks",
  "cpc",
  "cpm",
  "ctr",
  "actions",
  "action_values",
  "cost_per_action_type",
  "omni_purchase",
  "lead",
  "link_click",
  "OUTCOME_",
  "ACTIVE",
];

const DIAS_REAL = ["2026-09-07", "2026-09-08", "2026-09-14"];
const DIAS_DOLAR = ["2026-09-07", "2026-09-14"];
const CONSULTA_SETEMBRO =
  "periodo=intervalo&inicio=2026-09-01&fim=2026-09-30&granularidade=semana";

let cliente: Client;
let massa: MassaAcesso;
let hoje: string;

beforeAll(async () => {
  cliente = await conectarBancoLocal();
  massa = await criarMassaAcesso(cliente, "Visão Geral");
  hoje = obterHoje(new Date(), [FUSO]);

  await cadastrarEntidades(cliente, massa.empresaA, [
    {
      nome: "Conta Exemplo Real",
      fusoHorario: FUSO,
      moeda: "BRL",
      campanhas: [
        {
          nome: "Campanha Exemplo Vendas",
          objetivo: "OUTCOME_SALES",
          anuncios: [
            {
              nome: "Anúncio Exemplo Vendas",
              dias: DIAS_REAL,
              acoesPorDia: { omni_purchase: 2 },
            },
          ],
        },
        {
          nome: "Campanha Exemplo Reconhecimento",
          objetivo: "OUTCOME_AWARENESS",
          anuncios: [{ nome: "Anúncio Exemplo Reconhecimento", dias: [] }],
        },
      ],
    },
    {
      nome: "Conta Exemplo Dólar",
      fusoHorario: FUSO,
      moeda: "USD",
      campanhas: [
        {
          nome: "Campanha Exemplo Cadastros",
          objetivo: "OUTCOME_LEADS",
          anuncios: [
            {
              nome: "Anúncio Exemplo Cadastros",
              dias: DIAS_DOLAR,
              acoesPorDia: { lead: 3 },
            },
          ],
        },
      ],
    },
  ]);

  const { inicio } = calcularIntervalo("este-ano", hoje);
  await cadastrarEntidades(cliente, massa.empresaB, [
    {
      nome: "Conta Exemplo Ano",
      fusoHorario: FUSO,
      moeda: "BRL",
      campanhas: [
        {
          nome: "Campanha Exemplo Ano",
          anuncios: [{ nome: "Anúncio Exemplo Ano", dias: [inicio, hoje] }],
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

interface Pagina {
  documento: Document;
  html: string;
  // O conteúdo da página, sem os scripts que levam os dados do React.
  texto: string;
}

async function abrirGeral(
  empresaId: string,
  credencial: string,
  consulta: string,
): Promise<Pagina> {
  const endereco = `/empresas/${empresaId}?${consulta}`;
  const resposta = await requisitar(endereco, { credencial });
  expect(resposta.status, endereco).toBe(200);
  const html = await resposta.text();
  const documento = new DOMParser().parseFromString(html, "text/html");
  return {
    documento,
    html,
    texto: documento.querySelector("main")?.textContent ?? "",
  };
}

function abrirSetembro(): Promise<Pagina> {
  return abrirGeral(massa.empresaA, massa.tokenA, CONSULTA_SETEMBRO);
}

describe("RF-34: totais separados por moeda", () => {
  test("uma conta em BRL e outra em USD mostram dois totais de investimento e nenhum combinado", async () => {
    const { documento, texto } = await abrirSetembro();

    const real = lerCartoes(acharSecao(documento, TITULO_REAL));
    const dolar = lerCartoes(acharSecao(documento, TITULO_DOLAR));

    const totalReal = INVESTIMENTO_DIARIO * DIAS_REAL.length;
    const totalDolar = INVESTIMENTO_DIARIO * DIAS_DOLAR.length;
    expect(real["Investimento"][0]).toBe(formatarMoeda(totalReal, "BRL"));
    expect(dolar["Investimento"][0]).toBe(formatarMoeda(totalDolar, "USD"));
    expect(texto).not.toContain(`${totalReal + totalDolar},00`);
  });

  test("cada moeda tem a própria série, em que os períodos somam o total dela", async () => {
    const { documento } = await abrirSetembro();

    const real = lerSerie(acharSecao(documento, TITULO_REAL), "Investimento");
    const dolar = lerSerie(acharSecao(documento, TITULO_DOLAR), "Investimento");

    // Setembro de 2026 toca cinco semanas ISO, a primeira cortada no dia 1.
    expect(real.map(([periodo]) => periodo)).toEqual([
      "01/09/2026 a 06/09/2026",
      "07/09/2026 a 13/09/2026",
      "14/09/2026 a 20/09/2026",
      "21/09/2026 a 27/09/2026",
      "28/09/2026 a 30/09/2026",
    ]);
    expect(real.map(([, valor]) => valor)).toEqual(
      [0, 20, 10, 0, 0].map((valor) => formatarMoeda(valor, "BRL")),
    );
    expect(dolar.map(([, valor]) => valor)).toEqual(
      [0, 10, 10, 0, 0].map((valor) => formatarMoeda(valor, "USD")),
    );
  });
});

describe("§3.1: totais de cada tipo de resultado", () => {
  test("cada moeda mostra só o resultado das campanhas com entrega nela, com o total somado", async () => {
    const { documento } = await abrirSetembro();

    const real = lerCartoes(acharSecao(documento, TITULO_REAL));
    const dolar = lerCartoes(acharSecao(documento, TITULO_DOLAR));

    expect(Object.keys(real)).toEqual(["Investimento", "Compras"]);
    expect(Object.keys(dolar)).toEqual(["Investimento", "Cadastros"]);
    expect(real["Compras"][0]).toBe("6");
    expect(dolar["Cadastros"][0]).toBe("6");
  });

  test("a campanha sem entrega no período não acrescenta tipo", async () => {
    const { documento } = await abrirSetembro();

    expect(
      Object.keys(lerCartoes(acharSecao(documento, TITULO_REAL))),
    ).not.toContain("Pessoas alcançadas");
  });

  test("a campanha de reconhecimento com entrega mostra o alcance como não disponível, sem série (§3.3)", async () => {
    const dia = "2026-08-10";
    const [anuncio] = (
      await cliente.query<{ id: string }>(
        `SELECT anuncio.id
         FROM normalizado.anuncio AS anuncio
         WHERE anuncio.empresa_id = $1 AND anuncio.nome = 'Anúncio Exemplo Reconhecimento'`,
        [massa.empresaA],
      )
    ).rows;
    await cliente.query(
      `INSERT INTO normalizado.metrica_diaria_anuncio
         (empresa_id, anuncio_id, data, investimento, impressoes, execucao_id)
       SELECT empresa_id, id, $2, 10.00, 100, execucao_id
       FROM normalizado.anuncio WHERE id = $1`,
      [anuncio.id, dia],
    );

    const { documento } = await abrirGeral(
      massa.empresaA,
      massa.tokenA,
      `periodo=intervalo&inicio=${dia}&fim=${dia}&granularidade=dia`,
    );
    const secao = acharSecao(documento, TITULO_REAL);

    expect(lerCartoes(secao)["Pessoas alcançadas"][0]).toBe("Não disponível");
    expect(lerSerie(secao, "Pessoas alcançadas")).toEqual([]);
  });
});

describe("RF-30: rótulos e explicações vêm do catálogo", () => {
  test("cada cartão exibido tem o rótulo e a explicação de uma métrica do catálogo", async () => {
    const { documento } = await abrirSetembro();
    const { rows } = await cliente.query<{
      rotulo: string;
      explicacao: string;
    }>("SELECT rotulo, explicacao FROM normalizado.metrica");
    const explicacoes = new Map(
      rows.map(({ rotulo, explicacao }) => [rotulo, explicacao]),
    );

    const cartoes = Object.entries({
      ...lerCartoes(acharSecao(documento, TITULO_REAL)),
      ...lerCartoes(acharSecao(documento, TITULO_DOLAR)),
    });

    expect(cartoes.length).toBeGreaterThan(0);
    for (const [rotulo, paragrafos] of cartoes) {
      expect(explicacoes.has(rotulo), rotulo).toBe(true);
      expect(paragrafos, rotulo).toContain(explicacoes.get(rotulo));
    }
  });

  test("mudar uma explicação no catálogo muda a tela", async () => {
    const explicacaoTeste = "Explicação alterada só no catálogo.";
    const { rows } = await cliente.query<{ explicacao: string }>(
      "SELECT explicacao FROM normalizado.metrica WHERE codigo = 'investimento'",
    );

    try {
      await cliente.query(
        "UPDATE normalizado.metrica SET explicacao = $1 WHERE codigo = 'investimento'",
        [explicacaoTeste],
      );
      const { documento } = await abrirSetembro();

      expect(
        lerCartoes(acharSecao(documento, TITULO_REAL))["Investimento"],
      ).toContain(explicacaoTeste);
    } finally {
      await cliente.query(
        "UPDATE normalizado.metrica SET explicacao = $1 WHERE codigo = 'investimento'",
        [rows[0].explicacao],
      );
    }
  });
});

describe("RF-25: a série segue a granularidade", () => {
  test("com 'este ano' e 'mês', a série tem um ponto por mês, e a soma dos meses é o total do ano", async () => {
    const { documento } = await abrirGeral(
      massa.empresaB,
      massa.tokenB,
      "periodo=este-ano&granularidade=mes",
    );
    const secao = acharSecao(documento, TITULO_REAL);

    const pontos = lerSerie(secao, "Investimento");
    const total = lerCartoes(secao)["Investimento"][0];

    expect(pontos).toHaveLength(Number(hoje.slice(5, 7)));
    expect(
      pontos.reduce((soma, [, valor]) => soma + lerValorMoeda(valor), 0),
    ).toBe(lerValorMoeda(total));
  });
});

describe("visão Geral", () => {
  test("sem dados no intervalo, a página responde e diz isso", async () => {
    const { texto, documento } = await abrirGeral(
      massa.empresaA,
      massa.tokenA,
      "periodo=intervalo&inicio=2020-01-01&fim=2020-01-31&granularidade=dia",
    );

    expect(texto).toContain("Nenhum dado no período.");
    expect(documento.querySelectorAll("article")).toHaveLength(0);
  });

  test("o operador vê os totais de qualquer empresa", async () => {
    const { documento } = await abrirGeral(
      massa.empresaA,
      massa.tokenOperador,
      CONSULTA_SETEMBRO,
    );

    expect(acharSecao(documento, TITULO_DOLAR)).toBeDefined();
  });

  test("a página não leva o token nos dados que vão ao navegador", async () => {
    const { html } = await abrirSetembro();

    expect(html).not.toContain(massa.tokenA);
  });

  test("RNF-02: a tela não mostra código de métrica nem nome de campo ou enum da API", async () => {
    const { texto } = await abrirSetembro();
    const { rows } = await cliente.query<{ codigo: string }>(
      // Os códigos de uma palavra só, como "compras", são palavras do texto.
      "SELECT codigo FROM normalizado.metrica WHERE codigo LIKE '%\\_%'",
    );

    const termos = [...CAMPOS_API, ...rows.map(({ codigo }) => codigo)];
    expect(rows.length).toBeGreaterThan(0);
    for (const termo of termos) {
      expect(texto).not.toMatch(new RegExp(`\\b${termo}`));
    }
  });

  test("a página do anúncio continua sem os totais, que chegam com a visão dela", async () => {
    const { rows } = await cliente.query<{ id: string }>(
      "SELECT id FROM normalizado.anuncio WHERE empresa_id = $1 LIMIT 1",
      [massa.empresaA],
    );
    const resposta = await requisitar(
      `/empresas/${massa.empresaA}/anuncios/${rows[0].id}?${CONSULTA_SETEMBRO}`,
      { credencial: massa.tokenA },
    );
    const documento = new DOMParser().parseFromString(
      await resposta.text(),
      "text/html",
    );

    expect(resposta.status).toBe(200);
    expect(documento.querySelectorAll("article")).toHaveLength(0);
  });
});
