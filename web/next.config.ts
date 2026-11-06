import type { NextConfig } from "next";

// O link secreto não vaza pelo Referer nem pela indexação (RNF-18; ADR-0004).
// O roteador do Next.js aplica os headers do next.config antes dos
// redirecionamentos, do Proxy e das rotas, e eles valem para páginas, rotas,
// 404, erros e respostas do Proxy. O roteador monta duas respostas sem eles,
// de que o proxy.ts cuida, e uma terceira que nada alcança (R-43).
const CABECALHOS_SEGURANCA = [
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Robots-Tag", value: "noindex, nofollow" },
];

const configuracao: NextConfig = {
  // O redirecionamento da barra no fim do caminho sai do roteador sem os
  // headers acima, e por isso o proxy.ts o faz no lugar dele.
  skipTrailingSlashRedirect: true,
  async headers() {
    return [{ source: "/:path*", headers: CABECALHOS_SEGURANCA }];
  },
};

export default configuracao;
