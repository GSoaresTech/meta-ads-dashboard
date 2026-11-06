import Link from "next/link";

import type { CampanhaListada, MetricaMedida } from "@/lib/campanhas";
import { formatarLeituraMetrica, VALOR_AUSENTE } from "@/lib/formatacao";
import {
  montarCaminho,
  montarEndereco,
  nomearEntidade,
  type Selecao,
} from "@/lib/navegacao";

import estilos from "./TabelaCampanhas.module.css";

interface Propriedades {
  empresaId: string;
  campanhas: CampanhaListada[];
  selecao: Selecao;
}

// O resultado muda de uma campanha para outra, e por isso cada célula leva o
// rótulo do catálogo junto com o valor (RF-30; ADR-0007).
function CelulaMetrica({
  medida,
  moeda,
}: Readonly<{ medida: MetricaMedida | null; moeda: string }>) {
  if (medida === null) {
    return <td>{VALOR_AUSENTE}</td>;
  }

  const { metrica, valor } = medida;
  return (
    <td>
      {metrica.rotulo}: {formatarLeituraMetrica(valor, metrica.unidade, moeda)}
    </td>
  );
}

// As campanhas com entrega no período. Os links levam a seleção junto, para
// que descer de nível mantenha o período e a granularidade (RF-23).
export function TabelaCampanhas({
  empresaId,
  campanhas,
  selecao,
}: Readonly<Propriedades>) {
  return (
    <section aria-labelledby="titulo-filhas">
      <h2 id="titulo-filhas">Campanhas</h2>
      {campanhas.length === 0 ? (
        <p>Nenhuma campanha com entrega no período.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">Campanha</th>
              <th scope="col">Objetivo</th>
              <th scope="col">Status</th>
              <th scope="col">Resultado principal</th>
              <th scope="col">Custo por resultado</th>
            </tr>
          </thead>
          <tbody>
            {campanhas.map((campanha) => (
              <tr key={campanha.entidadeId}>
                <th scope="row">
                  <Link
                    href={montarEndereco(
                      montarCaminho(
                        empresaId,
                        campanha.nivel,
                        campanha.entidadeId,
                      ),
                      selecao,
                    )}
                  >
                    {nomearEntidade(campanha)}
                  </Link>
                </th>
                <td>{campanha.objetivo}</td>
                <td>
                  <span className={estilos.etiqueta}>{campanha.status}</span>
                </td>
                <CelulaMetrica
                  medida={campanha.resultado}
                  moeda={campanha.moeda}
                />
                <CelulaMetrica medida={campanha.kpi} moeda={campanha.moeda} />
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
