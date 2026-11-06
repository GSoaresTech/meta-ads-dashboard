import type { Metadata } from "next";
import { Inter, Inter_Tight } from "next/font/google";
import type { ReactNode } from "react";

import "./tokens.css";
import "./estilos-globais.css";

// O next/font baixa as fontes no build e as serve do próprio painel, sem
// requisição ao Google no navegador (ADR-0015).
const fonteTexto = Inter({ subsets: ["latin"], variable: "--fonte-inter" });
const fonteTitulo = Inter_Tight({
  subsets: ["latin"],
  weight: "400",
  variable: "--fonte-inter-tight",
});

export const metadata: Metadata = {
  title: "Painel de Meta Ads",
};

export default function LayoutRaiz({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html
      lang="pt-BR"
      className={`${fonteTexto.variable} ${fonteTitulo.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
