import { expect, inject, test } from "vitest";

test("a página inicial exibe o título do painel", async () => {
  const resposta = await fetch(new URL("/", inject("urlPainel")));

  expect(resposta.status).toBe(200);
  expect(await resposta.text()).toContain("<h1>Painel de Meta Ads</h1>");
});
