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

// Prova a visão da conta por HTTP: os totais, a série e a lista de campanhas
// com o objetivo e o status em linguagem de negócio, o resultado principal e
// o custo por resultado (REQUIREMENTS §3.1; RF-23, RF-25, RF-37; ADR-0013). As
// datas de setembro são fixas e já encerradas.
const FUSO = "America/Sao_Paulo";
const TITULO_REAL = "Real brasileiro (BRL)";
const TITULO_DOLAR = "Dólar americano (USD)";
const CONSULTA_SETEMBRO =
  "periodo=intervalo&inicio=2026-09-01&fim=2026-09-30&granularidade=semana";
const CONSULTA_SEM_DADOS =
  "periodo=intervalo&inicio=2020-01-01&fim=2020-01-31&granularidade=dia";

const CONTA = "Conta Exemplo Principal";
const CAMPANHA_VENDAS = "Campanha Exemplo Vendas";

// Os valores de enum gravados nesta massa e os demais que a tela nunca mostra.
const ENUMS_API = [
  "OUTCOME_",
  "LINK_CLICKS",
  "ACTIVE",
  "PAUSED",
  "ARCHIVED",
  "DELETED",
];

let cliente: Client;
let massa: MassaAcesso;
let ids: IdsEntidades;

beforeAll(async () => {
  cliente = await conectarBancoLocal();
  massa = await criarMassaAcesso(cliente, "Visão da Conta");

  ids = await cadastrarEntidades(cliente, massa.empresaA, [
    {
      nome: CONTA,
      fusoHorario: FUSO,
      moeda: "BRL",
      campanhas: [
        {
          nome: CAMPANHA_VENDAS,
          objetivo: "OUTCOME_SALES",
          status: "ACTIVE",
          anuncios: [
            {
              nome: "Anúncio Exemplo Vendas",
              dias: ["2026-09-07", "2026-09-08", "2026-09-14"],
              // Os cliques não são o resultado desta campanha, mas entram no
              // total da conta (ADR-0013).
              acoesPorDia: { omni_purchase: 2, link_click: 1 },
            },
          ],
        },
        {
          // Objetivo legado, que passa pelo equivalente atual (§7.2).
          nome: "Campanha Exemplo Tráfego",
          objetivo: "LINK_CLICKS",
          status: "PAUSED",
          anuncios: [
            {
              nome: "Anúncio Exemplo Tráfego",
              dias: ["2026-09-07", "2026-09-14"],
              acoesPorDia: { link_click: 5 },
            },
          ],
        },
        {
          nome: "Campanha Exemplo Reconhecimento",
          objetivo: "OUTCOME_AWARENESS",
          status: "ARCHIVED",
          anuncios: [
            { nome: "Anúncio Exemplo Reconhecimento", dias: ["2026-09-08"] },
          ],
        },
        {
          nome: "Campanha Exemplo Desconhecida",
          objetivo: "OUTCOME_TESTE",
          status: "DELETED",
          anuncios: [
            { nome: "Anúncio Exemplo Desconhecido", dias: ["2026-09-08"] },
          ],
        },
        {
          nome: "Campanha Exemplo Sem Entrega",
          objetivo: "OUTCOME_ENGAGEMENT",
          anuncios: [{ nome: "Anúncio Exemplo Sem Entrega", dias: [] }],
        },
      ],
    },
    {
      // Na mesma moeda, com outro tipo de resultado: o Geral soma os dois, e
      // a conta mostra só o dela.
      nome: "Conta Exemplo Vizinha",
      fusoHorario: FUSO,
      moeda: "BRL",
      campanhas: [
        {
          nome: "Campanha Exemplo Vizinha",
          objetivo: "OUTCOME_LEADS",
          anuncios: [
            {
              nome: "Anúncio Exemplo Vizinho",
              dias: ["2026-09-07"],
              acoesPorDia: { lead: 3 },
            },
          ],
        },
      ],
    },
    {
      nome: "Conta Exemplo Dólar",
      fusoHorario: FUSO,
      moeda: "USD",
      campanhas: [
        {
          nome: "Campanha Exemplo Dólar",
          objetivo: "OUTCOME_LEADS",
          anuncios: [
            {
              nome: "Anúncio Exemplo Dólar",
              dias: ["2026-09-07"],
              acoesPorDia: { lead: 2 },
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

async function abrirConta(
  nome = CONTA,
  consulta = CONSULTA_SETEMBRO,
  credencial = massa.tokenA,
): Promise<Pagina> {
  const endereco = `${montarCaminho(massa.empresaA, "conta", ids[nome])}?${consulta}`;
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

function lerCampanhas(documento: Document): string[][] {
  const linhas = documento.querySelectorAll(
    'section[aria-labelledby="titulo-filhas"] tbody tr',
  );
  return [...linhas].map((linha) =>
    [...linha.children].map((celula) => celula.textContent ?? ""),
  );
}

describe("§3.1: totais da conta", () => {
  test("os cartões são o investimento e o resultado das campanhas da conta com entrega, com o total somado", async () => {
    const { documento } = await abrirConta();

    const cartoes = lerCartoes(acharSecao(documento, TITULO_REAL));

    expect(Object.keys(cartoes)).toEqual([
      "Investimento",
      "Cliques no link",
      "Compras",
      "Pessoas alcançadas",
    ]);
    expect(cartoes["Investimento"][0]).toBe(formatarMoeda(70, "BRL"));
    expect(cartoes["Compras"][0]).toBe("6");
    expect(cartoes["Cliques no link"][0]).toBe("13");
  });

  test("o total de um tipo soma todas as campanhas da conta, inclusive as de outro resultado principal (§3.3; ADR-0014)", async () => {
    const { documento } = await abrirConta();

    const cartoes = lerCartoes(acharSecao(documento, TITULO_REAL));
    const trafego = lerCampanhas(documento).find(
      ([nome]) => nome === "Campanha Exemplo Tráfego",
    );

    expect(trafego?.[3]).toBe("Cliques no link: 10");
    expect(cartoes["Cliques no link"][0]).toBe("13");
  });

  test("a sobrescrita troca o tipo de resultado, o resultado e o custo, mas não o objetivo (§3.3; ADR-0007)", async () => {
    const campanhaId = ids["Campanha Exemplo Tráfego"];

    try {
      await cliente.query(
        `INSERT INTO normalizado.sobrescrita_resultado_campanha
           (empresa_id, campanha_id, metrica_resultado, metrica_kpi)
         VALUES ($1, $2, 'conversas_iniciadas', 'custo_conversa')`,
        [massa.empresaA, campanhaId],
      );
      const { documento } = await abrirConta();

      const tipos = Object.keys(lerCartoes(acharSecao(documento, TITULO_REAL)));
      const trafego = lerCampanhas(documento).find(
        ([nome]) => nome === "Campanha Exemplo Tráfego",
      );

      expect(tipos).toContain("Conversas iniciadas");
      expect(tipos).not.toContain("Cliques no link");
      expect(trafego?.slice(1)).toEqual([
        "Tráfego",
        "Pausada",
        "Conversas iniciadas: 0",
        "Custo por conversa: —",
      ]);
    } finally {
      await cliente.query(
        `DELETE FROM normalizado.sobrescrita_resultado_campanha
         WHERE empresa_id = $1 AND campanha_id = $2`,
        [massa.empresaA, campanhaId],
      );
    }
  });

  test("o resultado de outra conta na mesma moeda não entra, e a campanha sem entrega não acrescenta tipo", async () => {
    const { documento } = await abrirConta();

    const tipos = Object.keys(lerCartoes(acharSecao(documento, TITULO_REAL)));

    expect(tipos).not.toContain("Cadastros");
    expect(tipos).not.toContain("Interações com a publicação");
  });

  test("o alcance aparece como não disponível, sem série (§3.3; ADR-0013)", async () => {
    const { documento } = await abrirConta();
    const secao = acharSecao(documento, TITULO_REAL);

    expect(lerCartoes(secao)["Pessoas alcançadas"][0]).toBe("Não disponível");
    expect(lerSerie(secao, "Pessoas alcançadas")).toEqual([]);
  });

  test("a conta em dólar mostra os valores nessa moeda, sem a seção em real", async () => {
    const { documento } = await abrirConta("Conta Exemplo Dólar");

    expect(acharSecao(documento, TITULO_REAL)).toBeUndefined();
    expect(
      lerCartoes(acharSecao(documento, TITULO_DOLAR))["Investimento"][0],
    ).toBe(formatarMoeda(10, "USD"));
  });

  test("cada cartão exibido tem o rótulo e a explicação de uma métrica do catálogo (RF-30)", async () => {
    const { documento } = await abrirConta();
    const { rows } = await cliente.query<{
      rotulo: string;
      explicacao: string;
    }>("SELECT rotulo, explicacao FROM normalizado.metrica");
    const explicacoes = new Map(
      rows.map(({ rotulo, explicacao }) => [rotulo, explicacao]),
    );

    const cartoes = Object.entries(
      lerCartoes(acharSecao(documento, TITULO_REAL)),
    );

    expect(cartoes.length).toBeGreaterThan(0);
    for (const [rotulo, paragrafos] of cartoes) {
      expect(explicacoes.has(rotulo), rotulo).toBe(true);
      expect(paragrafos, rotulo).toContain(explicacoes.get(rotulo));
    }
  });
});

describe("RF-25: a série segue a granularidade", () => {
  test("a série tem um ponto por semana, e os períodos somam o total da conta", async () => {
    const { documento } = await abrirConta();
    const secao = acharSecao(documento, TITULO_REAL);

    const pontos = lerSerie(secao, "Investimento");

    expect(pontos.map(([periodo]) => periodo)).toEqual([
      "01/09/2026 a 06/09/2026",
      "07/09/2026 a 13/09/2026",
      "14/09/2026 a 20/09/2026",
      "21/09/2026 a 27/09/2026",
      "28/09/2026 a 30/09/2026",
    ]);
    expect(
      pontos.reduce((soma, [, valor]) => soma + lerValorMoeda(valor), 0),
    ).toBe(70);
    expect(lerSerie(secao, "Compras").map(([, valor]) => valor)).toEqual([
      "0",
      "4",
      "2",
      "0",
      "0",
    ]);
  });
});

describe("§3.1 e RF-37: lista de campanhas", () => {
  test("cada campanha com entrega traz o objetivo e o status em linguagem de negócio, o resultado e o custo", async () => {
    const { documento } = await abrirConta();

    expect(lerCampanhas(documento)).toEqual([
      [
        "Campanha Exemplo Desconhecida",
        "Não classificado",
        "Excluída",
        "—",
        "—",
      ],
      [
        "Campanha Exemplo Reconhecimento",
        "Reconhecimento",
        "Arquivada",
        "Pessoas alcançadas: Não disponível",
        "Custo por mil pessoas alcançadas: Não disponível",
      ],
      [
        "Campanha Exemplo Tráfego",
        "Tráfego",
        "Pausada",
        "Cliques no link: 10",
        `Custo por clique: ${formatarMoeda(2, "BRL")}`,
      ],
      [
        CAMPANHA_VENDAS,
        "Vendas",
        "Ativa",
        "Compras: 6",
        `Custo por compra: ${formatarMoeda(5, "BRL")}`,
      ],
    ]);
  });

  test("o custo sai na moeda da conta", async () => {
    const { documento } = await abrirConta("Conta Exemplo Dólar");

    expect(lerCampanhas(documento)).toEqual([
      [
        "Campanha Exemplo Dólar",
        "Cadastros",
        "Ativa",
        "Cadastros: 2",
        `Custo por cadastro: ${formatarMoeda(5, "USD")}`,
      ],
    ]);
  });

  test("RF-23: o link de cada campanha mantém o período e a granularidade", async () => {
    const { documento } = await abrirConta();

    const ligacao = [
      ...documento.querySelectorAll(
        'section[aria-labelledby="titulo-filhas"] a',
      ),
    ].find((elemento) => elemento.textContent === CAMPANHA_VENDAS);

    expect(ligacao?.getAttribute("href")).toBe(
      `${montarCaminho(massa.empresaA, "campanha", ids[CAMPANHA_VENDAS])}?${CONSULTA_SETEMBRO}`,
    );
  });

  test("RF-37: nenhum valor de enum da API aparece na tela nem nos dados que vão ao navegador", async () => {
    const { texto, html } = await abrirConta();

    expect(texto).toContain("Pausada");
    for (const termo of ENUMS_API) {
      expect(texto).not.toMatch(new RegExp(`\\b${termo}`));
      expect(html).not.toMatch(new RegExp(`\\b${termo}`));
    }
  });

  test("mudar o nome do objetivo e o rótulo do status no catálogo muda a tela (ADR-0007)", async () => {
    const atualizarCatalogo = async (objetivo: string, status: string) => {
      await cliente.query(
        `UPDATE normalizado.resultado_objetivo SET nome_objetivo = $1
         WHERE objetivo = 'OUTCOME_SALES' AND meta_otimizacao IS NULL`,
        [objetivo],
      );
      await cliente.query(
        `UPDATE normalizado.rotulo_valor_api SET rotulo = $1
         WHERE dominio = 'status' AND valor = 'ACTIVE'`,
        [status],
      );
    };

    try {
      await atualizarCatalogo("Objetivo Teste", "Status Teste");
      const { documento } = await abrirConta();

      const vendas = lerCampanhas(documento).find(
        ([nome]) => nome === CAMPANHA_VENDAS,
      );

      expect(vendas?.slice(1, 3)).toEqual(["Objetivo Teste", "Status Teste"]);
    } finally {
      await atualizarCatalogo("Vendas", "Ativa");
    }
  });
});

describe("visão da conta", () => {
  test("sem dados no intervalo, a página responde e diz isso", async () => {
    const { documento, texto } = await abrirConta(CONTA, CONSULTA_SEM_DADOS);

    expect(texto).toContain("Nenhum dado no período.");
    expect(texto).toContain("Nenhuma campanha com entrega no período.");
    expect(documento.querySelectorAll("article")).toHaveLength(0);
    expect(documento.querySelector("table")).toBeNull();
  });

  test("a campanha de outra conta não aparece", async () => {
    const { texto } = await abrirConta();

    expect(texto).not.toContain("Campanha Exemplo Vizinha");
  });

  test("o operador vê a conta de qualquer empresa", async () => {
    const { documento } = await abrirConta(
      CONTA,
      CONSULTA_SETEMBRO,
      massa.tokenOperador,
    );

    expect(lerCampanhas(documento)).toHaveLength(4);
  });

  test("RNF-14: a credencial de outra empresa recebe 404, sem revelar a conta", async () => {
    const resposta = await requisitar(
      `${montarCaminho(massa.empresaA, "conta", ids[CONTA])}?${CONSULTA_SETEMBRO}`,
      { credencial: massa.tokenB },
    );

    expect(resposta.status).toBe(404);
    expect(await resposta.text()).not.toContain(CONTA);
  });

  test("a página não leva o token nos dados que vão ao navegador", async () => {
    const { html } = await abrirConta();

    expect(html).not.toContain(massa.tokenA);
  });
});
