import { VisaoEntidade } from "@/components/VisaoEntidade";
import type { ParametrosUrl } from "@/lib/navegacao";

export default async function PaginaAnuncio({
  params,
  searchParams,
}: Readonly<{
  params: Promise<{ empresaId: string; anuncioId: string }>;
  searchParams: Promise<ParametrosUrl>;
}>) {
  const { empresaId, anuncioId } = await params;

  return (
    <VisaoEntidade
      empresaId={empresaId}
      nivel="anuncio"
      entidadeId={anuncioId}
      parametros={await searchParams}
    />
  );
}
