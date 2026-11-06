import { VisaoEntidade } from "@/components/VisaoEntidade";
import type { ParametrosUrl } from "@/lib/navegacao";

export default async function PaginaEmpresa({
  params,
  searchParams,
}: Readonly<{
  params: Promise<{ empresaId: string }>;
  searchParams: Promise<ParametrosUrl>;
}>) {
  const { empresaId } = await params;

  return (
    <VisaoEntidade
      empresaId={empresaId}
      nivel="geral"
      entidadeId={null}
      parametros={await searchParams}
    />
  );
}
