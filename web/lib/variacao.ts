// A comparação de cada métrica com o período anterior equivalente (RF-27;
// ADR-0021). Se a alta é melhora ou piora vem do catálogo, e nada aqui depende
// da métrica (ADR-0007).

import { CASAS_DECIMAIS_VARIACAO } from "@/lib/formatacao";

// Os valores do CHECK de normalizado.metrica.sentido_melhora.
export type SentidoMelhora = "alta" | "queda" | "indiferente";

export type AvaliacaoVariacao = "melhora" | "piora";

type ValorLido = number | null | undefined;

// A fração tem duas casas a mais que o percentual exibido.
const ESCALA_VARIACAO = 10 ** (CASAS_DECIMAIS_VARIACAO + 2);

function possuiValor(valor: ValorLido): valor is number {
  return Number.isFinite(valor);
}

// A fração da mudança: 0,25 é uma alta de 25%. Nula quando falta um dos
// valores ou quando o anterior é zero, que não tem base de comparação. Sai
// arredondada na casa exibida, para que a seta e a avaliação nunca acompanhem
// um "0%".
export function calcularVariacao(
  atual: ValorLido,
  anterior: ValorLido,
): number | null {
  if (!possuiValor(atual) || !possuiValor(anterior) || anterior === 0) {
    return null;
  }
  const variacao = (atual - anterior) / Math.abs(anterior);
  const arredondada = Math.round(variacao * ESCALA_VARIACAO) / ESCALA_VARIACAO;
  // Uma queda menor que a casa exibida arredonda para -0, que é zero.
  return arredondada === 0 ? 0 : arredondada;
}

// Nula na métrica indiferente e quando não há variação a avaliar.
export function avaliarVariacao(
  variacao: number | null,
  sentido: SentidoMelhora,
): AvaliacaoVariacao | null {
  if (variacao === null || variacao === 0 || sentido === "indiferente") {
    return null;
  }
  return variacao > 0 === (sentido === "alta") ? "melhora" : "piora";
}
