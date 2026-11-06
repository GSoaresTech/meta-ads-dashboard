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

export interface Intervalo {
  inicio: string;
  fim: string;
}

// A conta ainda sem a primeira extração não tem fuso, e a rotina diária usa
// o dia em UTC para ela (ADR-0009 §5).
const FUSO_SEM_CONTA = "UTC";

const DIAS_ULTIMA_SEMANA = 7;
const DIAS_ULTIMO_MES = 30;

// O ano 0000 existe no Date, mas o Postgres recusa o texto com erro, em vez de
// devolver zero linhas.
const FORMATO_DIA = /^(?!0000)\d{4}-\d{2}-\d{2}$/;

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

// O dia corrente no fuso da conta (RF-26). Com contas em fusos diferentes,
// vale o da mais atrasada, para que ontem já esteja encerrado em todas
// (REQUIREMENTS §3.3). Em AAAA-MM-DD, a ordem do texto é a das datas.
export function obterHoje(
  agora: Date,
  fusosHorarios: readonly string[],
): string {
  const fusos = fusosHorarios.length > 0 ? fusosHorarios : [FUSO_SEM_CONTA];
  return fusos
    .map((fuso) => obterDiaNoFuso(agora, fuso))
    .reduce((maisAtrasado, dia) => (dia < maisAtrasado ? dia : maisAtrasado));
}

// Os últimos 7 e 30 dias terminam ontem, sem o dia parcial de hoje; este mês
// e este ano vão até hoje (REQUIREMENTS §3.2).
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
