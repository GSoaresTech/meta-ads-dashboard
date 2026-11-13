// O eixo de tempo do painel (REQUIREMENTS §3.2): os atalhos de período, o
// intervalo livre e as granularidades. Os dias são civis, em AAAA-MM-DD e
// sem fuso, como as datas de métrica (CLAUDE.md §5). O relógio entra como
// parâmetro, para que os testes fixem a data (RF-26).

export const ATALHOS = [
  "hoje",
  "ontem",
  "ultimos-7-dias",
  "ultimos-30-dias",
  "este-mes",
  "mes-passado",
  "este-ano",
] as const;

export type Atalho = (typeof ATALHOS)[number];

// Os valores que analitico.obter_desempenho aceita, sem o total do
// intervalo, que não é escolha da tela (ADR-0009 §4; RF-25).
export const GRANULARIDADES = ["dia", "semana", "mes", "ano"] as const;

export type Granularidade = (typeof GRANULARIDADES)[number];

export interface Intervalo {
  inicio: string;
  fim: string;
}

// A conta ainda sem a primeira extração não tem fuso, e a rotina diária usa
// o dia em UTC para ela (ADR-0009 §5).
const FUSO_SEM_CONTA = "UTC";

const DIAS_ULTIMA_SEMANA = 7;
const DIAS_ULTIMO_MES = 30;
const MESES_ANO = 12;
const MILISSEGUNDOS_DIA = 24 * 60 * 60 * 1000;

// O ano 0000 existe no Date, mas o Postgres recusa o texto com erro, em vez de
// devolver zero linhas. Os anos de 0001 a 0999 ficam de fora também: o período
// anterior de um intervalo neles pode cair no ano 0000, e o Date.UTC lê os
// anos de 0 a 99 como 1900 a 1999 (RF-27).
const FORMATO_DIA = /^(?!0)\d{4}-\d{2}-\d{2}$/;

// O dia civil vira meia-noite UTC, em que somar dias e voltar ao início do
// mês não esbarram em horário de verão.
function lerDia(dia: string): Date {
  return new Date(`${dia}T00:00:00Z`);
}

function escreverDia(data: Date): string {
  return data.toISOString().slice(0, 10);
}

function somarDias(data: Date, dias: number): Date {
  const resultado = new Date(data);
  resultado.setUTCDate(resultado.getUTCDate() + dias);
  return resultado;
}

function iniciarMes(data: Date): Date {
  return new Date(Date.UTC(data.getUTCFullYear(), data.getUTCMonth(), 1));
}

function iniciarAno(data: Date): Date {
  return new Date(Date.UTC(data.getUTCFullYear(), 0, 1));
}

// O dia zero de um mês é o último dia do mês anterior.
function encerrarMes(data: Date): Date {
  return new Date(Date.UTC(data.getUTCFullYear(), data.getUTCMonth() + 1, 0));
}

// O mesmo dia, alguns meses antes, sem passar do fim do mês de chegada: 31 de
// março, um mês antes, é 28 de fevereiro, e não 3 de março.
function recuarMeses(data: Date, meses: number): Date {
  const mesChegada = new Date(
    Date.UTC(data.getUTCFullYear(), data.getUTCMonth() - meses, 1),
  );
  const dia = Math.min(data.getUTCDate(), encerrarMes(mesChegada).getUTCDate());
  return new Date(
    Date.UTC(mesChegada.getUTCFullYear(), mesChegada.getUTCMonth(), dia),
  );
}

function contarDias(inicio: Date, fim: Date): number {
  return Math.round((fim.getTime() - inicio.getTime()) / MILISSEGUNDOS_DIA) + 1;
}

function contarMeses(inicio: Date, fim: Date): number {
  return (
    (fim.getUTCFullYear() - inicio.getUTCFullYear()) * MESES_ANO +
    fim.getUTCMonth() -
    inicio.getUTCMonth() +
    1
  );
}

function cobreMesesInteiros(inicio: Date, fim: Date): boolean {
  return (
    inicio.getUTCDate() === 1 && fim.getTime() === encerrarMes(fim).getTime()
  );
}

