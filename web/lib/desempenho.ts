import "server-only";

import { consultar } from "@/lib/banco";
import type { Nivel } from "@/lib/navegacao";
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
interface LinhaDesempenhoBanco extends Omit<LinhaDesempenhoEntidade, "valor"> {
  valor: string | null;
}

interface LinhaDesempenhoEntidade extends LinhaDesempenho {
  nivel: Nivel;
  entidadeId: string | null;
}

interface FiltroDesempenho {
  credencial: string;
  empresaId: string;
  nivel: Nivel;
  entidadeId: string | null;
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

// Só os níveis pedidos, entre a entidade em foco e as filhas dela, e só as
// métricas da tela.
async function carregarDesempenho(
  {
    credencial,
    empresaId,
    nivel,
    entidadeId,
    intervalo,
    metricas,
  }: FiltroDesempenho,
  granularidade: Granularidade | "periodo",
  niveis: Nivel[],
): Promise<LinhaDesempenhoEntidade[]> {
  const linhas = await consultar<LinhaDesempenhoBanco>(
    `SELECT nivel, entidade_id AS "entidadeId", inicio_periodo::text AS inicio,
       fim_periodo::text AS fim, moeda, metrica, valor
     FROM analitico.obter_desempenho($1, $2, $3, $4, $5, $6, $7)
     WHERE nivel = ANY($8::text[]) AND metrica = ANY($9::text[])
     ORDER BY inicio_periodo`,
    [
      credencial,
      empresaId,
      nivel,
      entidadeId,
      intervalo.inicio,
      intervalo.fim,
      granularidade,
      niveis,
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
    nivel: "geral",
    entidadeId: null,
    intervalo,
    metricas: [
      METRICA_INVESTIMENTO,
      ...resultados.map(({ metrica }) => metrica),
    ],
  };
  const [totais, serie] = await Promise.all([
    carregarDesempenho(filtro, "periodo", ["geral"]),
    carregarDesempenho(filtro, granularidade, ["geral"]),
  ]);

  return montarResumos({ catalogo, resultados, totais, serie });
}
