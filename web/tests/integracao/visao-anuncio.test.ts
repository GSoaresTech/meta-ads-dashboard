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
} from "./leitura-pagina";

// Prova a visão do anúncio por HTTP: as métricas da campanha dele, com o
// total e a série, e a soma dos anúncios igual à campanha (REQUIREMENTS §3.1;
// RF-25, RF-30, RF-32; ADR-0019). As datas de setembro são fixas e já
// encerradas.
const FUSO = "America/Sao_Paulo";
const TITULO_DESTAQUE = "Resultado principal";
const TITULO_REAL = "Real brasileiro (BRL)";
const CONSULTA_SETEMBRO =
  "periodo=intervalo&inicio=2026-09-01&fim=2026-09-30&granularidade=semana";
const CONSULTA_SEM_DADOS =
  "periodo=intervalo&inicio=2020-01-01&fim=2020-01-31&granularidade=dia";

const CAMPANHA_VENDAS = "Campanha Exemplo Vendas";
const ANUNCIO_VENDAS = "Anúncio Exemplo Vendas Um";
const ANUNCIO_DESCONHECIDO = "Anúncio Exemplo Desconhecido";

// O resultado, o KPI e o apoio da regra de vendas do catálogo, depois do
// investimento.
const METRICAS_VENDAS = [
  "Investimento",
  "Compras",
  "Custo por compra",
  "Valor das compras",
  "Retorno sobre o investimento",
  "Cliques no link",
];

// Os valores de enum e os tipos de ação gravados nesta massa, que a tela
// nunca mostra (RNF-02; RF-37).
const TERMOS_API = [
  "OUTCOME_",
  "OFFSITE_CONVERSIONS",
  "ACTIVE",
  "omni_purchase",
  "link_click",
];

let cliente: Client;
let massa: MassaAcesso;
let ids: IdsEntidades;

