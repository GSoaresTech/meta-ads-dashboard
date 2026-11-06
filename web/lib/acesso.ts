import "server-only";

import { cookies } from "next/headers";
import { notFound } from "next/navigation";

import { consultar } from "@/lib/banco";

// O cookie guarda o token como chegou no link. O banco resolve a credencial
// a cada requisição, e por isso a revogação vale já na seguinte (ADR-0004;
// RF-45).
export const NOME_COOKIE_CREDENCIAL = "credencial";

// O token é base64url (ADR-0009 §4). Um valor com outro caractere não é de
// nenhuma credencial e nem vai ao banco: com o byte nulo, o Postgres recusaria
// o texto com erro, em vez de devolver zero linhas.
const FORMATO_TOKEN = /^[A-Za-z0-9_-]+$/;

export type EscopoAcesso = "empresa" | "operador";

export interface Acesso {
  escopo: EscopoAcesso;
  // Nulo só no escopo do operador, que não pertence a uma empresa.
  empresaId: string | null;
}

interface LinhaAcesso {
  escopo: EscopoAcesso;
  empresa_id: string | null;
}

// Devolve nulo para credencial ausente, inválida, revogada ou de empresa
// inativa, sem distinguir os casos, para que a rota responda 404 em todos.
export async function resolverAcesso(
  credencial: string | undefined,
): Promise<Acesso | null> {
  if (credencial === undefined || !FORMATO_TOKEN.test(credencial)) {
    return null;
  }

  const [linha] = await consultar<LinhaAcesso>(
    "SELECT escopo, empresa_id FROM analitico.resolver_acesso($1)",
    [credencial],
  );
  return linha ? { escopo: linha.escopo, empresaId: linha.empresa_id } : null;
}

// Para Server Components: sem acesso, a rota responde 404, sem revelar se a
// empresa existe (ADR-0004; RF-46).
export async function exigirAcesso(): Promise<Acesso> {
  const loja = await cookies();
  const acesso = await resolverAcesso(loja.get(NOME_COOKIE_CREDENCIAL)?.value);
  if (acesso === null) {
    notFound();
  }
  return acesso;
}

// O operador vê todas as empresas; o link, só a própria.
export function abrangeEmpresa(acesso: Acesso, empresaId: string): boolean {
  return acesso.escopo === "operador" || acesso.empresaId === empresaId;
}

// A URL para onde a entrada redireciona, sem o token.
export function obterDestinoDoAcesso(acesso: Acesso): string {
  return acesso.escopo === "empresa" ? `/empresas/${acesso.empresaId}` : "/";
}
