import { notFound } from "next/navigation";

import { abrangeEmpresa, exigirAcesso } from "@/lib/acesso";

export default async function PaginaEmpresa({
  params,
}: Readonly<{ params: Promise<{ empresaId: string }> }>) {
  const { empresaId } = await params;
  const acesso = await exigirAcesso();
  if (!abrangeEmpresa(acesso, empresaId)) {
    notFound();
  }

  return (
    <main>
      <h1>Painel de Meta Ads</h1>
    </main>
  );
}
