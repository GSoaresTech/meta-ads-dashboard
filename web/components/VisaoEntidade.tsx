import { notFound } from "next/navigation";

import { DestaqueCampanha } from "@/components/DestaqueCampanha";
import { IndicadorAtualizacao } from "@/components/IndicadorAtualizacao";
import { ListaEntidades } from "@/components/ListaEntidades";
import { ResumoDesempenho } from "@/components/ResumoDesempenho";
import { SeletorPeriodo } from "@/components/SeletorPeriodo";
import { TabelaCampanhas } from "@/components/TabelaCampanhas";
import { TrilhaNavegacao } from "@/components/TrilhaNavegacao";
import { exigirCredencialEmpresa } from "@/lib/acesso";
import { alcancaHoje, estaDesatualizada } from "@/lib/atualizacao";
import {
  carregarResumoGeral,
  carregarVisaoAnuncio,
  carregarVisaoCampanha,
  carregarVisaoConta,
} from "@/lib/desempenho";
import { carregarTrilha, listarFilhasComEntrega } from "@/lib/entidades";
import {
  lerSelecao,
  montarCaminho,
  nomearEntidade,
  resolverIntervalo,
  type Nivel,
  type NivelTrilha,
  type ParametrosUrl,
  type Selecao,
} from "@/lib/navegacao";
import {
  calcularPeriodoAnterior,
  obterFusoReferencia,
  obterHoje,
  type Intervalo,
} from "@/lib/periodo";
import { carregarUltimaCarga } from "@/lib/situacao-carga";

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
  // O período anterior equivalente, com que as métricas se comparam (RF-27).
  intervaloAnterior: Intervalo;
  selecao: Selecao;
  // Do geral até a entidade em foco.
  trilha: NivelTrilha[];
}

// Os totais, as séries e as campanhas com as colunas da conta (§3.1).
async function ConteudoConta({
  credencial,
  empresaId,
  entidadeId,
  intervalo,
  intervaloAnterior,
  selecao,
}: Readonly<PropriedadesConteudo>) {
  const { resumos, campanhas } = await carregarVisaoConta(
    credencial,
    empresaId,
    entidadeId,
    intervalo,
    intervaloAnterior,
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

// O destaque, o apoio e os anúncios com entrega da campanha (§3.1). O
// destaque só aparece com dados, que dão a moeda e os valores dele.
async function ConteudoCampanha({
  credencial,
  empresaId,
  entidadeId,
  intervalo,
  intervaloAnterior,
  selecao,
}: Readonly<PropriedadesConteudo>) {
  const [visao, anuncios] = await Promise.all([
    carregarVisaoCampanha(
      credencial,
      empresaId,
      entidadeId,
      intervalo,
      intervaloAnterior,
      selecao.granularidade,
    ),
    listarFilhasComEntrega(
      credencial,
      empresaId,
      "campanha",
      entidadeId,
      intervalo,
    ),
  ]);
  if (visao === null) {
    notFound();
  }

  return (
    <>
      {visao.destaque !== null && (
        <DestaqueCampanha
          destaque={visao.destaque}
          granularidade={selecao.granularidade}
        />
      )}
      <ResumoDesempenho
        resumos={visao.resumos}
        granularidade={selecao.granularidade}
      />
      <ListaEntidades
        empresaId={empresaId}
        nivel="anuncio"
        filhas={anuncios}
        selecao={selecao}
      />
    </>
  );
}

// As métricas e as séries do anúncio, que são as da campanha dele (§3.1;
// ADR-0019).
async function ConteudoAnuncio({
  credencial,
  empresaId,
  entidadeId,
  intervalo,
  intervaloAnterior,
  selecao,
  trilha,
}: Readonly<PropriedadesConteudo>) {
  const campanha = trilha.find(({ nivel }) => nivel === "campanha");
  const resumos =
    campanha === undefined
      ? null
      : await carregarVisaoAnuncio(
          credencial,
          empresaId,
          entidadeId,
          campanha.entidadeId,
          intervalo,
          intervaloAnterior,
          selecao.granularidade,
        );
  if (resumos === null) {
    notFound();
  }

  return (
    <ResumoDesempenho resumos={resumos} granularidade={selecao.granularidade} />
  );
}

// Os totais e as séries do Geral e a lista das contas.
async function ConteudoGeral({
  credencial,
  empresaId,
  intervalo,
  intervaloAnterior,
  selecao,
}: Readonly<PropriedadesConteudo>) {
  const [contas, resumos] = await Promise.all([
    listarFilhasComEntrega(credencial, empresaId, "geral", null, intervalo),
    carregarResumoGeral(
      credencial,
      empresaId,
      intervalo,
      intervaloAnterior,
      selecao.granularidade,
    ),
  ]);

  return (
    <>
      <ResumoDesempenho
        resumos={resumos}
        granularidade={selecao.granularidade}
      />
      <ListaEntidades
        empresaId={empresaId}
        nivel="conta"
        filhas={contas}
        selecao={selecao}
      />
    </>
  );
}

function ConteudoNivel({
  nivel,
  ...conteudo
}: Readonly<PropriedadesConteudo & { nivel: Nivel }>) {
  switch (nivel) {
    case "conta":
      return <ConteudoConta {...conteudo} />;
    case "campanha":
      return <ConteudoCampanha {...conteudo} />;
    case "anuncio":
      return <ConteudoAnuncio {...conteudo} />;
    default:
      return <ConteudoGeral {...conteudo} />;
  }
}

// A página de um nível: a trilha, o seletor, a atualização dos dados e o
// conteúdo dele. O relógio lido aqui é o que os atalhos usam, no fuso da
// entidade em foco (RF-26), e o que mede o atraso da carga (RF-28).
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
  // Depois da trilha, que já recusou a empresa fora do formato de UUID: o
  // banco a recusaria com erro, e não com zero linhas.
  const ultimaCargaEm = await carregarUltimaCarga(credencial, empresaId);

  const selecao = lerSelecao(parametros);
  const agora = new Date();
  const hoje = obterHoje(agora, foco.fusosHorarios);
  const intervalo = resolverIntervalo(selecao.periodo, hoje);
  const intervaloAnterior = calcularPeriodoAnterior(selecao.periodo, intervalo);
  const conteudo = {
    credencial,
    empresaId,
    entidadeId,
    intervalo,
    intervaloAnterior,
    selecao,
    trilha,
  };

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
        intervaloAnterior={intervaloAnterior}
      />
      <IndicadorAtualizacao
        ultimaCargaEm={ultimaCargaEm}
        fuso={obterFusoReferencia(agora, foco.fusosHorarios)}
        desatualizada={estaDesatualizada(ultimaCargaEm, agora)}
        parcial={alcancaHoje(intervalo, hoje)}
      />
      <ConteudoNivel {...conteudo} nivel={nivel} />
    </main>
  );
}
