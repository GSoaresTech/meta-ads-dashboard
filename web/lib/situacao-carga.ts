import "server-only";

import { consultar } from "@/lib/banco";

interface LinhaSituacaoCarga {
  ultima_carga_em: Date | null;
}

// O instante da última carga bem-sucedida da empresa (RF-28), nulo se ela
// nunca teve uma. O timestamptz chega como Date, um instante, sem fuso.
export async function carregarUltimaCarga(
  credencial: string,
  empresaId: string,
): Promise<Date | null> {
  const [linha] = await consultar<LinhaSituacaoCarga>(
    `SELECT ultima_carga_em
     FROM analitico.obter_situacao_carga($1, $2)`,
    [credencial, empresaId],
  );
  return linha?.ultima_carga_em ?? null;
}
