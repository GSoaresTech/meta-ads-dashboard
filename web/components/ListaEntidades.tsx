import Link from "next/link";

import {
  montarCaminho,
  montarEndereco,
  nomearEntidade,
  type EntidadeFilha,
  type NivelFilho,
  type Selecao,
} from "@/lib/navegacao";

// As campanhas têm a própria tabela, com as colunas da visão da conta.
type NivelLista = Exclude<NivelFilho, "campanha">;

const TITULOS: Record<NivelLista, string> = {
  conta: "Contas",
  anuncio: "Anúncios",
};

const AVISOS_SEM_ENTREGA: Record<NivelLista, string> = {
  conta: "Nenhuma conta com entrega no período.",
  anuncio: "Nenhum anúncio com entrega no período.",
};

interface Propriedades {
  empresaId: string;
  nivel: NivelLista;
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
