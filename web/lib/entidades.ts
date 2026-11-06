import "server-only";

import { consultar } from "@/lib/banco";
import type { EntidadeFilha, Nivel, NivelTrilha } from "@/lib/navegacao";
import type { Intervalo } from "@/lib/periodo";

// Um valor fora do formato não é de nenhuma entidade e nem vai ao banco, que
// recusaria o texto como uuid com erro, em vez de devolver zero linhas.
const FORMATO_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface LinhaEntidade {
  nivel: Nivel;
  entidade_id: string;
  nome: string | null;
}

interface LinhaTrilha extends Omit<LinhaEntidade, "entidade_id"> {
  entidade_id: string | null;
  fusos_horarios: string[];
}

// Vazia para entidade inexistente, de outra empresa ou de outro nível, e a
// página responde 404, sem distinguir os casos (RF-46).
export async function carregarTrilha(
  credencial: string,
  empresaId: string,
  nivel: Nivel,
  entidadeId: string | null,
): Promise<NivelTrilha[]> {
  const possuiIdsValidos =
    FORMATO_UUID.test(empresaId) &&
    (entidadeId === null || FORMATO_UUID.test(entidadeId));
  if (!possuiIdsValidos) {
    return [];
  }

  const linhas = await consultar<LinhaTrilha>(
    `SELECT nivel, entidade_id, nome, fusos_horarios
     FROM analitico.obter_trilha($1, $2, $3, $4)`,
    [credencial, empresaId, nivel, entidadeId],
  );
  return linhas.map((linha) => ({
    nivel: linha.nivel,
    entidadeId: linha.entidade_id,
    nome: linha.nome,
    fusosHorarios: linha.fusos_horarios,
  }));
}

// As filhas com entrega no período (RF-23): o nome vem da listagem, e o
// filtro, do desempenho do intervalo inteiro, em que as filhas aparecem só
// com dados (ADR-0009 §4).
export async function listarFilhasComEntrega(
  credencial: string,
  empresaId: string,
  nivel: Nivel,
  entidadeId: string | null,
  { inicio, fim }: Intervalo,
): Promise<EntidadeFilha[]> {
  const [filhas, comEntrega] = await Promise.all([
    consultar<LinhaEntidade>(
      `SELECT nivel, entidade_id, nome
       FROM analitico.listar_entidades($1, $2, $3, $4)`,
      [credencial, empresaId, nivel, entidadeId],
    ),
    consultar<{ entidade_id: string }>(
      `SELECT DISTINCT entidade_id
       FROM analitico.obter_desempenho($1, $2, $3, $4, $5, $6, 'periodo')
       WHERE nivel <> $3`,
      [credencial, empresaId, nivel, entidadeId, inicio, fim],
    ),
  ]);

  const idsComEntrega = new Set(comEntrega.map((linha) => linha.entidade_id));
  return filhas
    .filter((filha) => idsComEntrega.has(filha.entidade_id))
    .map((filha) => ({
      nivel: filha.nivel,
      entidadeId: filha.entidade_id,
      nome: filha.nome,
    }));
}
