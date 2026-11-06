import { VisaoEntidade } from "@/components/VisaoEntidade";
import type { ParametrosUrl } from "@/lib/navegacao";

export default async function PaginaCampanha({
  params,
  searchParams,
}: Readonly<{
  params: Promise<{ empresaId: string; campanhaId: string }>;
  searchParams: Promise<ParametrosUrl>;
}>) {
  const { empresaId, campanhaId } = await params;

  return (
    <VisaoEntidade
      empresaId={empresaId}
      nivel="campanha"
      entidadeId={campanhaId}
      parametros={await searchParams}
    />
  );
}
