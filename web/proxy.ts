import { NextResponse, type NextRequest } from "next/server";

// O roteador do Next.js monta duas respostas sem os headers do next.config:
// o redirecionamento da barra no fim do caminho, que descarta os headers já
// aplicados, e o erro do caminho que ele não consegue decodificar. O Proxy as
// monta no lugar dele, e o Next.js aplica os headers às respostas do Proxy
// (RNF-18).
export function proxy(requisicao: NextRequest): NextResponse {
  const caminho = requisicao.nextUrl.pathname;

  if (!possuiCodificacaoValida(caminho)) {
    return new NextResponse("Bad Request", { status: 400 });
  }

  // O mesmo 308 que o Next.js faria, desligado no next.config. O destino sai
  // de um URL comum porque, com o redirecionamento desligado, o nextUrl
  // devolve a barra ao montar o endereço.
  if (caminho !== "/" && caminho.endsWith("/")) {
    const destino = new URL(requisicao.url);
    destino.pathname = caminho.replace(/\/+$/, "") || "/";
    return NextResponse.redirect(destino, 308);
  }

  return NextResponse.next();
}

function possuiCodificacaoValida(caminho: string): boolean {
  try {
    decodeURIComponent(caminho);
    return true;
  } catch (erro) {
    if (erro instanceof URIError) {
      return false;
    }
    throw erro;
  }
}

// Os arquivos do build ficam de fora para não invocar o Proxy a cada um que
// o navegador baixa. Neles, o Next.js já responde com os headers do
// next.config, com ou sem a barra no fim.
export const config = {
  matcher: ["/((?!_next/static/|_next/image).*)"],
};
