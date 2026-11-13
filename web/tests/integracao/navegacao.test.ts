// @vitest-environment jsdom
import { randomUUID } from "node:crypto";

import type { Client } from "pg";
import { afterAll, beforeAll, describe, expect, test } from "vitest";

import { montarCaminho } from "@/lib/navegacao";
import {
  ATALHOS,
  calcularIntervalo,
  GRANULARIDADES,
  obterHoje,
  type Intervalo,
} from "@/lib/periodo";

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

// Prova a navegação de Geral até anúncio com o seletor de período e de
// granularidade (RF-23 a RF-26). Os fusos têm 25 h de diferença, e assim o
// dia corrente de um nunca é o do outro: o teste vê qual fuso cada página
// usou.
const FUSO_ADIANTADO = "Pacific/Kiritimati";
const FUSO_ATRASADO = "Pacific/Pago_Pago";

let cliente: Client;
let massa: MassaAcesso;
let ids: IdsEntidades;
let idsB: IdsEntidades;
let hojeAdiantado: string;
let hojeAtrasado: string;

beforeAll(async () => {
  cliente = await conectarBancoLocal();
  massa = await criarMassaAcesso(cliente, "Navegação");

  const agora = new Date();
  hojeAdiantado = obterHoje(agora, [FUSO_ADIANTADO]);
  hojeAtrasado = obterHoje(agora, [FUSO_ATRASADO]);
  const ontemAdiantado = calcularIntervalo("ontem", hojeAdiantado).inicio;
  const fimMesPassado = calcularIntervalo("mes-passado", hojeAdiantado).fim;

  // O anúncio recente tem entrega em todo "este mês" e "últimos 7 dias" da
  // conta adiantada e no "hoje" do Geral; o antigo, só no mês passado.
  ids = await cadastrarEntidades(cliente, massa.empresaA, [
    {
      nome: "Conta Exemplo Adiantada",
      fusoHorario: FUSO_ADIANTADO,
      moeda: "BRL",
      campanhas: [
        {
          nome: "Campanha Exemplo Um",
          anuncios: [
            {
              nome: "Anúncio Exemplo Recente",
              dias: [hojeAdiantado, ontemAdiantado, hojeAtrasado],
            },
            { nome: "Anúncio Exemplo Antigo", dias: [fimMesPassado] },
          ],
        },
        {
          nome: "Campanha Exemplo Dois",
          anuncios: [
            { nome: "Anúncio Exemplo Outra Campanha", dias: [hojeAdiantado] },
          ],
        },
      ],
    },
    {
      nome: "Conta Exemplo Atrasada",
      fusoHorario: FUSO_ATRASADO,
      moeda: "USD",
      campanhas: [],
    },
  ]);
  idsB = await cadastrarEntidades(cliente, massa.empresaB, [
    {
      nome: "Conta Exemplo B",
      fusoHorario: "America/Sao_Paulo",
      moeda: "BRL",
      campanhas: [
        {
          nome: "Campanha Exemplo B",
          anuncios: [{ nome: "Anúncio Exemplo B", dias: [hojeAdiantado] }],
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

interface Ligacao {
  texto: string;
  href: string | null;
}

// O que a pessoa vê de uma página, lido pelos papéis e rótulos acessíveis.
interface Visao {
  trilha: Ligacao[];
  titulo: string;
  intervalo: string[];
  atalho: string | null;
  granularidade: string | null;
  filhas: Ligacao[];
}

function lerLigacao(elemento: Element): Ligacao {
  return {
    texto: elemento.textContent?.trim() ?? "",
    href: elemento.getAttribute("href"),
  };
}

function lerTexto(elemento: Element | null): string | null {
  return elemento?.textContent?.trim() ?? null;
}

function lerVisao(documento: Document): Visao {
  const trilha = documento.querySelectorAll(
    'nav[aria-label="Trilha de navegação"] li > *',
  );
  return {
    trilha: [...trilha].map(lerLigacao),
    titulo: lerTexto(documento.querySelector("h1")) ?? "",
    // O primeiro parágrafo do seletor é o intervalo escolhido, e o seguinte,
    // o período anterior com que ele se compara (RF-27).
    intervalo: [
      ...documento.querySelectorAll(
        'section[aria-label="Período e granularidade"] > p:first-child time',
      ),
    ].map((elemento) => elemento.getAttribute("datetime") ?? ""),
    atalho: lerTexto(
      documento.querySelector(
        'nav[aria-label="Atalhos de período"] a[aria-current="true"]',
      ),
    ),
    granularidade: lerTexto(
      documento.querySelector(
        'nav[aria-label="Granularidade"] a[aria-current="true"]',
      ),
    ),
    filhas: [
      ...documento.querySelectorAll(
        'section[aria-labelledby="titulo-filhas"] a',
      ),
    ].map(lerLigacao),
  };
}

async function abrirPagina(
  endereco: string,
  credencial: string = massa.tokenA,
): Promise<{ documento: Document; html: string }> {
  const resposta = await requisitar(endereco, { credencial });
  expect(resposta.status, endereco).toBe(200);
  const html = await resposta.text();
  return {
    documento: new DOMParser().parseFromString(html, "text/html"),
    html,
  };
}

async function abrirVisao(endereco: string): Promise<Visao> {
  return lerVisao((await abrirPagina(endereco)).documento);
}

function listarDias({ inicio, fim }: Intervalo): string[] {
  return [inicio, fim];
}

function caminhoDe(nivel: "conta" | "campanha" | "anuncio", nome: string) {
  return montarCaminho(massa.empresaA, nivel, ids[nome]);
}

describe("RF-23: descer de Geral até anúncio mantendo a seleção", () => {
  test("com 'este mês' selecionado, a campanha lista só os anúncios dela com entrega no mesmo mês", async () => {
    const consulta = "periodo=este-mes&granularidade=semana";
    const visao = await abrirVisao(
      `${caminhoDe("campanha", "Campanha Exemplo Um")}?${consulta}`,
    );

    expect(visao.filhas).toEqual([
      {
        texto: "Anúncio Exemplo Recente",
        href: `${caminhoDe("anuncio", "Anúncio Exemplo Recente")}?${consulta}`,
      },
    ]);
    expect(visao.intervalo).toEqual(
      listarDias(calcularIntervalo("este-mes", hojeAdiantado)),
    );
  });

  test("de Geral até anúncio, cada lista e a trilha levam o mesmo período e a mesma granularidade", async () => {
    const consulta = "periodo=este-mes&granularidade=mes";
    const seguir = (visao: Visao, nome: string) => {
      const filha = visao.filhas.find((ligacao) => ligacao.texto === nome);
      expect(filha, nome).toBeDefined();
      return filha?.href ?? "";
    };

    const geral = await abrirVisao(`/empresas/${massa.empresaA}?${consulta}`);
    const conta = await abrirVisao(seguir(geral, "Conta Exemplo Adiantada"));
    const campanha = await abrirVisao(seguir(conta, "Campanha Exemplo Um"));
    const anuncio = await abrirVisao(
      seguir(campanha, "Anúncio Exemplo Recente"),
    );

    expect(seguir(geral, "Conta Exemplo Adiantada")).toBe(
      `${caminhoDe("conta", "Conta Exemplo Adiantada")}?${consulta}`,
    );
    expect(anuncio.titulo).toBe("Anúncio Exemplo Recente");
    expect(anuncio.trilha).toEqual([
      { texto: "Geral", href: `/empresas/${massa.empresaA}?${consulta}` },
      {
        texto: "Conta Exemplo Adiantada",
        href: `${caminhoDe("conta", "Conta Exemplo Adiantada")}?${consulta}`,
      },
      {
        texto: "Campanha Exemplo Um",
        href: `${caminhoDe("campanha", "Campanha Exemplo Um")}?${consulta}`,
      },
      { texto: "Anúncio Exemplo Recente", href: null },
    ]);
    expect(anuncio.atalho).toBe("Este mês");
    expect(anuncio.granularidade).toBe("Mês");
    expect(anuncio.filhas).toEqual([]);
  });
});

describe("RF-24: nível, período e granularidade na URL, sem o token", () => {
  test("ao recarregar a página de uma campanha com 'últimos 7 dias', a mesma visão reaparece, e a URL não contém o token", async () => {
    const endereco = `${caminhoDe("campanha", "Campanha Exemplo Um")}?periodo=ultimos-7-dias&granularidade=dia`;

    const primeira = await abrirPagina(endereco);
    const recarga = await abrirPagina(endereco);

    const visao = lerVisao(primeira.documento);
    expect(lerVisao(recarga.documento)).toEqual(visao);
    expect(visao.atalho).toBe("Últimos 7 dias");
    expect(visao.intervalo).toEqual(
      listarDias(calcularIntervalo("ultimos-7-dias", hojeAdiantado)),
    );
    expect(visao.filhas.map((ligacao) => ligacao.texto)).toContain(
      "Anúncio Exemplo Recente",
    );

    const urls = [
      ...primeira.documento.querySelectorAll("[href], [action], [src]"),
    ].map(
      (elemento) =>
        elemento.getAttribute("href") ??
        elemento.getAttribute("action") ??
        elemento.getAttribute("src") ??
        "",
    );
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.filter((url) => url.includes(massa.tokenA))).toEqual([]);
    expect(primeira.html).not.toContain(massa.tokenA);
  });

  test("sem período na URL, a página abre nos últimos 30 dias, por dia, e cada atalho e granularidade leva à mesma página com a seleção trocada", async () => {
    const caminho = caminhoDe("conta", "Conta Exemplo Adiantada");
    const { documento } = await abrirPagina(caminho);
    const visao = lerVisao(documento);
    const lerEnderecos = (rotulo: string) =>
      [...documento.querySelectorAll(`nav[aria-label="${rotulo}"] a`)].map(
        (elemento) => elemento.getAttribute("href"),
      );

    expect(visao.atalho).toBe("Últimos 30 dias");
    expect(visao.granularidade).toBe("Dia");
    expect(visao.intervalo).toEqual(
      listarDias(calcularIntervalo("ultimos-30-dias", hojeAdiantado)),
    );
    expect(lerEnderecos("Atalhos de período")).toEqual(
      ATALHOS.map((atalho) => `${caminho}?periodo=${atalho}&granularidade=dia`),
    );
    expect(lerEnderecos("Granularidade")).toEqual(
      GRANULARIDADES.map(
        (granularidade) =>
          `${caminho}?periodo=ultimos-30-dias&granularidade=${granularidade}`,
      ),
    );
  });

  test("o intervalo livre vai para a URL pelo formulário, com a granularidade, e reaparece selecionado", async () => {
    const caminho = caminhoDe("conta", "Conta Exemplo Adiantada");
    const { documento } = await abrirPagina(
      `${caminho}?periodo=mes-passado&granularidade=semana`,
    );
    const formulario = documento.querySelector(
      'form[aria-label="Intervalo livre"]',
    );
    const campos = Object.fromEntries(
      [...(formulario?.querySelectorAll("input") ?? [])].map((campo) => [
        campo.name,
        campo.value,
      ]),
    );
    const mesPassado = calcularIntervalo("mes-passado", hojeAdiantado);

    expect(formulario?.getAttribute("method")).toBe("get");
    expect(formulario?.getAttribute("action")).toBe(caminho);
    expect(campos).toEqual({
      periodo: "intervalo",
      granularidade: "semana",
      inicio: mesPassado.inicio,
      fim: mesPassado.fim,
    });

    // O envio com GET monta a consulta com os campos do formulário.
    const envio = new URLSearchParams({
      ...campos,
      inicio: "2026-10-01",
      fim: "2026-10-10",
    });
    const visao = await abrirVisao(`${caminho}?${envio}`);
    expect(visao.intervalo).toEqual(["2026-10-01", "2026-10-10"]);
    expect(visao.atalho).toBeNull();
    expect(visao.granularidade).toBe("Semana");
  });
});

describe("seleção inválida na URL", () => {
  test.each([
    ["ano que o banco não aceita", "inicio=0000-01-01&fim=2026-01-01"],
    ["início depois do fim", "inicio=2026-10-10&fim=2026-10-01"],
    ["dia que não existe", "inicio=2026-02-30&fim=2026-03-01"],
    ["sem as datas", ""],
  ])(
    "com %s, a página volta ao período padrão, sem erro",
    async (_d, datas) => {
      const visao = await abrirVisao(
        `/empresas/${massa.empresaA}?periodo=intervalo&${datas}`,
      );

      expect(visao.atalho).toBe("Últimos 30 dias");
      expect(visao.intervalo).toEqual(
        listarDias(calcularIntervalo("ultimos-30-dias", hojeAtrasado)),
      );
    },
  );
});

describe("RF-25: granularidade da série", () => {
  // A série de investimento do Geral na moeda das contas com entrega, como a
  // visão a recebe da seleção (ADR-0009 §4).
  async function lerInvestimento(
    { inicio, fim }: Intervalo,
    granularidade: string,
  ): Promise<{ inicio: string; valor: number }[]> {
    const { rows } = await cliente.query<{ inicio: string; valor: string }>(
      `SELECT inicio_periodo::text AS inicio, valor::text AS valor
       FROM analitico.obter_desempenho($1, $2, 'geral', NULL, $3, $4, $5)
       WHERE nivel = 'geral' AND metrica = 'investimento' AND moeda = 'BRL'
       ORDER BY inicio_periodo`,
      [massa.tokenA, massa.empresaA, inicio, fim, granularidade],
    );
    return rows.map((linha) => ({
      inicio: linha.inicio,
      valor: Number(linha.valor),
    }));
  }

  test("com 'este ano' e 'mês', a série tem um ponto por mês, e a soma do investimento dos meses é igual ao total do ano", async () => {
    const visao = await abrirVisao(
      `/empresas/${massa.empresaA}?periodo=este-ano&granularidade=mes`,
    );
    const [inicio, fim] = visao.intervalo;
    const ano = fim.slice(0, 4);
    const meses = Array.from(
      { length: Number(fim.slice(5, 7)) },
      (_valor, indice) => `${ano}-${String(indice + 1).padStart(2, "0")}-01`,
    );

    expect(visao.granularidade).toBe("Mês");
    expect({ inicio, fim }).toEqual(
      calcularIntervalo("este-ano", hojeAtrasado),
    );

    const serie = await lerInvestimento({ inicio, fim }, "mes");
    const [total] = await lerInvestimento({ inicio, fim }, "periodo");
    expect(serie.map((ponto) => ponto.inicio)).toEqual(meses);
    expect(total.valor).toBeGreaterThan(0);
    expect(serie.reduce((soma, ponto) => soma + ponto.valor, 0)).toBe(
      total.valor,
    );
  });
});

describe("RF-26: atalhos no fuso da conta", () => {
  test("'hoje' é o dia corrente no fuso da conta de cada página, e o Geral usa o da conta mais atrasada", async () => {
    const consulta = "periodo=hoje&granularidade=dia";
    const lerIntervalo = async (caminho: string) =>
      (await abrirVisao(`${caminho}?${consulta}`)).intervalo;

    expect(hojeAdiantado).not.toBe(hojeAtrasado);
    expect(
      await lerIntervalo(caminhoDe("conta", "Conta Exemplo Adiantada")),
    ).toEqual([hojeAdiantado, hojeAdiantado]);
    expect(
      await lerIntervalo(caminhoDe("campanha", "Campanha Exemplo Um")),
    ).toEqual([hojeAdiantado, hojeAdiantado]);
    expect(
      await lerIntervalo(caminhoDe("anuncio", "Anúncio Exemplo Recente")),
    ).toEqual([hojeAdiantado, hojeAdiantado]);
    expect(
      await lerIntervalo(caminhoDe("conta", "Conta Exemplo Atrasada")),
    ).toEqual([hojeAtrasado, hojeAtrasado]);
    expect(await lerIntervalo(`/empresas/${massa.empresaA}`)).toEqual([
      hojeAtrasado,
      hojeAtrasado,
    ]);
  });
});

describe("isolamento entre empresas e níveis", () => {
  test("com o link da empresa A, as páginas das entidades da empresa B respondem 404, como as de uma entidade inexistente", async () => {
    const inexistente = randomUUID();
    const respostaInexistente = await requisitar(
      montarCaminho(massa.empresaA, "campanha", inexistente),
      { credencial: massa.tokenA },
    );
    expect(respostaInexistente.status).toBe(404);
    const corpoInexistente = (await respostaInexistente.text()).replaceAll(
      inexistente,
      "ID",
    );

    const casos: [string, string][] = [
      [
        montarCaminho(massa.empresaA, "conta", idsB["Conta Exemplo B"]),
        idsB["Conta Exemplo B"],
      ],
      [
        montarCaminho(massa.empresaA, "campanha", idsB["Campanha Exemplo B"]),
        idsB["Campanha Exemplo B"],
      ],
      [
        montarCaminho(massa.empresaA, "anuncio", idsB["Anúncio Exemplo B"]),
        idsB["Anúncio Exemplo B"],
      ],
    ];
    for (const [caminho, id] of casos) {
      const resposta = await requisitar(caminho, { credencial: massa.tokenA });
      expect(resposta.status, caminho).toBe(404);
      if (caminho.includes("/campanhas/")) {
        expect((await resposta.text()).replaceAll(id, "ID")).toBe(
          corpoInexistente,
        );
      }
    }
    const visaoB = await requisitar(
      montarCaminho(massa.empresaB, "campanha", idsB["Campanha Exemplo B"]),
      { credencial: massa.tokenA },
    );
    expect(visaoB.status).toBe(404);
  });

  test("uma entidade aberta no caminho de outro nível, ou um ID que não é UUID, responde 404", async () => {
    const campanha = ids["Campanha Exemplo Um"];
    const casos: [string, string][] = [
      [montarCaminho(massa.empresaA, "conta", campanha), massa.tokenA],
      [montarCaminho(massa.empresaA, "anuncio", campanha), massa.tokenA],
      [`/empresas/${massa.empresaA}/campanhas/nao-e-uuid`, massa.tokenA],
      [`/empresas/${massa.empresaA}/campanhas/nao-e-uuid`, massa.tokenOperador],
      ["/empresas/nao-e-uuid", massa.tokenOperador],
    ];

    for (const [caminho, credencial] of casos) {
      const resposta = await requisitar(caminho, { credencial });
      expect(resposta.status, caminho).toBe(404);
    }
  });

  test("o operador abre a campanha da empresa B, com a trilha dela", async () => {
    const { documento } = await abrirPagina(
      montarCaminho(massa.empresaB, "campanha", idsB["Campanha Exemplo B"]),
      massa.tokenOperador,
    );

    expect(lerVisao(documento).trilha.map((ligacao) => ligacao.texto)).toEqual([
      "Geral",
      "Conta Exemplo B",
      "Campanha Exemplo B",
    ]);
  });
});
