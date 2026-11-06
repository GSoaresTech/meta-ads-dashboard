import { randomBytes } from "node:crypto";
import type { Client } from "pg";
import { afterAll, beforeAll, expect, test } from "vitest";

import {
  conectarBancoLocal,
  criarMassaAcesso,
  removerMassaAcesso,
  type MassaAcesso,
} from "./banco-local";
import { requisitar, type OpcoesRequisicao } from "./http";

// Prova o RNF-18: toda resposta do painel, inclusive redirecionamentos, 404 e
// erros, leva os dois cabeçalhos que impedem o vazamento do link pelo
// Referer e pela indexação (ADR-0004).
//
// Fica de fora o 308 com que o Next.js troca barras repetidas e invertidas
// por uma só, antes de qualquer configuração e do Proxy, e que nenhuma
// configuração alcança (R-43).

const CABECALHOS_SEGURANCA = {
  "referrer-policy": "no-referrer",
  "x-robots-tag": "noindex, nofollow",
};

// Os 32 bytes do token gerado pelo banco (ADR-0009 §4).
const BYTES_TOKEN = 32;

let cliente: Client;
let massa: MassaAcesso;
let arquivoEstatico: string;

beforeAll(async () => {
  cliente = await conectarBancoLocal();
  massa = await criarMassaAcesso(cliente, "Cabeçalhos");

  // Um JS do build, que a página referencia e o navegador baixa.
  const html = await (
    await requisitar("/", { credencial: massa.tokenOperador })
  ).text();
  const achado = html.match(/\/_next\/static\/[^"]+\.js/);
  if (achado === null) {
    throw new Error("a página não referencia nenhum arquivo estático");
  }
  arquivoEstatico = achado[0];
});

afterAll(async () => {
  await removerMassaAcesso(cliente, massa);
  await cliente.end();
});

interface Caso {
  descricao: string;
  status: number;
  // Lê a massa só na execução, depois do beforeAll.
  montar: () => [string, OpcoesRequisicao?];
}

const CASOS: Caso[] = [
  {
    descricao: "entrada pelo link",
    status: 303,
    montar: () => [`/acesso/${massa.tokenA}`],
  },
  {
    descricao: "entrada pelo link com HEAD",
    status: 303,
    montar: () => [`/acesso/${massa.tokenA}`, { metodo: "HEAD" }],
  },
  {
    descricao: "link com barra no fim",
    status: 308,
    montar: () => [`/acesso/${massa.tokenA}/`],
  },
  {
    descricao: "link que não é de nenhuma credencial",
    status: 404,
    montar: () => [`/acesso/${randomBytes(BYTES_TOKEN).toString("base64url")}`],
  },
  {
    descricao: "link com método não aceito",
    status: 405,
    montar: () => [`/acesso/${massa.tokenA}`, { metodo: "POST" }],
  },
  {
    descricao: "link com OPTIONS",
    status: 204,
    montar: () => [`/acesso/${massa.tokenA}`, { metodo: "OPTIONS" }],
  },
  {
    descricao: "página inicial com credencial",
    status: 200,
    montar: () => ["/", { credencial: massa.tokenOperador }],
  },
  {
    descricao: "página inicial sem credencial",
    status: 404,
    montar: () => ["/"],
  },
  {
    descricao: "visão da empresa",
    status: 200,
    montar: () => [`/empresas/${massa.empresaA}`, { credencial: massa.tokenA }],
  },
  {
    descricao: "visão de outra empresa",
    status: 404,
    montar: () => [`/empresas/${massa.empresaB}`, { credencial: massa.tokenA }],
  },
  {
    descricao: "navegação no cliente sem o parâmetro _rsc",
    status: 307,
    montar: () => [
      `/empresas/${massa.empresaA}`,
      { credencial: massa.tokenA, cabecalhos: { rsc: "1" } },
    ],
  },
  {
    descricao: "navegação no cliente",
    status: 200,
    montar: () => [
      `/empresas/${massa.empresaA}?_rsc`,
      { credencial: massa.tokenA, cabecalhos: { rsc: "1" } },
    ],
  },
  {
    descricao: "rota inexistente",
    status: 404,
    montar: () => ["/rota-inexistente"],
  },
  {
    descricao: "arquivo estático do build",
    status: 200,
    montar: () => [arquivoEstatico],
  },
  {
    descricao: "arquivo estático com barra no fim",
    status: 200,
    montar: () => [`${arquivoEstatico}/`],
  },
  {
    descricao: "arquivo estático inexistente",
    status: 404,
    montar: () => ["/_next/static/inexistente.js"],
  },
  {
    descricao: "parâmetro com codificação inválida",
    status: 400,
    montar: () => ["/acesso/%E0%A4%A"],
  },
  {
    descricao: "caminho com codificação inválida",
    status: 400,
    montar: () => ["/rota/%E0%A4%A"],
  },
  {
    descricao: "otimização de imagem de arquivo inexistente",
    status: 404,
    montar: () => ["/_next/image?url=%2Finexistente.png&w=64&q=75"],
  },
  {
    descricao: "entrada pelo link com o banco fora do ar",
    status: 500,
    montar: () => [`/acesso/${massa.tokenA}`, { semBanco: true }],
  },
  {
    descricao: "página com o banco fora do ar",
    status: 500,
    montar: () => ["/", { credencial: massa.tokenA, semBanco: true }],
  },
];

test.each(CASOS)(
  "$descricao: $status, com os cabeçalhos de segurança",
  async ({ status, montar }) => {
    const resposta = await requisitar(...montar());

    expect(resposta.status).toBe(status);
    expect({
      "referrer-policy": resposta.headers.get("referrer-policy"),
      "x-robots-tag": resposta.headers.get("x-robots-tag"),
    }).toEqual(CABECALHOS_SEGURANCA);
  },
);

test("o caminho com barra no fim redireciona para o mesmo caminho sem ela, com a consulta", async () => {
  const resposta = await requisitar(`/empresas/${massa.empresaA}/?periodo=mes`);

  expect(resposta.status).toBe(308);
  expect(resposta.headers.get("location")).toBe(
    `/empresas/${massa.empresaA}?periodo=mes`,
  );
});
