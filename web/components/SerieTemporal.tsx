import { GraficoSerie } from "@/components/GraficoSerie";
import { formatarMetrica, formatarPeriodo } from "@/lib/formatacao";
import type { Granularidade } from "@/lib/periodo";
import type { Metrica, PontoSerie } from "@/lib/resumo-desempenho";

interface Propriedades {
  metrica: Metrica;
  moeda: string;
  granularidade: Granularidade;
  pontos: PontoSerie[];
}

// O gráfico e os dados dele. A tabela vem do servidor e deixa todo valor
// acessível sem o cursor e sem o JavaScript do gráfico. Um ponto só não
// desenha linha, e o número dele já está na tabela e no cartão.
export function SerieTemporal({
  metrica,
  moeda,
  granularidade,
  pontos,
}: Readonly<Propriedades>) {
  return (
    <figure>
      <figcaption>{metrica.rotulo}</figcaption>
      {pontos.length > 1 && (
        <GraficoSerie
          rotulo={metrica.rotulo}
          unidade={metrica.unidade}
          moeda={moeda}
          granularidade={granularidade}
          pontos={pontos}
        />
      )}
      <details>
        <summary>Ver os dados</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">Período</th>
              <th scope="col">{metrica.rotulo}</th>
            </tr>
          </thead>
          <tbody>
            {pontos.map(({ inicio, fim, valor }) => (
              <tr key={inicio}>
                <td>{formatarPeriodo(inicio, fim)}</td>
                <td>{formatarMetrica(valor, metrica.unidade, moeda)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
