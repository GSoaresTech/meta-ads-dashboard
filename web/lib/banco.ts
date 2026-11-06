import "server-only";

import { Pool, type QueryResultRow } from "pg";

import { exigirTls } from "@/lib/conexao-banco";

// O painel conecta como painel_leitor, que só executa as funções de
// analitico (ADR-0009 §3). O pool fica no módulo para que as requisições da
// mesma instância reusem as conexões. Ele nasce na primeira consulta, e não
// na importação, porque o build roda sem banco.
let pool: Pool | undefined;

function obterPool(): Pool {
  if (pool !== undefined) {
    return pool;
  }

  const urlBanco = process.env.URL_BANCO;
  if (!urlBanco) {
    throw new Error("URL_BANCO não definida");
  }
  exigirTls(urlBanco);

  pool = new Pool({ connectionString: urlBanco });
  // Uma conexão ociosa que cai emite error no pool, que a descarta. Sem um
  // ouvinte, o Node encerraria o processo.
  pool.on("error", (erro) => {
    console.error("conexão ociosa com o banco encerrada:", erro.message);
  });
  return pool;
}

// Os valores vão sempre como parâmetros, nunca no texto do comando: o
// Postgres grava no log o texto do comando que falha, e não os parâmetros
// dele, e assim o token de acesso não chega ao log.
export async function consultar<Linha extends QueryResultRow>(
  comando: string,
  parametros: unknown[],
): Promise<Linha[]> {
  const resultado = await obterPool().query<Linha>(comando, parametros);
  return resultado.rows;
}
