import { randomBytes, randomUUID } from "node:crypto";
import type { Client } from "pg";
import { afterAll, beforeAll, describe, expect, test } from "vitest";

import {
  conectarBancoLocal,
  criarMassaAcesso,
  gerarCredencial,
  removerMassaAcesso,
  revogarCredencial,
  type MassaAcesso,
} from "./banco-local";
import { NOME_COOKIE_CREDENCIAL, requisitar } from "./http";

// Prova a entrada pelo link do ADR-0004: o token vira cookie, o navegador
// segue para uma URL sem ele, e toda rota sem acesso responde 404 (RF-45,
// RF-46).

// Os 32 bytes do token gerado pelo banco (ADR-0009 §4), num valor que não é
// de nenhuma credencial.
const BYTES_TOKEN = 32;

let cliente: Client;
let massa: MassaAcesso;

beforeAll(async () => {
  cliente = await conectarBancoLocal();
  massa = await criarMassaAcesso(cliente, "Entrada");
});

afterAll(async () => {
  await removerMassaAcesso(cliente, massa);
  await cliente.end();
});

function sortearTokenInexistente(): string {
  return randomBytes(BYTES_TOKEN).toString("base64url");
}

function lerAtributosCookie(resposta: Response): string[] {
  const cookies = resposta.headers.getSetCookie();
  expect(cookies).toHaveLength(1);
  return cookies[0].split(";").map((parte) => parte.trim());
}

describe("entrada pelo link", () => {
  test("o link da empresa troca o token por um cookie e redireciona para a visão dela", async () => {
    const resposta = await requisitar(`/acesso/${massa.tokenA}`);

    expect(resposta.status).toBe(303);
    expect(resposta.headers.get("location")).toBe(
      `/empresas/${massa.empresaA}`,
    );
    expect(resposta.headers.get("cache-control")).toContain("no-store");

    const [valor, ...atributos] = lerAtributosCookie(resposta);
    expect(valor).toBe(`${NOME_COOKIE_CREDENCIAL}=${massa.tokenA}`);
    const atributosNormalizados = atributos.map((atributo) =>
      atributo.toLowerCase(),
    );
    expect(atributosNormalizados).toEqual(
      expect.arrayContaining(["httponly", "secure", "samesite=lax", "path=/"]),
    );
    // Cookie de sessão: sem validade, some quando o navegador fecha.
    expect(
      atributosNormalizados.filter(
        (atributo) =>
          atributo.startsWith("max-age") || atributo.startsWith("expires"),
      ),
    ).toEqual([]);
  });

  test("o link do operador redireciona para a raiz", async () => {
    const resposta = await requisitar(`/acesso/${massa.tokenOperador}`);

    expect(resposta.status).toBe(303);
    expect(resposta.headers.get("location")).toBe("/");
    expect(lerAtributosCookie(resposta)[0]).toBe(
      `${NOME_COOKIE_CREDENCIAL}=${massa.tokenOperador}`,
    );
  });

  test("depois da entrada, nenhuma URL de navegação contém o token", async () => {
    const entrada = await requisitar(`/acesso/${massa.tokenA}`);
    const destino = entrada.headers.get("location") ?? "";
    expect(destino).not.toContain(massa.tokenA);

    const pagina = await requisitar(destino, { credencial: massa.tokenA });
    expect(pagina.status).toBe(200);
    expect(pagina.headers.get("location")).toBeNull();
    const html = await pagina.text();
    const urls = [...html.matchAll(/(?:href|src|action)="([^"]*)"/g)].map(
      (achado) => achado[1],
    );
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.filter((url) => url.includes(massa.tokenA))).toEqual([]);
    // Nem fora dos atributos: o payload do RSC embutido também não o leva.
    expect(html).not.toContain(massa.tokenA);

    // A navegação no cliente busca o payload do RSC, e não o HTML. Sem o
    // parâmetro _rsc, o Next.js primeiro redireciona para a URL com ele.
    const opcoesRsc = { credencial: massa.tokenA, cabecalhos: { rsc: "1" } };
    const redirecionamentoRsc = await requisitar(destino, opcoesRsc);
    expect(redirecionamentoRsc.status).toBe(307);
    const destinoRsc = redirecionamentoRsc.headers.get("location") ?? "";
    expect(
      new URL(destinoRsc, "http://painel.invalid").searchParams.has("_rsc"),
    ).toBe(true);
    expect(destinoRsc).not.toContain(massa.tokenA);

    const navegacao = await requisitar(destinoRsc, opcoesRsc);
    expect(navegacao.status).toBe(200);
    expect(navegacao.headers.get("content-type")).toContain("text/x-component");
    expect(await navegacao.text()).not.toContain(massa.tokenA);
  });

  test.each([
    ["que não é de nenhuma credencial", sortearTokenInexistente()],
    ["de uma credencial com um caractere a mais", "TOKEN_Ax"],
    ["com caractere fora do base64url", "abc.def"],
    ["com byte nulo", "abc%00def"],
  ])(
    "o link com token %s responde 404, sem cookie",
    async (_descricao, token) => {
      const caminho = token.replace("TOKEN_A", massa.tokenA);
      const resposta = await requisitar(`/acesso/${caminho}`);

      expect(resposta.status).toBe(404);
      expect(resposta.headers.getSetCookie()).toEqual([]);
    },
  );
});

