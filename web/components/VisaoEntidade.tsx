import { notFound } from "next/navigation";

import { ListaEntidades } from "@/components/ListaEntidades";
import { SeletorPeriodo } from "@/components/SeletorPeriodo";
import { TrilhaNavegacao } from "@/components/TrilhaNavegacao";
import { exigirCredencialEmpresa } from "@/lib/acesso";
import { carregarTrilha, listarFilhasComEntrega } from "@/lib/entidades";
import {
  lerSelecao,
  montarCaminho,
  NIVEIS_FILHOS,
  nomearEntidade,
  resolverIntervalo,
  type Nivel,
  type ParametrosUrl,
} from "@/lib/navegacao";
import { obterHoje } from "@/lib/periodo";

interface Propriedades {
  empresaId: string;
  nivel: Nivel;
  // Nula só no geral, que é a própria empresa.
  entidadeId: string | null;
  parametros: ParametrosUrl;
}

// A página de um nível: a trilha, o seletor e a lista das filhas. O relógio
// lido aqui é o que os atalhos usam, no fuso da entidade em foco (RF-26).
export async function VisaoEntidade({
  empresaId,
  nivel,
  entidadeId,
  parametros,
}: Readonly<Propriedades>) {
  const credencial = await exigirCredencialEmpresa(empresaId);
  const trilha = await carregarTrilha(credencial, empresaId, nivel, entidadeId);
  const foco = trilha.at(-1);
  if (foco === undefined) {
    notFound();
  }

  const selecao = lerSelecao(parametros);
  const hoje = obterHoje(new Date(), foco.fusosHorarios);
  const intervalo = resolverIntervalo(selecao.periodo, hoje);
  const nivelFilho = NIVEIS_FILHOS[nivel];
  const filhas =
    nivelFilho === null
      ? []
      : await listarFilhasComEntrega(
          credencial,
          empresaId,
          nivel,
          entidadeId,
          intervalo,
        );

  return (
    <main>
      <TrilhaNavegacao
        empresaId={empresaId}
        trilha={trilha}
        selecao={selecao}
      />
      <h1>{nomearEntidade(foco)}</h1>
      <SeletorPeriodo
        caminho={montarCaminho(empresaId, nivel, entidadeId)}
        selecao={selecao}
        intervalo={intervalo}
      />
      {nivelFilho !== null && (
        <ListaEntidades
          empresaId={empresaId}
          nivel={nivelFilho}
          filhas={filhas}
          selecao={selecao}
        />
      )}
    </main>
  );
}
