import Link from "next/link";

import {
  montarCaminho,
  montarEndereco,
  nomearEntidade,
  ROTULOS_NIVEL,
  type NivelTrilha,
  type Selecao,
} from "@/lib/navegacao";

interface Propriedades {
  empresaId: string;
  trilha: NivelTrilha[];
  selecao: Selecao;
}

function nomearItem(item: NivelTrilha): string {
  return item.nivel === "geral" ? ROTULOS_NIVEL.geral : nomearEntidade(item);
}

// Geral → conta → campanha → anúncio. Os links levam a seleção junto, para
// que subir de nível mantenha o período e a granularidade (RF-23).
export function TrilhaNavegacao({
  empresaId,
  trilha,
  selecao,
}: Readonly<Propriedades>) {
  return (
    <nav aria-label="Trilha de navegação">
      <ol>
        {trilha.map((item, indice) => (
          <li key={item.nivel}>
            {indice === trilha.length - 1 ? (
              <span aria-current="page">{nomearItem(item)}</span>
            ) : (
              <Link
                href={montarEndereco(
                  montarCaminho(empresaId, item.nivel, item.entidadeId),
                  selecao,
                )}
              >
                {nomearItem(item)}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
