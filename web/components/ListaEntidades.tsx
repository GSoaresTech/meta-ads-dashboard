import Link from "next/link";

import {
  montarCaminho,
  montarEndereco,
  nomearEntidade,
  type EntidadeFilha,
  type NivelFilho,
  type Selecao,
} from "@/lib/navegacao";

const TITULOS: Record<NivelFilho, string> = {
  conta: "Contas",
  campanha: "Campanhas",
  anuncio: "Anúncios",
};

const AVISOS_SEM_ENTREGA: Record<NivelFilho, string> = {
  conta: "Nenhuma conta com entrega no período.",
  campanha: "Nenhuma campanha com entrega no período.",
  anuncio: "Nenhum anúncio com entrega no período.",
};

interface Propriedades {
  empresaId: string;
  nivel: NivelFilho;
  filhas: EntidadeFilha[];
  selecao: Selecao;
}

// As filhas da entidade em foco. Os links levam a seleção junto, para que
// descer de nível mantenha o período e a granularidade (RF-23).
export function ListaEntidades({
  empresaId,
  nivel,
  filhas,
  selecao,
}: Readonly<Propriedades>) {
  return (
    <section aria-labelledby="titulo-filhas">
      <h2 id="titulo-filhas">{TITULOS[nivel]}</h2>
      {filhas.length === 0 ? (
        <p>{AVISOS_SEM_ENTREGA[nivel]}</p>
      ) : (
        <ul>
          {filhas.map((filha) => (
            <li key={filha.entidadeId}>
              <Link
                href={montarEndereco(
                  montarCaminho(empresaId, filha.nivel, filha.entidadeId),
                  selecao,
                )}
              >
                {nomearEntidade(filha)}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
