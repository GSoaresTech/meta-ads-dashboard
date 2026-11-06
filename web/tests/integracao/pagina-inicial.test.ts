import type { Client } from "pg";
import { afterAll, beforeAll, expect, test } from "vitest";

import {
  conectarBancoLocal,
  criarMassaAcesso,
  removerMassaAcesso,
  type MassaAcesso,
} from "./banco-local";
import { requisitar } from "./http";

let cliente: Client;
let massa: MassaAcesso;

beforeAll(async () => {
  cliente = await conectarBancoLocal();
  massa = await criarMassaAcesso(cliente, "Inicial");
});

afterAll(async () => {
  await removerMassaAcesso(cliente, massa);
  await cliente.end();
});

test("com a credencial do operador, a página inicial exibe o título do painel", async () => {
  const resposta = await requisitar("/", { credencial: massa.tokenOperador });

  expect(resposta.status).toBe(200);
  expect(await resposta.text()).toContain("<h1>Painel de Meta Ads</h1>");
});

test("sem credencial, a página inicial responde 404", async () => {
  const resposta = await requisitar("/");

  expect(resposta.status).toBe(404);
});