describe("rotas sem acesso", () => {
  test.each([
    ["sem cookie", undefined],
    ["com cookie que não é de nenhuma credencial", sortearTokenInexistente()],
    ["com cookie com byte nulo", "abc%00def"],
  ])("%s, as rotas do painel respondem 404", async (_descricao, credencial) => {
    for (const caminho of ["/", `/empresas/${massa.empresaA}`]) {
      const resposta = await requisitar(caminho, { credencial });
      expect(resposta.status, caminho).toBe(404);
    }
  });
});

describe("RF-45: revogação do link", () => {
  test("na requisição seguinte à revogação, o link revogado e a sessão dele respondem 404", async () => {
    const token = await gerarCredencial(cliente, massa.empresaA);
    const visao = `/empresas/${massa.empresaA}`;
    expect((await requisitar(`/acesso/${token}`)).status).toBe(303);
    expect((await requisitar(visao, { credencial: token })).status).toBe(200);

    await revogarCredencial(cliente, massa.tokenOperador, token);

    expect((await requisitar(`/acesso/${token}`)).status).toBe(404);
    expect((await requisitar(visao, { credencial: token })).status).toBe(404);
    expect((await requisitar("/", { credencial: token })).status).toBe(404);
  });
});

describe("RF-46: isolamento entre empresas", () => {
  test("com o link da empresa A, a visão da empresa B responde 404, como a de uma empresa inexistente", async () => {
    const inexistente = randomUUID();
    const credencial = massa.tokenA;

    const visaoA = await requisitar(`/empresas/${massa.empresaA}`, {
      credencial,
    });
    const visaoB = await requisitar(`/empresas/${massa.empresaB}`, {
      credencial,
    });
    const visaoInexistente = await requisitar(`/empresas/${inexistente}`, {
      credencial,
    });

    expect(visaoA.status).toBe(200);
    expect(visaoB.status).toBe(404);
    expect(visaoInexistente.status).toBe(404);
    // A resposta não revela se a empresa B existe: tirado o ID do caminho,
    // ela é igual à de uma empresa que não existe.
    expect((await visaoB.text()).replaceAll(massa.empresaB, "ID")).toBe(
      (await visaoInexistente.text()).replaceAll(inexistente, "ID"),
    );
  });

  test("com o link da empresa B, a visão da empresa A responde 404", async () => {
    const credencial = massa.tokenB;

    expect(
      (await requisitar(`/empresas/${massa.empresaB}`, { credencial })).status,
    ).toBe(200);
    expect(
      (await requisitar(`/empresas/${massa.empresaA}`, { credencial })).status,
    ).toBe(404);
  });

  test("com o link da empresa A, um parâmetro que não é UUID responde 404", async () => {
    const resposta = await requisitar("/empresas/nao-e-uuid", {
      credencial: massa.tokenA,
    });

    expect(resposta.status).toBe(404);
  });

  test("a credencial do operador abre a visão de cada empresa", async () => {
    const credencial = massa.tokenOperador;

    for (const empresa of [massa.empresaA, massa.empresaB]) {
      const resposta = await requisitar(`/empresas/${empresa}`, {
        credencial,
      });
      expect(resposta.status, empresa).toBe(200);
    }
  });
});
