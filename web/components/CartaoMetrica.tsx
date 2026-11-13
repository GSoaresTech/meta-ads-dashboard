import { useId } from "react";

import { AjudaMetrica } from "@/components/AjudaMetrica";
import { formatarLeituraMetrica, formatarVariacao } from "@/lib/formatacao";
import type { MetricaResumida } from "@/lib/resumo-desempenho";
import { avaliarVariacao, calcularVariacao } from "@/lib/variacao";

import estilos from "./CartaoMetrica.module.css";

interface Propriedades {
  metrica: MetricaResumida["metrica"];
  moeda: string;
  valor: MetricaResumida["total"];
  anterior: MetricaResumida["anterior"];
}

// A seta repete o sinal para quem vê, e por isso fica fora do leitor de tela.
const SETAS: Record<number, string> = { 1: "↑", [-1]: "↓" };

// A variação em relação ao período anterior, avaliada pelo sentido do
// catálogo, sem cor: a seta e a palavra dizem a direção e se ela é boa
// (RF-27; ADR-0015; ADR-0021).
function VariacaoMetrica({
  metrica,
  valor,
  anterior,
}: Readonly<Omit<Propriedades, "moeda">>) {
  const variacao = calcularVariacao(valor, anterior);
  const avaliacao = avaliarVariacao(variacao, metrica.sentidoMelhora);
  const seta = variacao === null ? undefined : SETAS[Math.sign(variacao)];

  return (
    <p className={estilos.variacao}>
      {seta !== undefined && <span aria-hidden="true">{seta} </span>}
      {formatarVariacao(variacao)}
      {avaliacao !== null && ` · ${avaliacao}`}
      <span className={estilos.oculto}> em relação ao período anterior</span>
    </p>
  );
}

// O rótulo e a explicação vêm do catálogo, e a formatação segue a unidade
// dele: mudar um texto no banco muda a tela (RF-30; ADR-0007). A explicação
// fica na ajuda, como em toda métrica exibida (ADR-0020).
export function CartaoMetrica({
  metrica,
  moeda,
  valor,
  anterior,
}: Readonly<Propriedades>) {
  const idTitulo = useId();

  return (
    <article className={estilos.cartao} aria-labelledby={idTitulo}>
      <h3 id={idTitulo} className={estilos.rotulo}>
        {metrica.rotulo}
      </h3>
      <p className={estilos.valor}>
        {formatarLeituraMetrica(valor, metrica.unidade, moeda)}
      </p>
      <VariacaoMetrica metrica={metrica} valor={valor} anterior={anterior} />
      <AjudaMetrica metrica={metrica} />
    </article>
  );
}
