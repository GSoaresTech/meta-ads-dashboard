import { VisaoEntidade } from "@/components/VisaoEntidade";
import type { ParametrosUrl } from "@/lib/navegacao";

export default async function PaginaConta({
  params,
  searchParams,
}: Readonly<{
  params: Promise<{ empresaId: string; contaId: string }>;
  searchParams: Promise<ParametrosUrl>;
}>) {
  const { empresaId, contaId } = await params;

  return (
    <VisaoEntidade
      empresaId={empresaId}
      nivel="conta"
      entidadeId={contaId}
      parametros={await searchParams}
    />
  );
}
