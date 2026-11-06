import "server-only";

import { consultar } from "@/lib/banco";
import type { Granularidade, Intervalo } from "@/lib/periodo";
import {
  METRICA_INVESTIMENTO,
  montarResumos,
  type LinhaDesempenho,
  type LinhaResultado,
  type Metrica,
  type ResumoMoeda,
} from "@/lib/resumo-desempenho";

// O numeric chega como texto, para não perder casas, e a data vira texto na
// consulta: como Date, ela seria a meia-noite no fuso do servidor.
interface LinhaDesempenhoBanco extends Omit<LinhaDesempenho, "valor"> {
  valor: string | null;
}

interface FiltroDesempenho {
  credencial: string;
  empresaId: string;
  intervalo: Intervalo;
  metricas: string[];
}

function carregarCatalogo(credencial: string): Promise<Metrica[]> {
  return consultar<Metrica & Record<string, unknown>>(
    "SELECT codigo, rotulo, explicacao, unidade FROM analitico.listar_metricas($1)",
    [credencial],
  );
}

function carregarResultados(
  credencial: string,
  empresaId: string,
  { inicio, fim }: Intervalo,
): Promise<LinhaResultado[]> {
  return consultar<LinhaResultado & Record<string, unknown>>(
    "SELECT moeda, metrica FROM analitico.listar_resultados($1, $2, $3, $4)",
    [credencial, empresaId, inicio, fim],
  );
}

// Só as linhas da empresa, sem as das contas, e só as métricas da tela.
async function carregarDesempenhoGeral(
  { credencial, empresaId, intervalo, metricas }: FiltroDesempenho,
  granularidade: Granularidade | "periodo",
): Promise<LinhaDesempenho[]> {
  const linhas = await consultar<LinhaDesempenhoBanco>(
    `SELECT inicio_periodo::text AS inicio, fim_periodo::text AS fim, moeda, metrica, valor
     FROM analitico.obter_desempenho($1, $2, 'geral', NULL, $3, $4, $5)
     WHERE nivel = 'geral' AND metrica = ANY($6::text[])
     ORDER BY inicio_periodo`,
    [
      credencial,
      empresaId,
      intervalo.inicio,
      intervalo.fim,
      granularidade,
      metricas,
    ],
  );
  return linhas.map((linha) => ({
    ...linha,
    valor: linha.valor === null ? null : Number(linha.valor),
  }));
}

// O que a visão Geral mostra (REQUIREMENTS §3.1): os totais do intervalo e a
// série na granularidade escolhida, por moeda.
export async function carregarResumoGeral(
  credencial: string,
  empresaId: string,
  intervalo: Intervalo,
  granularidade: Granularidade,
): Promise<ResumoMoeda[]> {
  const [catalogo, resultados] = await Promise.all([
    carregarCatalogo(credencial),
    carregarResultados(credencial, empresaId, intervalo),
  ]);

  const filtro: FiltroDesempenho = {
    credencial,
    empresaId,
    intervalo,
    metricas: [
      METRICA_INVESTIMENTO,
      ...resultados.map(({ metrica }) => metrica),
    ],
  };
  const [totais, serie] = await Promise.all([
    carregarDesempenhoGeral(filtro, "periodo"),
    carregarDesempenhoGeral(filtro, granularidade),
  ]);

  return montarResumos({ catalogo, resultados, totais, serie });
}
