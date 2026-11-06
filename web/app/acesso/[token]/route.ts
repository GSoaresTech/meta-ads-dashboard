import { notFound } from "next/navigation";
import { NextResponse } from "next/server";

import {
  NOME_COOKIE_CREDENCIAL,
  obterDestinoDoAcesso,
  resolverAcesso,
} from "@/lib/acesso";

// A entrada pelo link: troca o token por um cookie e redireciona para uma
// URL sem ele, para que o token não fique nas URLs de navegação (ADR-0004).
export async function GET(
  _requisicao: Request,
  { params }: { params: Promise<{ token: string }> },
): Promise<NextResponse> {
  const { token } = await params;
  const acesso = await resolverAcesso(token);
  if (acesso === null) {
    notFound();
  }

  // O 303 faz o navegador seguir com GET. O Location relativo não depende do
  // host que a requisição informa. O no-store impede que um cache guarde a
  // resposta, com o cookie dela, e a entregue a outra pessoa.
  const resposta = new NextResponse(null, {
    status: 303,
    headers: {
      Location: obterDestinoDoAcesso(acesso),
      "Cache-Control": "no-store",
    },
  });
  // Sem validade: um cookie de sessão, que some quando o navegador fecha.
  resposta.cookies.set(NOME_COOKIE_CREDENCIAL, token, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
  });
  return resposta;
}
