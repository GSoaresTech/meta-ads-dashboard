import type { Client } from "pg";

// O que a tela nunca mostra (RNF-02): os nomes de campo da API, fixos aqui
// porque o catálogo guarda só os que viraram métrica, e os termos da API que
// o catálogo guarda, lidos dele para valer também para os que entrarem depois.
const CAMPOS_API = [
  "spend",
  "impressions",
  "reach",
  "frequency",
  "clicks",
  "inline_link_clicks",
  "cpc",
  "cpm",
  "ctr",
  "actions",
  "action_values",
  "cost_per_action_type",
  "results",
  "conversions",
  "objective",
  "optimization_goal",
  "effective_status",
  // O prefixo dos objetivos atuais, inclusive os que o catálogo não conhece.
  "OUTCOME_",
];

// Os tipos de ação, os valores de enum com rótulo e os objetivos e metas de
// otimização das regras, sem os nulos da métrica que não é de ação, da regra
// de "Não classificado" e das regras de qualquer meta. Os códigos de métrica
// de uma palavra só, como "compras", são palavras do texto, e os de sigla,
// como "ctr", já são campos.
const CONSULTA_TERMOS_CATALOGO = `
  SELECT termo FROM (
    SELECT tipo_acao AS termo FROM normalizado.metrica
    UNION SELECT codigo FROM normalizado.metrica WHERE codigo LIKE '%\\_%'
    UNION SELECT valor FROM normalizado.rotulo_valor_api
    UNION SELECT objetivo FROM normalizado.resultado_objetivo
    UNION SELECT meta_otimizacao FROM normalizado.resultado_objetivo
  ) AS termos
  WHERE termo IS NOT NULL`;

export async function listarTermosApi(cliente: Client): Promise<string[]> {
  const { rows } = await cliente.query<{ termo: string }>(
    CONSULTA_TERMOS_CATALOGO,
  );
  return [...CAMPOS_API, ...rows.map(({ termo }) => termo)];
}

function escaparExpressao(termo: string): string {
  return termo.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Os termos que aparecem no texto como palavra ou começo de palavra, para que
// a falha diga quais são.
export function acharTermosApi(texto: string, termos: string[]): string[] {
  return termos.filter((termo) =>
    new RegExp(`\\b${escaparExpressao(termo)}`).test(texto),
  );
}
