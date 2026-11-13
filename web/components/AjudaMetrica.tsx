import type { Metrica } from "@/lib/resumo-desempenho";

import estilos from "./AjudaMetrica.module.css";

interface Propriedades {
  metrica: Pick<Metrica, "rotulo" | "explicacao">;
}

// O "o que é isso?" de cada métrica, com a explicação do catálogo (RF-30;
// ADR-0020). O details nativo abre pelo teclado e diz ao leitor de tela se
// está aberto, sem JavaScript. O rótulo oculto distingue as ajudas de uma
// mesma página para quem navega pelos controles.
export function AjudaMetrica({ metrica }: Readonly<Propriedades>) {
  return (
    <details className={estilos.ajuda}>
      <summary>
        O que é isso?
        <span className={estilos.oculto}> ({metrica.rotulo})</span>
      </summary>
      <p className={estilos.explicacao}>{metrica.explicacao}</p>
    </details>
  );
}
