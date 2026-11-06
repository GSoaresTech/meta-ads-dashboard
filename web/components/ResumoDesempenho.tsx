import { CartaoMetrica } from "@/components/CartaoMetrica";
import { SerieTemporal } from "@/components/SerieTemporal";
import { formatarNomeMoeda } from "@/lib/formatacao";
import type { Granularidade } from "@/lib/periodo";
import type { ResumoMoeda } from "@/lib/resumo-desempenho";

import estilos from "./ResumoDesempenho.module.css";

interface Propriedades {
  resumos: ResumoMoeda[];
  granularidade: Granularidade;
}

// Uma seção por moeda, sem nenhum total entre elas (RF-34). A métrica que a
// leitura de desempenho não traz tem cartão, mas não tem série (ADR-0013).
export function ResumoDesempenho({
  resumos,
  granularidade,
}: Readonly<Propriedades>) {
  if (resumos.length === 0) {
    return <p>Nenhum dado no período.</p>;
  }

  return resumos.map(({ moeda, metricas }) => {
    const idTitulo = `titulo-moeda-${moeda}`;

    return (
      <section
        key={moeda}
        aria-labelledby={idTitulo}
        className={estilos.painel}
      >
        <h2 id={idTitulo}>
          {formatarNomeMoeda(moeda)} ({moeda})
        </h2>
        <div className={estilos.grade}>
          {metricas.map(({ metrica, total }) => (
            <CartaoMetrica
              key={metrica.codigo}
              metrica={metrica}
              moeda={moeda}
              valor={total}
            />
          ))}
        </div>
        <div className={estilos.grade}>
          {metricas
            .filter(({ serie }) => serie.length > 0)
            .map(({ metrica, serie }) => (
              <SerieTemporal
                key={metrica.codigo}
                metrica={metrica}
                moeda={moeda}
                granularidade={granularidade}
                pontos={serie}
              />
            ))}
        </div>
      </section>
    );
  });
}
