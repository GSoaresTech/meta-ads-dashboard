import { CartaoMetrica } from "@/components/CartaoMetrica";
import { SerieTemporal } from "@/components/SerieTemporal";
import type { Granularidade } from "@/lib/periodo";
import type { DestaqueCampanha as Destaque } from "@/lib/visao-campanha";

import estilos from "./DestaqueCampanha.module.css";

interface Propriedades {
  destaque: Destaque;
  granularidade: Granularidade;
}

// O resultado principal e o KPI que a resolução do catálogo escolheu para a
// campanha, já com a sobrescrita (RF-31; ADR-0007). O componente só exibe o
// que recebe: nenhuma regra de objetivo fica aqui. Cada métrica tem o cartão
// e a série, como nos totais das outras visões.
export function DestaqueCampanha({
  destaque,
  granularidade,
}: Readonly<Propriedades>) {
  const { objetivo, status, moeda, metricas } = destaque;

  return (
    <section aria-labelledby="titulo-destaque" className={estilos.destaque}>
      <h2 id="titulo-destaque">Resultado principal</h2>
      <dl className={estilos.situacao}>
        <div>
          <dt>Objetivo</dt>
          <dd>{objetivo}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{status}</dd>
        </div>
      </dl>
      {metricas.length === 0 ? (
        <p>O objetivo desta campanha não tem resultado principal definido.</p>
      ) : (
        <>
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
        </>
      )}
    </section>
  );
}
