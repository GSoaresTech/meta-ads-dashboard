import {
  ATALHOS,
  calcularIntervalo,
  GRANULARIDADES,
  lerIntervalo,
  type Atalho,
  type Granularidade,
  type Intervalo,
} from "@/lib/periodo";

// O estado da navegação: o nível e a entidade vão no caminho, e o período e
// a granularidade, na consulta. A URL nunca leva o token, que fica no cookie
// (RF-24; ADR-0004).

export type Nivel = "geral" | "conta" | "campanha" | "anuncio";

export type NivelFilho = Exclude<Nivel, "geral">;

// O nome é nulo entre o cadastro e a primeira extração (ADR-0009 §2).
export interface Entidade {
  nivel: Nivel;
  entidadeId: string | null;
  nome: string | null;
}

// Um nível da trilha, com os fusos das contas que ele abrange.
export interface NivelTrilha extends Entidade {
  fusosHorarios: string[];
}

export interface EntidadeFilha extends Entidade {
  entidadeId: string;
}

export const ROTULOS_NIVEL: Record<Nivel, string> = {
  geral: "Geral",
  conta: "Conta",
  campanha: "Campanha",
  anuncio: "Anúncio",
};

// O anúncio é o nível mais detalhado (REQUIREMENTS §3.1).
export const NIVEIS_FILHOS: Record<Nivel, NivelFilho | null> = {
  geral: "conta",
  conta: "campanha",
  campanha: "anuncio",
  anuncio: null,
};

export interface Selecao {
  // O atalho é recalculado a cada visita, e o intervalo livre fica fixo.
  periodo: Atalho | Intervalo;
  granularidade: Granularidade;
}

// REQUIREMENTS §3.2.
export const SELECAO_PADRAO: Selecao = {
  periodo: "ultimos-30-dias",
  granularidade: "dia",
};

// Os nomes dos parâmetros da consulta, que o formulário do intervalo livre
// também usa.
export const PARAMETROS = {
  periodo: "periodo",
  inicio: "inicio",
  fim: "fim",
  granularidade: "granularidade",
} as const;

export const PERIODO_INTERVALO = "intervalo";

// Os searchParams do Next.js: a chave repetida chega como lista.
export type ParametrosUrl = Record<string, string | string[] | undefined>;

const SEGMENTOS_NIVEL: Record<NivelFilho, string> = {
  conta: "contas",
  campanha: "campanhas",
  anuncio: "anuncios",
};

function pertence<Valor extends string>(
  valores: readonly Valor[],
  valor: unknown,
): valor is Valor {
  return (
    typeof valor === "string" && (valores as readonly string[]).includes(valor)
  );
}

function lerPeriodo(parametros: ParametrosUrl): Atalho | Intervalo {
  const periodo = parametros[PARAMETROS.periodo];
  if (periodo === PERIODO_INTERVALO) {
    return (
      lerIntervalo(parametros[PARAMETROS.inicio], parametros[PARAMETROS.fim]) ??
      SELECAO_PADRAO.periodo
    );
  }
  return pertence(ATALHOS, periodo) ? periodo : SELECAO_PADRAO.periodo;
}

// O valor que não é de nenhuma escolha volta ao padrão, sem erro, como um
// endereço antigo ou editado à mão.
export function lerSelecao(parametros: ParametrosUrl): Selecao {
  const granularidade = parametros[PARAMETROS.granularidade];
  return {
    periodo: lerPeriodo(parametros),
    granularidade: pertence(GRANULARIDADES, granularidade)
      ? granularidade
      : SELECAO_PADRAO.granularidade,
  };
}

export function montarConsulta(selecao: Selecao): string {
  const consulta = new URLSearchParams();
  if (typeof selecao.periodo === "string") {
    consulta.set(PARAMETROS.periodo, selecao.periodo);
  } else {
    consulta.set(PARAMETROS.periodo, PERIODO_INTERVALO);
    consulta.set(PARAMETROS.inicio, selecao.periodo.inicio);
    consulta.set(PARAMETROS.fim, selecao.periodo.fim);
  }
  consulta.set(PARAMETROS.granularidade, selecao.granularidade);
  return consulta.toString();
}

// A entidade é nula só no geral, que é a própria empresa.
export function montarCaminho(
  empresaId: string,
  nivel: Nivel,
  entidadeId: string | null,
): string {
  const raiz = `/empresas/${empresaId}`;
  return nivel === "geral"
    ? raiz
    : `${raiz}/${SEGMENTOS_NIVEL[nivel]}/${entidadeId}`;
}

export function nomearEntidade({ nivel, nome }: Entidade): string {
  return nome ?? `${ROTULOS_NIVEL[nivel]} sem nome`;
}

export function montarEndereco(caminho: string, selecao: Selecao): string {
  return `${caminho}?${montarConsulta(selecao)}`;
}

export function resolverIntervalo(
  periodo: Selecao["periodo"],
  hoje: string,
): Intervalo {
  return typeof periodo === "string"
    ? calcularIntervalo(periodo, hoje)
    : periodo;
}