beforeAll(async () => {
  cliente = await conectarBancoLocal();
  massa = await criarMassaAcesso(cliente, "Visão do Anúncio");

  ids = await cadastrarEntidades(cliente, massa.empresaA, [
    {
      nome: "Conta Exemplo Anúncios",
      fusoHorario: FUSO,
      moeda: "BRL",
      campanhas: [
        {
          nome: CAMPANHA_VENDAS,
          objetivo: "OUTCOME_SALES",
          metaOtimizacao: "OFFSITE_CONVERSIONS",
          anuncios: [
            {
              nome: ANUNCIO_VENDAS,
              dias: ["2026-09-07", "2026-09-08", "2026-09-14"],
              acoesPorDia: { omni_purchase: 2, link_click: 4 },
            },
            {
              nome: "Anúncio Exemplo Vendas Dois",
              dias: ["2026-09-14", "2026-09-29"],
              acoesPorDia: { omni_purchase: 1, link_click: 1 },
            },
            {
              // Sem entrega em setembro: fica fora da soma do mês.
              nome: "Anúncio Exemplo Vendas Antigo",
              dias: ["2026-08-10"],
              acoesPorDia: { omni_purchase: 9 },
            },
          ],
        },
        {
          nome: "Campanha Exemplo Desconhecida",
          objetivo: "OUTCOME_TESTE",
          anuncios: [
            {
              nome: ANUNCIO_DESCONHECIDO,
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

async function abrirPagina(
  endereco: string,
  credencial = massa.tokenA,
): Promise<Pagina> {
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

function abrirAnuncio(
  nome = ANUNCIO_VENDAS,
  consulta = CONSULTA_SETEMBRO,
  credencial = massa.tokenA,
): Promise<Pagina> {
  return abrirPagina(
    `${montarCaminho(massa.empresaA, "anuncio", ids[nome])}?${consulta}`,
    credencial,
  );
}

function lerMetricas(documento: Document): Record<string, string[]> {
  return lerCartoes(acharSecao(documento, TITULO_REAL));
}

describe("§3.1: métricas e série temporal do anúncio", () => {
  test("o anúncio mostra o investimento, o resultado, o KPI e o apoio da campanha dele", async () => {
    const { documento } = await abrirAnuncio();

    const metricas = lerMetricas(documento);

    expect(Object.keys(metricas)).toEqual(METRICAS_VENDAS);
    expect(metricas["Investimento"][0]).toBe(formatarMoeda(30, "BRL"));
    expect(metricas["Compras"][0]).toBe("6");
    expect(metricas["Custo por compra"][0]).toBe(formatarMoeda(5, "BRL"));
    expect(metricas["Cliques no link"][0]).toBe("12");
  });

  test("o anúncio não tem o destaque da campanha (ADR-0019)", async () => {
    const { documento } = await abrirAnuncio();

    expect(acharSecao(documento, TITULO_DESTAQUE)).toBeUndefined();
  });

  test("RF-25: as séries têm um ponto por semana, e os períodos somam o total", async () => {
    const { documento } = await abrirAnuncio();
    const secao = acharSecao(documento, TITULO_REAL);

    const compras = lerSerie(secao, "Compras");
    const investimento = lerSerie(secao, "Investimento");

    expect(compras).toEqual([
      ["01/09/2026 a 06/09/2026", "0"],
      ["07/09/2026 a 13/09/2026", "4"],
      ["14/09/2026 a 20/09/2026", "2"],
      ["21/09/2026 a 27/09/2026", "0"],
      ["28/09/2026 a 30/09/2026", "0"],
    ]);
    expect(
      investimento.reduce((soma, [, valor]) => soma + lerValorMoeda(valor), 0),
    ).toBe(30);
  });

  test("a sobrescrita da campanha troca o resultado e o KPI do anúncio (ADR-0007)", async () => {
    const campanhaId = ids[CAMPANHA_VENDAS];

    try {
      await cliente.query(
        `INSERT INTO normalizado.sobrescrita_resultado_campanha
           (empresa_id, campanha_id, metrica_resultado, metrica_kpi)
         VALUES ($1, $2, 'cliques_link', 'cpc')`,
        [massa.empresaA, campanhaId],
      );
      const { documento } = await abrirAnuncio();

      const metricas = lerMetricas(documento);

      expect(Object.keys(metricas)).toEqual([
        "Investimento",
        "Cliques no link",
        "Custo por clique",
        "Valor das compras",
        "Retorno sobre o investimento",
      ]);
      expect(metricas["Custo por clique"][0]).toBe(formatarMoeda(2.5, "BRL"));
    } finally {
      await cliente.query(
        `DELETE FROM normalizado.sobrescrita_resultado_campanha
         WHERE empresa_id = $1 AND campanha_id = $2`,
        [massa.empresaA, campanhaId],
      );
    }
  });

  test("o anúncio de campanha sem resultado no catálogo mostra só o investimento e o apoio (§7.2)", async () => {
    const { documento } = await abrirAnuncio(ANUNCIO_DESCONHECIDO);

    const metricas = lerMetricas(documento);

    expect(Object.keys(metricas)).toEqual([
      "Investimento",
      "Impressões",
      "Cliques no link",
    ]);
    expect(metricas["Cliques no link"][0]).toBe("3");
  });

  test("RF-30: cada cartão tem o rótulo e a explicação de uma métrica do catálogo", async () => {
    const { documento } = await abrirAnuncio();
    const { rows } = await cliente.query<{
      rotulo: string;
      explicacao: string;
    }>("SELECT rotulo, explicacao FROM normalizado.metrica");
    const explicacoes = new Map(
      rows.map(({ rotulo, explicacao }) => [rotulo, explicacao]),
    );

    const cartoes = Object.entries(lerMetricas(documento));

    expect(cartoes).toHaveLength(METRICAS_VENDAS.length);
    for (const [rotulo, paragrafos] of cartoes) {
      expect(explicacoes.has(rotulo), rotulo).toBe(true);
      expect(paragrafos, rotulo).toContain(explicacoes.get(rotulo));
    }
  });
});

describe("RF-32: a soma dos anúncios é a campanha", () => {
  test("pelos links da campanha, o investimento, as compras e os cliques dos anúncios somam os da campanha", async () => {
    const campanha = await abrirPagina(
      `${montarCaminho(massa.empresaA, "campanha", ids[CAMPANHA_VENDAS])}?${CONSULTA_SETEMBRO}`,
    );
    const enderecos = [
      ...campanha.documento.querySelectorAll(
        'section[aria-labelledby="titulo-filhas"] a',
      ),
    ].map((ligacao) => ligacao.getAttribute("href") ?? "");
    const anuncios = await Promise.all(
      enderecos.map((endereco) => abrirPagina(endereco)),
    );
    const apoioCampanha = lerMetricas(campanha.documento);
    const destaqueCampanha = lerCartoes(
      acharSecao(campanha.documento, TITULO_DESTAQUE),
    );
    const somar = (rotulo: string, ler: (texto: string) => number) =>
      anuncios.reduce(
        (soma, { documento }) => soma + ler(lerMetricas(documento)[rotulo][0]),
        0,
      );

    expect(enderecos).toHaveLength(2);
    expect(somar("Investimento", lerValorMoeda)).toBe(
      lerValorMoeda(apoioCampanha["Investimento"][0]),
    );
    expect(somar("Investimento", lerValorMoeda)).toBe(50);
    expect(somar("Compras", Number)).toBe(
      Number(destaqueCampanha["Compras"][0]),
    );
    expect(somar("Compras", Number)).toBe(8);
    expect(somar("Cliques no link", Number)).toBe(
      Number(apoioCampanha["Cliques no link"][0]),
    );
  });
});

describe("visão do anúncio", () => {
  test("sem dados no intervalo, a página responde e diz isso, sem cartões", async () => {
    const { documento, texto } = await abrirAnuncio(
      ANUNCIO_VENDAS,
      CONSULTA_SEM_DADOS,
    );

    expect(texto).toContain("Nenhum dado no período.");
    expect(documento.querySelectorAll("article")).toHaveLength(0);
  });

  test("RNF-02 e RF-37: nenhum valor de enum nem tipo de ação da API aparece na tela nem nos dados que vão ao navegador", async () => {
    const { texto, html } = await abrirAnuncio();

    for (const termo of TERMOS_API) {
      expect(texto).not.toMatch(new RegExp(`\\b${termo}`));
      expect(html).not.toMatch(new RegExp(`\\b${termo}`));
    }
  });

  test("o operador vê o anúncio de qualquer empresa", async () => {
    const { documento } = await abrirAnuncio(
      ANUNCIO_VENDAS,
      CONSULTA_SETEMBRO,
      massa.tokenOperador,
    );

    expect(Object.keys(lerMetricas(documento))).toEqual(METRICAS_VENDAS);
  });

  test("RNF-14: a credencial de outra empresa recebe 404, sem revelar o anúncio", async () => {
    const resposta = await requisitar(
      `${montarCaminho(massa.empresaA, "anuncio", ids[ANUNCIO_VENDAS])}?${CONSULTA_SETEMBRO}`,
      { credencial: massa.tokenB },
    );

    expect(resposta.status).toBe(404);
    expect(await resposta.text()).not.toContain(ANUNCIO_VENDAS);
  });

  test("a página não leva o token nos dados que vão ao navegador", async () => {
    const { html } = await abrirAnuncio();

    expect(html).not.toContain(massa.tokenA);
  });
});
