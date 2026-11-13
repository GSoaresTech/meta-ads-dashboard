// @vitest-environment jsdom
import type { Client } from "pg";
import { afterAll, beforeAll, describe, expect, test } from "vitest";

import { formatarMoeda } from "@/lib/formatacao";
import { montarCaminho } from "@/lib/navegacao";

import {
  cadastrarEntidades,
  conectarBancoLocal,
  criarMassaAcesso,
  removerEntidades,
  lerExplicacoesCatalogo,
  removerMassaAcesso,
  type IdsEntidades,
  type MassaAcesso,
} from "./banco-local";
import { requisitar } from "./http";
import {
  acharSecao,
  lerCartoes,
  lerSerie,
  lerValorMoeda,
  listarMetricasExibidas,
} from "./leitura-pagina";

// Prova a visão da campanha por HTTP: o destaque com o resultado principal e
// o KPI do objetivo, as métricas de apoio, as séries e a lista de anúncios
// (REQUIREMENTS §3.1; RF-23, RF-25, RF-30, RF-31; ADR-0007). As datas de
// setembro são fixas e já encerradas.
const FUSO = "America/Sao_Paulo";
const TITULO_DESTAQUE = "Resultado principal";
const TITULO_REAL = "Real brasileiro (BRL)";
const CONSULTA_SETEMBRO =
  "periodo=intervalo&inicio=2026-09-01&fim=2026-09-30&granularidade=semana";
const CONSULTA_SEM_DADOS =
  "periodo=intervalo&inicio=2020-01-01&fim=2020-01-31&granularidade=dia";
const SEM_RESULTADO =
  "O objetivo desta campanha não tem resultado principal definido.";

const CAMPANHA_VENDAS = "Campanha Exemplo Vendas";
const CAMPANHA_MENSAGENS = "Campanha Exemplo Mensagens";
const CAMPANHA_DESCONHECIDA = "Campanha Exemplo Desconhecida";

// Os valores de enum e os tipos de ação gravados nesta massa, que a tela
// nunca mostra (RNF-02; RF-37).
const TERMOS_API = [
  "OUTCOME_",
  "OFFSITE_CONVERSIONS",
  "CONVERSATIONS",
  "ACTIVE",
  "PAUSED",
  "omni_purchase",
  "link_click",
  "onsite_conversion",
];

let cliente: Client;
let massa: MassaAcesso;
let ids: IdsEntidades;

