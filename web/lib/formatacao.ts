const LOCALIDADE = "pt-BR";

const VALOR_AUSENTE = "—";

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
