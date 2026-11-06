import { Client } from "pg";

// O padrão público do Supabase local, exibido por `supabase status`. Fica
// fixo, e não vem do ambiente, para que o teste nunca rode contra produção.
export const URL_BANCO_LOCAL =
  "postgresql://postgres:postgres@127.0.0.1:54322/postgres";

// Empresas fictícias criadas por um arquivo de teste e removidas no fim, para
// não mudar a contagem de linhas de que dependem os testes pgTAP.
export interface MassaAcesso {
  empresaA: string;
  empresaB: string;
  tokenA: string;
  tokenB: string;
  tokenOperador: string;
}

export async function conectarBancoLocal(): Promise<Client> {
  const cliente = new Client({ connectionString: URL_BANCO_LOCAL });
  await cliente.connect();
  return cliente;
}

async function cadastrarEmpresa(
  cliente: Client,
  nome: string,
): Promise<string> {
  const { rows } = await cliente.query<{ id: string }>(
    "INSERT INTO normalizado.empresa (nome) VALUES ($1) RETURNING id",
    [nome],
  );
  return rows[0].id;
}

// Sem empresa, gera a credencial do operador.
export async function gerarCredencial(
  cliente: Client,
  empresaId: string | null,
): Promise<string> {
  const escopo = empresaId === null ? "operador" : "empresa";
  const { rows } = await cliente.query<{ token: string }>(
    "SELECT normalizado.gerar_credencial($1, $2) AS token",
    [escopo, empresaId],
  );
  return rows[0].token;
}

// Revoga pela função da área do operador, como o operador revogaria.
export async function revogarCredencial(
  cliente: Client,
  tokenOperador: string,
  token: string,
): Promise<void> {
  const { rows } = await cliente.query<{ id: string }>(
    "SELECT id FROM normalizado.credencial_acesso WHERE hash = sha256(convert_to($1, 'UTF8'))",
    [token],
  );
  await cliente.query("SELECT analitico.revogar_credencial($1, $2)", [
    tokenOperador,
    rows[0].id,
  ]);
}

export async function criarMassaAcesso(
  cliente: Client,
  rotulo: string,
): Promise<MassaAcesso> {
  const empresaA = await cadastrarEmpresa(
    cliente,
    `Empresa Exemplo ${rotulo} A`,
  );
  const empresaB = await cadastrarEmpresa(
    cliente,
    `Empresa Exemplo ${rotulo} B`,
  );

  return {
    empresaA,
    empresaB,
    tokenA: await gerarCredencial(cliente, empresaA),
    tokenB: await gerarCredencial(cliente, empresaB),
    tokenOperador: await gerarCredencial(cliente, null),
  };
}

export async function removerMassaAcesso(
  cliente: Client,
  massa: MassaAcesso,
): Promise<void> {
  const empresas = [massa.empresaA, massa.empresaB];
  await cliente.query(
    `DELETE FROM normalizado.credencial_acesso
     WHERE empresa_id = ANY($1::uuid[]) OR hash = sha256(convert_to($2, 'UTF8'))`,
    [empresas, massa.tokenOperador],
  );
  await cliente.query(
    "DELETE FROM normalizado.empresa WHERE id = ANY($1::uuid[])",
    [empresas],
  );
}
