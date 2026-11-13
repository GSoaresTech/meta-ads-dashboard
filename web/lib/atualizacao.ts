import type { Intervalo } from "@/lib/periodo";

// RF-28: o painel avisa do atraso quando a última carga bem-sucedida da
// empresa tem mais de 3 horas. A carga horária roda a cada hora (RF-06), e o
// limite deixa passar duas execuções perdidas antes do aviso.
export const LIMITE_ATUALIZACAO_HORAS = 3;

const MILISSEGUNDOS_HORA = 60 * 60 * 1000;

// A empresa que nunca teve carga bem-sucedida também está atrasada. O relógio
// entra como parâmetro, para que os testes fixem o instante.
export function estaDesatualizada(
  ultimaCargaEm: Date | null,
  agora: Date,
): boolean {
  return (
    ultimaCargaEm === null ||
    agora.getTime() - ultimaCargaEm.getTime() >
      LIMITE_ATUALIZACAO_HORAS * MILISSEGUNDOS_HORA
  );
}

// O dia de hoje ainda recebe dados a cada carga, e o intervalo que chega a
// ele tem números parciais (RF-28). Vale também o que só passa dele: no Geral
// com contas em fusos diferentes, o "hoje" é o da conta mais atrasada, e o
// dia seguinte já corre nas adiantadas (REQUIREMENTS §3.3). Em AAAA-MM-DD, a
// ordem do texto é a das datas.
export function alcancaHoje({ fim }: Intervalo, hoje: string): boolean {
  return fim >= hoje;
}