// As partes numéricas, e não o texto formatado, para que o resultado não
// dependa do padrão de data de uma localidade. Não é formatação para a tela.
function obterDiaNoFuso(agora: Date, fuso: string): string {
  const partes = new Intl.DateTimeFormat("en-US", {
    timeZone: fuso,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(agora);
  const lerParte = (tipo: Intl.DateTimeFormatPartTypes) =>
    partes.find((parte) => parte.type === tipo)?.value;
  return `${lerParte("year")}-${lerParte("month")}-${lerParte("day")}`;
}

// O fuso do dia corrente (RF-26): o da conta ou, com contas em fusos
// diferentes, o da mais atrasada, para que ontem já esteja encerrado em todas
// (REQUIREMENTS §3.3). Em AAAA-MM-DD, a ordem do texto é a das datas.
export function obterFusoReferencia(
  agora: Date,
  fusosHorarios: readonly string[],
): string {
  const fusos = fusosHorarios.length > 0 ? fusosHorarios : [FUSO_SEM_CONTA];
  return fusos.reduce((maisAtrasado, fuso) =>
    obterDiaNoFuso(agora, fuso) < obterDiaNoFuso(agora, maisAtrasado)
      ? fuso
      : maisAtrasado,
  );
}

export function obterHoje(
  agora: Date,
  fusosHorarios: readonly string[],
): string {
  return obterDiaNoFuso(agora, obterFusoReferencia(agora, fusosHorarios));
}

// Os últimos 7 e 30 dias terminam ontem, sem o dia parcial de hoje; este mês
// e este ano vão até hoje (REQUIREMENTS §3.2).
// Os atalhos que andam com o dia de hoje comparam sempre pelos dias, mesmo
// quando cobrem um mês inteiro, como os últimos 30 dias em 1º de maio
// (ADR-0021).
const ATALHOS_POR_DIAS: ReadonlySet<Atalho> = new Set([
  "hoje",
  "ontem",
  "ultimos-7-dias",
  "ultimos-30-dias",
]);

const CALCULOS_ATALHO: Record<Atalho, (hoje: Date) => [Date, Date]> = {
  hoje: (hoje) => [hoje, hoje],
  ontem: (hoje) => [somarDias(hoje, -1), somarDias(hoje, -1)],
  "ultimos-7-dias": (hoje) => [
    somarDias(hoje, -DIAS_ULTIMA_SEMANA),
    somarDias(hoje, -1),
  ],
  "ultimos-30-dias": (hoje) => [
    somarDias(hoje, -DIAS_ULTIMO_MES),
    somarDias(hoje, -1),
  ],
  "este-mes": (hoje) => [iniciarMes(hoje), hoje],
  "mes-passado": (hoje) => {
    const fimMesPassado = somarDias(iniciarMes(hoje), -1);
    return [iniciarMes(fimMesPassado), fimMesPassado];
  },
  "este-ano": (hoje) => [iniciarAno(hoje), hoje],
};

export function calcularIntervalo(atalho: Atalho, hoje: string): Intervalo {
  const [inicio, fim] = CALCULOS_ATALHO[atalho](lerDia(hoje));
  return { inicio: escreverDia(inicio), fim: escreverDia(fim) };
}

// "Este mês" e "este ano" comparam com o mesmo trecho do mês e do ano
// anteriores, e por isso a regra precisa do atalho: 01 a 13/01 é os dois. Os
// meses inteiros comparam com os meses inteiros antes deles, e o restante,
// com os mesmos dias imediatamente antes (ADR-0021).
function recuarIntervalo(
  periodo: Atalho | Intervalo,
  inicio: Date,
  fim: Date,
): [Date, Date] {
  if (periodo === "este-mes") {
    return [recuarMeses(inicio, 1), recuarMeses(fim, 1)];
  }
  if (periodo === "este-ano") {
    return [recuarMeses(inicio, MESES_ANO), recuarMeses(fim, MESES_ANO)];
  }
  const porDias = typeof periodo === "string" && ATALHOS_POR_DIAS.has(periodo);
  if (!porDias && cobreMesesInteiros(inicio, fim)) {
    const meses = contarMeses(inicio, fim);
    return [recuarMeses(inicio, meses), encerrarMes(recuarMeses(fim, meses))];
  }
  const dias = contarDias(inicio, fim);
  return [somarDias(inicio, -dias), somarDias(fim, -dias)];
}

// O período anterior equivalente, com que cada métrica se compara (RF-27).
// Recebe o atalho ou o intervalo livre escolhido e o intervalo já resolvido.
export function calcularPeriodoAnterior(
  periodo: Atalho | Intervalo,
  intervalo: Intervalo,
): Intervalo {
  const [inicio, fim] = recuarIntervalo(
    periodo,
    lerDia(intervalo.inicio),
    lerDia(intervalo.fim),
  );
  return { inicio: escreverDia(inicio), fim: escreverDia(fim) };
}

// O dia existe quando a leitura e a escrita devolvem o mesmo texto: 30 de
// fevereiro viraria 2 de março.
function possuiFormatoDia(valor: unknown): valor is string {
  return (
    typeof valor === "string" &&
    FORMATO_DIA.test(valor) &&
    !Number.isNaN(lerDia(valor).getTime()) &&
    escreverDia(lerDia(valor)) === valor
  );
}

// O intervalo livre como chega da URL. Nulo para o que não for dois dias
// válidos com o início até o fim.
export function lerIntervalo(inicio: unknown, fim: unknown): Intervalo | null {
  if (!possuiFormatoDia(inicio) || !possuiFormatoDia(fim) || inicio > fim) {
    return null;
  }
  return { inicio, fim };
}
