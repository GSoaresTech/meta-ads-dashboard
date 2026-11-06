import { notFound } from "next/navigation";

import { ListaEntidades } from "@/components/ListaEntidades";
import { ResumoDesempenho } from "@/components/ResumoDesempenho";
import { SeletorPeriodo } from "@/components/SeletorPeriodo";
import { TabelaCampanhas } from "@/components/TabelaCampanhas";
import { TrilhaNavegacao } from "@/components/TrilhaNavegacao";
import { exigirCredencialEmpresa } from "@/lib/acesso";
import { carregarResumoGeral, carregarVisaoConta } from "@/lib/desempenho";
import { carregarTrilha, listarFilhasComEntrega } from "@/lib/entidades";
import {
  lerSelecao,
  montarCaminho,
  NIVEIS_FILHOS,
  nomearEntidade,
  resolverIntervalo,
  type Nivel,
  type ParametrosUrl,
  type Selecao,
} from "@/lib/navegacao";
import { obterHoje, type Intervalo } from "@/lib/periodo";

interface Propriedades {
  empresaId: string;
  nivel: Nivel;
  // Nula só no geral, que é a própria empresa.
  entidadeId: string | null;
  parametros: ParametrosUrl;
}

interface PropriedadesConteudo {
  credencial: string;
  empresaId: string;
  entidadeId: string | null;
  intervalo: Intervalo;
  selecao: Selecao;
}

// Os totais, as séries e as campanhas com as colunas da conta (§3.1).
async function ConteudoConta({
  credencial,
  empresaId,
  entidadeId,
  intervalo,
  selecao,
}: Readonly<PropriedadesConteudo>) {
  const { resumos, campanhas } = await carregarVisaoConta(
    credencial,
    empresaId,
    entidadeId,
    intervalo,
    selecao.granularidade,
  );

  return (
    <>
      <ResumoDesempenho
        resumos={resumos}
        granularidade={selecao.granularidade}
      />
      <TabelaCampanhas
        empresaId={empresaId}
        campanhas={campanhas}
        selecao={selecao}
      />
    </>
  );
}

// Os totais e as séries do Geral e a lista das filhas dos demais níveis.
async function ConteudoEntidade({
  credencial,
  empresaId,
  nivel,
  entidadeId,
  intervalo,
  selecao,
}: Readonly<PropriedadesConteudo & { nivel: Exclude<Nivel, "conta"> }>) {
  const nivelFilho = NIVEIS_FILHOS[nivel];
  const [filhas, resumos] = await Promise.all([
    nivelFilho === null
      ? []
      : listarFilhasComEntrega(
          credencial,
          empresaId,
          nivel,
          entidadeId,
          intervalo,
        ),
    nivel === "geral"
      ? carregarResumoGeral(
          credencial,
          empresaId,
          intervalo,
          selecao.granularidade,
        )
      : null,
  ]);

  return (
    <>
      {resumos !== null && (
        <ResumoDesempenho
          resumos={resumos}
          granularidade={selecao.granularidade}
        />
      )}
      {nivelFilho !== null && (
        <ListaEntidades
          empresaId={empresaId}
          nivel={nivelFilho}
          filhas={filhas}
          selecao={selecao}
        />
      )}
    </>
  );
}

// A página de um nível: a trilha, o seletor e o conteúdo dele. O relógio lido
// aqui é o que os atalhos usam, no fuso da entidade em foco (RF-26).
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
  const conteudo = { credencial, empresaId, entidadeId, intervalo, selecao };

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
      {nivel === "conta" ? (
        <ConteudoConta {...conteudo} />
      ) : (
        <ConteudoEntidade {...conteudo} nivel={nivel} />
      )}
    </main>
  );
}
