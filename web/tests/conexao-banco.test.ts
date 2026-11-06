import { expect, test } from "vitest";

import { exigirTls } from "@/lib/conexao-banco";

const BANCO_REMOTO =
  "postgresql://painel_leitor:senha-ficticia@db.exemplo.invalid:5432/postgres";

test.each([
  ["sem sslmode", BANCO_REMOTO],
  ["com sslmode=disable", `${BANCO_REMOTO}?sslmode=disable`],
])("recusa o banco remoto %s, sem a URL na mensagem", (_descricao, url) => {
  let mensagem = "";
  try {
    exigirTls(url);
  } catch (erro) {
    mensagem = erro instanceof Error ? erro.message : String(erro);
  }

  expect(mensagem).toContain("sem TLS");
  expect(mensagem).not.toContain("senha-ficticia");
});

test.each([
  ["remoto com sslmode=verify-full", `${BANCO_REMOTO}?sslmode=verify-full`],
  [
    "remoto com a semântica do libpq",
    `${BANCO_REMOTO}?uselibpqcompat=true&sslmode=require`,
  ],
  [
    "local, sem TLS",
    "postgresql://painel_leitor:senha-ficticia@127.0.0.1:54322/postgres",
  ],
  [
    "local por nome, sem TLS",
    "postgresql://painel_leitor:senha-ficticia@localhost:54322/postgres",
  ],
])("aceita o banco %s", (_descricao, url) => {
  expect(() => exigirTls(url)).not.toThrow();
});
