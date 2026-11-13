import type { Granularidade } from "@/lib/periodo";

const LOCALIDADE = "pt-BR";

export const VALOR_AUSENTE = "—";

// A métrica que a leitura não traz, diferente do valor ausente, que é a razão
// sem denominador (docs/REQUIREMENTS.md §3.3 e §7.1).
export const ROTULO_NAO_DISPONIVEL = "Não disponível";

// Os valores do CHECK de normalizado.metrica.unidade.
export type UnidadeMetrica = "moeda" | "quantidade" | "percentual" | "razao";

// Duas casas separam CTRs próximos, como 0,87% e 0,91%, que com uma casa
// ficariam iguais. O padrão do Intl é zero casas no percentual e três no número.
const MAXIMO_CASAS_DECIMAIS = 2;

const FORMATO_NUMERO = new Intl.NumberFormat(LOCALIDADE, {
  maximumFractionDigits: MAXIMO_CASAS_DECIMAIS,
});

const FORMATO_PERCENTUAL = new Intl.NumberFormat(LOCALIDADE, {
  style: "percent",
  maximumFractionDigits: MAXIMO_CASAS_DECIMAIS,
});

// O dia em AAAA-MM-DD é lido como meia-noite UTC. Exibi-lo também em UTC
// devolve o mesmo dia em qualquer fuso; no fuso local, UTC−3 recuaria um dia.
const FORMATO_DATA = new Intl.DateTimeFormat(LOCALIDADE, {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  timeZone: "UTC",
});

// O instante da carga sai com a sigla do fuso, porque a página pode somar
// contas em fusos diferentes, e o horário sem ela seria ambíguo.
const OPCOES_INSTANTE: Intl.DateTimeFormatOptions = {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZoneName: "short",
};

// O eixo do gráfico mostra o período sem o ano quando o dia importa, e a
// data inteira fica na dica e na tabela.
const FORMATO_DIA_MES = new Intl.DateTimeFormat(LOCALIDADE, {
  day: "2-digit",
  month: "2-digit",
  timeZone: "UTC",
});

const FORMATOS_EIXO: Record<Granularidade, Intl.DateTimeFormat> = {
  dia: FORMATO_DIA_MES,
  semana: FORMATO_DIA_MES,
  mes: new Intl.DateTimeFormat(LOCALIDADE, {
    month: "2-digit",
    year: "numeric",
    timeZone: "UTC",
  }),
  ano: new Intl.DateTimeFormat(LOCALIDADE, {
    year: "numeric",
    timeZone: "UTC",
  }),
};

const NOMES_MOEDA = new Intl.DisplayNames(LOCALIDADE, { type: "currency" });

type ValorNumerico = number | null | undefined;

// NaN e infinito vêm de divisão por zero, que o catálogo manda exibir como
// ausência (docs/REQUIREMENTS.md §7.1). Zero é valor e continua aparecendo.
function possuiValor(valor: ValorNumerico): valor is number {
  return Number.isFinite(valor);
}

// A moeda é obrigatória porque vem da conta, e as casas decimais vêm dela:
// o iene, por exemplo, não tem centavos.
export function formatarMoeda(valor: ValorNumerico, moeda: string): string {
  if (!possuiValor(valor)) {
    return VALOR_AUSENTE;
  }

  const formato = new Intl.NumberFormat(LOCALIDADE, {
    style: "currency",
    currency: moeda,
  });

  return formato.format(valor);
}

export function formatarNumero(valor: ValorNumerico): string {
  return possuiValor(valor) ? FORMATO_NUMERO.format(valor) : VALOR_AUSENTE;
}

// Recebe a fração, como o catálogo guarda o percentual (ADR-0009): 0.125 é 12,5%.
export function formatarPercentual(valor: ValorNumerico): string {
  return possuiValor(valor) ? FORMATO_PERCENTUAL.format(valor) : VALOR_AUSENTE;
}

// Recebe o dia em AAAA-MM-DD. Um instante precisa do fuso da conta, e esta
// função não serve para ele.
export function formatarData(data: string | null | undefined): string {
  return data ? FORMATO_DATA.format(new Date(data)) : VALOR_AUSENTE;
}

// O instante, como o da última carga, no fuso em que a página conta o dia.
export function formatarInstante(instante: Date, fuso: string): string {
  return new Intl.DateTimeFormat(LOCALIDADE, {
    ...OPCOES_INSTANTE,
    timeZone: fuso,
  }).format(instante);
}

// A unidade vem do catálogo, e a moeda, da conta (ADR-0007).
export function formatarMetrica(
  valor: ValorNumerico,
  unidade: UnidadeMetrica,
  moeda: string,
): string {
  switch (unidade) {
    case "moeda":
      return formatarMoeda(valor, moeda);
    case "percentual":
      return formatarPercentual(valor);
    default:
      return formatarNumero(valor);
  }
}

// O que uma leitura trouxe de uma métrica: indefinido é a métrica que ela não
// traz, como o alcance, e nulo é a razão sem denominador (ADR-0013).
export function formatarLeituraMetrica(
  valor: ValorNumerico,
  unidade: UnidadeMetrica,
  moeda: string,
): string {
  return valor === undefined
    ? ROTULO_NAO_DISPONIVEL
    : formatarMetrica(valor, unidade, moeda);
}

// O eixo do gráfico é aproximado: o valor exato fica na dica e na tabela.
export function formatarEixoMetrica(
  valor: number,
  unidade: UnidadeMetrica,
  moeda: string,
): string {
  if (unidade === "percentual") {
    return formatarPercentual(valor);
  }

  const formato = new Intl.NumberFormat(LOCALIDADE, {
    notation: "compact",
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
    ...(unidade === "moeda" && { style: "currency", currency: moeda }),
  });

  return formato.format(valor);
}

// O dia, ou os dois extremos: a semana e o mês vêm cortados no intervalo, e
// os extremos mostram quais dias entraram.
export function formatarPeriodo(inicio: string, fim: string): string {
  return inicio === fim
    ? formatarData(inicio)
    : `${formatarData(inicio)} a ${formatarData(fim)}`;
}

export function formatarRotuloEixo(
  inicio: string,
  granularidade: Granularidade,
): string {
  return FORMATOS_EIXO[granularidade].format(new Date(inicio));
}

export function formatarNomeMoeda(moeda: string): string {
  return NOMES_MOEDA.of(moeda) ?? moeda;
}
