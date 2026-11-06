import { inject } from "vitest";

export const NOME_COOKIE_CREDENCIAL = "credencial";

export interface OpcoesRequisicao {
  credencial?: string;
  metodo?: string;
  cabecalhos?: Record<string, string>;
  // O servidor cujo banco recusa a conexão, para as respostas de erro.
  semBanco?: boolean;
}

// Redirecionamentos não são seguidos, para que o teste veja a resposta de
// cada passo, com o Location e o Set-Cookie dela.
export function requisitar(
  caminho: string,
  opcoes: OpcoesRequisicao = {},
): Promise<Response> {
  const cabecalhos = new Headers(opcoes.cabecalhos);
  if (opcoes.credencial !== undefined) {
    cabecalhos.set("cookie", `${NOME_COOKIE_CREDENCIAL}=${opcoes.credencial}`);
  }

  const servidor = inject(opcoes.semBanco ? "urlPainelSemBanco" : "urlPainel");
  return fetch(`${servidor}${caminho}`, {
    method: opcoes.metodo ?? "GET",
    headers: cabecalhos,
    redirect: "manual",
  });
}
