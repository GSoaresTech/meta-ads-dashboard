import { useId } from "react";

import { formatarLeituraMetrica } from "@/lib/formatacao";
import type { MetricaResumida } from "@/lib/resumo-desempenho";

import estilos from "./CartaoMetrica.module.css";

interface Propriedades {
  metrica: MetricaResumida["metrica"];
  moeda: string;
  valor: MetricaResumida["total"];
}

// O rótulo e a explicação vêm do catálogo, e a formatação segue a unidade
// dele: mudar um texto no banco muda a tela (RF-30; ADR-0007).
export function CartaoMetrica({
  metrica,
  moeda,
  valor,
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
      <p className={estilos.explicacao}>{metrica.explicacao}</p>
    </article>
  );
}
