import "server-only";

import { consultar } from "@/lib/banco";
import {
  listarTiposResultado,
  montarCampanhas,
  type CampanhaListada,
} from "@/lib/campanhas";
import { listarCampanhas, obterCampanha } from "@/lib/entidades";
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
import { montarVisaoAnuncio } from "@/lib/visao-anuncio";
import {
  listarMetricasCampanha,
  montarVisaoCampanha,
  type VisaoCampanha,
} from "@/lib/visao-campanha";

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

export interface VisaoConta {
  resumos: ResumoMoeda[];
  campanhas: CampanhaListada[];
}

function carregarCatalogo(credencial: string): Promise<Metrica[]> {
  return consultar<Metrica & Record<string, unknown>>(
    `SELECT codigo, rotulo, explicacao, unidade,
       sentido_melhora AS "sentidoMelhora"
     FROM analitico.listar_metricas($1)`,
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

// O total de cada métrica no período anterior equivalente, só da entidade em
// foco, que é a comparada (RF-27; ADR-0021).
function carregarAnteriores(
  filtro: FiltroDesempenho,
  intervaloAnterior: Intervalo,
): Promise<LinhaDesempenhoEntidade[]> {
  return carregarDesempenho(
    { ...filtro, intervalo: intervaloAnterior },
    "periodo",
    [filtro.nivel],
  );
}

// O que a visão Geral mostra (REQUIREMENTS §3.1): os totais do intervalo e a
// série na granularidade escolhida, por moeda.
export async function carregarResumoGeral(
  credencial: string,
  empresaId: string,
  intervalo: Intervalo,
  intervaloAnterior: Intervalo,
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
  const [totais, serie, anteriores] = await Promise.all([
    carregarDesempenho(filtro, "periodo", ["geral"]),
    carregarDesempenho(filtro, granularidade, ["geral"]),
    carregarAnteriores(filtro, intervaloAnterior),
  ]);

  return montarResumos({ catalogo, resultados, totais, serie, anteriores });
}

// O que a visão da conta mostra (REQUIREMENTS §3.1): os totais e a série, como
// no Geral, e as campanhas com entrega. A leitura do intervalo inteiro serve
// às duas partes, porque a obter_desempenho traz o foco e as filhas na mesma
// chamada. O investimento vai sempre no filtro: é ele que marca a campanha com
// entrega, inclusive a que não tem resultado no catálogo.
export async function carregarVisaoConta(
  credencial: string,
  empresaId: string,
  contaId: string | null,
  intervalo: Intervalo,
  intervaloAnterior: Intervalo,
  granularidade: Granularidade,
): Promise<VisaoConta> {
  const [catalogo, linhasCampanhas] = await Promise.all([
    carregarCatalogo(credencial),
    listarCampanhas(credencial, empresaId, contaId),
  ]);

  const filtro: FiltroDesempenho = {
    credencial,
    empresaId,
    nivel: "conta",
    entidadeId: contaId,
    intervalo,
    metricas: [
      METRICA_INVESTIMENTO,
      ...linhasCampanhas
        .flatMap(({ metricaResultado, metricaKpi }) => [
          metricaResultado,
          metricaKpi,
        ])
        .filter((metrica) => metrica !== null),
    ],
  };
  const [periodo, serie, anteriores] = await Promise.all([
    carregarDesempenho(filtro, "periodo", ["conta", "campanha"]),
    carregarDesempenho(filtro, granularidade, ["conta"]),
    carregarAnteriores(filtro, intervaloAnterior),
  ]);

  const campanhas = montarCampanhas(
    linhasCampanhas,
    periodo.filter(({ nivel }) => nivel === "campanha"),
    catalogo,
  );
  return {
    campanhas,
    resumos: montarResumos({
      catalogo,
      resultados: listarTiposResultado(campanhas),
      totais: periodo.filter(({ nivel }) => nivel === "conta"),
      serie,
      anteriores,
    }),
  };
}

// O que a visão da campanha mostra (REQUIREMENTS §3.1): o resultado principal
// e o KPI em destaque e as métricas de apoio, com o total e a série de cada
// um. Quais são vem da obter_campanha, e só elas vão ao filtro. Nula para
// campanha que a credencial não lê.
export async function carregarVisaoCampanha(
  credencial: string,
  empresaId: string,
  campanhaId: string | null,
  intervalo: Intervalo,
  intervaloAnterior: Intervalo,
  granularidade: Granularidade,
): Promise<VisaoCampanha | null> {
  const [catalogo, campanha] = await Promise.all([
    carregarCatalogo(credencial),
    obterCampanha(credencial, empresaId, campanhaId),
  ]);
  if (campanha === undefined) {
    return null;
  }

  const filtro: FiltroDesempenho = {
    credencial,
    empresaId,
    nivel: "campanha",
    entidadeId: campanhaId,
    intervalo,
    metricas: listarMetricasCampanha(campanha),
  };
  const [totais, serie, anteriores] = await Promise.all([
    carregarDesempenho(filtro, "periodo", ["campanha"]),
    carregarDesempenho(filtro, granularidade, ["campanha"]),
    carregarAnteriores(filtro, intervaloAnterior),
  ]);

  return montarVisaoCampanha({
    catalogo,
    campanha,
    totais,
    serie,
    anteriores,
  });
}

// O que a visão do anúncio mostra (REQUIREMENTS §3.1): as métricas da campanha
// dele, com o total e a série de cada uma (ADR-0019). A campanha vem da trilha
// do anúncio. Nulo para campanha que a credencial não lê.
export async function carregarVisaoAnuncio(
  credencial: string,
  empresaId: string,
  anuncioId: string | null,
  campanhaId: string | null,
  intervalo: Intervalo,
  intervaloAnterior: Intervalo,
  granularidade: Granularidade,
): Promise<ResumoMoeda[] | null> {
  const [catalogo, campanha] = await Promise.all([
    carregarCatalogo(credencial),
    obterCampanha(credencial, empresaId, campanhaId),
  ]);
  if (campanha === undefined) {
    return null;
  }

  const filtro: FiltroDesempenho = {
    credencial,
    empresaId,
    nivel: "anuncio",
    entidadeId: anuncioId,
    intervalo,
    metricas: listarMetricasCampanha(campanha),
  };
  const [totais, serie, anteriores] = await Promise.all([
    carregarDesempenho(filtro, "periodo", ["anuncio"]),
    carregarDesempenho(filtro, granularidade, ["anuncio"]),
    carregarAnteriores(filtro, intervaloAnterior),
  ]);

  return montarVisaoAnuncio({
    catalogo,
    campanha,
    totais,
    serie,
    anteriores,
  });
}