beforeAll(async () => {
  cliente = await conectarBancoLocal();
  massa = await criarMassaAcesso(cliente, "Visão da Campanha");

  ids = await cadastrarEntidades(cliente, massa.empresaA, [
    {
      nome: "Conta Exemplo Campanhas",
      fusoHorario: FUSO,
      moeda: "BRL",
      campanhas: [
        {
          nome: CAMPANHA_VENDAS,
          objetivo: "OUTCOME_SALES",
          metaOtimizacao: "OFFSITE_CONVERSIONS",
          anuncios: [
            {
              nome: "Anúncio Exemplo Vendas Um",
              dias: ["2026-09-07", "2026-09-08", "2026-09-14"],
              acoesPorDia: { omni_purchase: 2, link_click: 4 },
            },
            {
              nome: "Anúncio Exemplo Vendas Dois",
              dias: ["2026-09-14"],
              acoesPorDia: { omni_purchase: 2 },
            },
            {
              // Sem entrega em setembro: não entra na lista.
              nome: "Anúncio Exemplo Vendas Antigo",
              dias: ["2026-08-10"],
            },
          ],
        },
        {
          // A meta de otimização do conjunto escolhe a regra de conversas.
          nome: CAMPANHA_MENSAGENS,
          objetivo: "OUTCOME_ENGAGEMENT",
          status: "PAUSED",
          metaOtimizacao: "CONVERSATIONS",
          anuncios: [
            {
              nome: "Anúncio Exemplo Mensagens",
              dias: ["2026-09-07", "2026-09-21"],
              acoesPorDia: {
                "onsite_conversion.messaging_conversation_started_7d": 5,
              },
            },
          ],
        },
        {
          nome: CAMPANHA_DESCONHECIDA,
          objetivo: "OUTCOME_TESTE",
          anuncios: [
            {
              nome: "Anúncio Exemplo Desconhecido",
              dias: ["2026-09-08"],
              acoesPorDia: { link_click: 3 },
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

interface Pagina {
  documento: Document;
  html: string;
  // O conteúdo da página, sem os scripts que levam os dados do React.
  texto: string;
}

async function abrirCampanha(
  nome = CAMPANHA_VENDAS,
  consulta = CONSULTA_SETEMBRO,
  credencial = massa.tokenA,
): Promise<Pagina> {
  const endereco = `${montarCaminho(massa.empresaA, "campanha", ids[nome])}?${consulta}`;
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

function lerDestaque(documento: Document): Record<string, string[]> {
  return lerCartoes(acharSecao(documento, TITULO_DESTAQUE));
}

// O objetivo e o status, pelo termo de cada um.
function lerSituacao(documento: Document): Record<string, string> {
  const secao = acharSecao(documento, TITULO_DESTAQUE);
  return Object.fromEntries(
    [...(secao?.querySelectorAll("dl > div") ?? [])].map((par) => [
      par.querySelector("dt")?.textContent ?? "",
      par.querySelector("dd")?.textContent ?? "",
    ]),
  );
}

function lerAnuncios(documento: Document): Element[] {
  return [
    ...documento.querySelectorAll('section[aria-labelledby="titulo-filhas"] a'),
  ];
}

describe("RF-31: o resultado principal e o KPI em destaque, conforme o catálogo", () => {
  test("a campanha de vendas mostra as compras e o custo por compra em destaque", async () => {
    const { documento } = await abrirCampanha();

    const destaque = lerDestaque(documento);

    expect(Object.keys(destaque)).toEqual(["Compras", "Custo por compra"]);
    expect(destaque["Compras"][0]).toBe("8");
    expect(destaque["Custo por compra"][0]).toBe(formatarMoeda(5, "BRL"));
  });

  test("a campanha de mensagens mostra as conversas iniciadas e o custo por conversa em destaque", async () => {
    const { documento } = await abrirCampanha(CAMPANHA_MENSAGENS);

    const destaque = lerDestaque(documento);

    expect(Object.keys(destaque)).toEqual([
      "Conversas iniciadas",
      "Custo por conversa",
    ]);
    expect(destaque["Conversas iniciadas"][0]).toBe("10");
    expect(destaque["Custo por conversa"][0]).toBe(formatarMoeda(2, "BRL"));
  });

  test("o destaque diz o objetivo e o status em linguagem de negócio (RF-37)", async () => {
    const vendas = await abrirCampanha();
    const mensagens = await abrirCampanha(CAMPANHA_MENSAGENS);

    expect(lerSituacao(vendas.documento)).toEqual({
      Objetivo: "Vendas",
      Status: "Ativa",
    });
    expect(lerSituacao(mensagens.documento)).toEqual({
      Objetivo: "Conversas",
      Status: "Pausada",
    });
  });

  test("a sobrescrita troca o destaque, e o apoio continua o da regra (ADR-0007)", async () => {
    const campanhaId = ids[CAMPANHA_VENDAS];

    try {
      await cliente.query(
        `INSERT INTO normalizado.sobrescrita_resultado_campanha
           (empresa_id, campanha_id, metrica_resultado, metrica_kpi)
         VALUES ($1, $2, 'conversas_iniciadas', 'custo_conversa')`,
        [massa.empresaA, campanhaId],
      );
      const { documento } = await abrirCampanha();

      const destaque = lerDestaque(documento);

      expect(Object.keys(destaque)).toEqual([
        "Conversas iniciadas",
        "Custo por conversa",
      ]);
      expect(destaque["Conversas iniciadas"][0]).toBe("0");
      expect(destaque["Custo por conversa"][0]).toBe("—");
      expect(
        Object.keys(lerCartoes(acharSecao(documento, TITULO_REAL))),
      ).toEqual([
        "Investimento",
        "Valor das compras",
        "Retorno sobre o investimento",
        "Cliques no link",
      ]);
    } finally {
      await cliente.query(
        `DELETE FROM normalizado.sobrescrita_resultado_campanha
         WHERE empresa_id = $1 AND campanha_id = $2`,
        [massa.empresaA, campanhaId],
      );
    }
  });

  test("mudar o resultado e o KPI da regra no catálogo muda o destaque, sem mudar componente", async () => {
    const atualizarRegra = async (resultado: string, kpi: string) => {
      await cliente.query(
        `UPDATE normalizado.resultado_objetivo
         SET metrica_resultado = $1, metrica_kpi = $2
         WHERE objetivo = 'OUTCOME_SALES' AND meta_otimizacao IS NULL`,
        [resultado, kpi],
      );
    };

    try {
      await atualizarRegra("cliques_link", "cpc");
      const { documento } = await abrirCampanha();

      expect(Object.keys(lerDestaque(documento))).toEqual([
        "Cliques no link",
        "Custo por clique",
      ]);
      expect(lerDestaque(documento)["Cliques no link"][0]).toBe("12");
      expect(
        Object.keys(lerCartoes(acharSecao(documento, TITULO_REAL))),
      ).not.toContain("Cliques no link");
    } finally {
      await atualizarRegra("compras", "custo_compra");
    }
  });

  test("a campanha sem resultado no catálogo não destaca o número de outra métrica (§7.2)", async () => {
    const { documento } = await abrirCampanha(CAMPANHA_DESCONHECIDA);
    const destaque = acharSecao(documento, TITULO_DESTAQUE);

    expect(destaque?.querySelectorAll("article")).toHaveLength(0);
    expect(destaque?.textContent).toContain(SEM_RESULTADO);
    expect(lerSituacao(documento)["Objetivo"]).toBe("Não classificado");
  });
});

describe("§3.1: métricas de apoio e série temporal", () => {
  test("o apoio é o investimento e as métricas da regra, na ordem do catálogo", async () => {
    const vendas = await abrirCampanha();
    const mensagens = await abrirCampanha(CAMPANHA_MENSAGENS);

    const apoioVendas = lerCartoes(acharSecao(vendas.documento, TITULO_REAL));
    const apoioMensagens = lerCartoes(
      acharSecao(mensagens.documento, TITULO_REAL),
    );

    expect(Object.keys(apoioVendas)).toEqual([
      "Investimento",
      "Valor das compras",
      "Retorno sobre o investimento",
      "Cliques no link",
    ]);
    expect(apoioVendas["Investimento"][0]).toBe(formatarMoeda(40, "BRL"));
    expect(apoioVendas["Cliques no link"][0]).toBe("12");
    expect(Object.keys(apoioMensagens)).toEqual([
      "Investimento",
      "Cliques no link",
      "Taxa de cliques",
      "Custo por mil impressões",
    ]);
  });

  test("a campanha sem resultado mostra só o apoio da regra própria, com o investimento uma vez", async () => {
    const { documento } = await abrirCampanha(CAMPANHA_DESCONHECIDA);

    const apoio = lerCartoes(acharSecao(documento, TITULO_REAL));

    expect(Object.keys(apoio)).toEqual([
      "Investimento",
      "Impressões",
      "Cliques no link",
    ]);
    expect(apoio["Cliques no link"][0]).toBe("3");
  });

  test("RF-25: as séries do destaque e do apoio têm um ponto por semana, e os períodos somam o total", async () => {
    const { documento } = await abrirCampanha();
    const destaque = acharSecao(documento, TITULO_DESTAQUE);
    const apoio = acharSecao(documento, TITULO_REAL);

    const compras = lerSerie(destaque, "Compras");
    const investimento = lerSerie(apoio, "Investimento");

    expect(compras.map(([periodo]) => periodo)).toEqual([
      "01/09/2026 a 06/09/2026",
      "07/09/2026 a 13/09/2026",
      "14/09/2026 a 20/09/2026",
      "21/09/2026 a 27/09/2026",
      "28/09/2026 a 30/09/2026",
    ]);
    expect(compras.map(([, valor]) => valor)).toEqual([
      "0",
      "4",
      "4",
      "0",
      "0",
    ]);
    expect(
      lerSerie(destaque, "Custo por compra").map(([, valor]) => valor),
    ).toEqual([
      "—",
      formatarMoeda(5, "BRL"),
      formatarMoeda(5, "BRL"),
      "—",
      "—",
    ]);
    expect(
      investimento.reduce((soma, [, valor]) => soma + lerValorMoeda(valor), 0),
    ).toBe(40);
  });

  test("RF-30: cada cartão e cada série do destaque e do apoio têm o rótulo de uma métrica do catálogo e a ajuda com a explicação dela", async () => {
    const { documento } = await abrirCampanha();
    const explicacoes = await lerExplicacoesCatalogo(cliente);

    const metricas = listarMetricasExibidas(documento);

    // Duas métricas no destaque e quatro no apoio, cada uma com o cartão e a
    // série.
    expect(metricas).toHaveLength(12);
    for (const { rotulo, ajuda } of metricas) {
      expect(explicacoes.has(rotulo), rotulo).toBe(true);
      expect(ajuda, rotulo).toEqual({
        controle: `O que é isso? (${rotulo})`,
        explicacao: explicacoes.get(rotulo),
      });
    }
  });
});

describe("§3.1 e RF-23: lista de anúncios", () => {
  test("a campanha lista só os anúncios dela com entrega no período, com links que mantêm a seleção", async () => {
    const { documento } = await abrirCampanha();

    expect(
      lerAnuncios(documento).map((ligacao) => [
        ligacao.textContent,
        ligacao.getAttribute("href"),
      ]),
    ).toEqual(
      ["Anúncio Exemplo Vendas Dois", "Anúncio Exemplo Vendas Um"].map(
        (nome) => [
          nome,
          `${montarCaminho(massa.empresaA, "anuncio", ids[nome])}?${CONSULTA_SETEMBRO}`,
        ],
      ),
    );
  });
});

describe("visão da campanha", () => {
  test("sem dados no intervalo, a página responde e diz isso, sem destaque", async () => {
    const { documento, texto } = await abrirCampanha(
      CAMPANHA_VENDAS,
      CONSULTA_SEM_DADOS,
    );

    expect(texto).toContain("Nenhum dado no período.");
    expect(texto).toContain("Nenhum anúncio com entrega no período.");
    expect(acharSecao(documento, TITULO_DESTAQUE)).toBeUndefined();
    expect(documento.querySelectorAll("article")).toHaveLength(0);
  });

  test("RNF-02 e RF-37: nenhum valor de enum nem tipo de ação da API aparece na tela nem nos dados que vão ao navegador", async () => {
    const { texto, html } = await abrirCampanha(CAMPANHA_MENSAGENS);

    expect(texto).toContain("Pausada");
    for (const termo of TERMOS_API) {
      expect(texto).not.toMatch(new RegExp(`\\b${termo}`));
      expect(html).not.toMatch(new RegExp(`\\b${termo}`));
    }
  });

  test("o operador vê a campanha de qualquer empresa", async () => {
    const { documento } = await abrirCampanha(
      CAMPANHA_VENDAS,
      CONSULTA_SETEMBRO,
      massa.tokenOperador,
    );

    expect(Object.keys(lerDestaque(documento))).toEqual([
      "Compras",
      "Custo por compra",
    ]);
  });

  test("RNF-14: a credencial de outra empresa recebe 404, sem revelar a campanha", async () => {
    const resposta = await requisitar(
      `${montarCaminho(massa.empresaA, "campanha", ids[CAMPANHA_VENDAS])}?${CONSULTA_SETEMBRO}`,
      { credencial: massa.tokenB },
    );

    expect(resposta.status).toBe(404);
    expect(await resposta.text()).not.toContain(CAMPANHA_VENDAS);
  });

  test("a página não leva o token nos dados que vão ao navegador", async () => {
    const { html } = await abrirCampanha();

    expect(html).not.toContain(massa.tokenA);
  });
});
