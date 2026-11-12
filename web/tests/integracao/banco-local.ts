import { randomInt } from "node:crypto";

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

// Uma hierarquia fictícia de conta, campanhas e anúncios, cada anúncio com
// investimento nos dias informados. Cada campanha tem um conjunto, e cada
// conta, um criativo, que não são níveis de navegação.
export interface AnuncioTeste {
  nome: string;
  dias: string[];
  // A quantidade de cada tipo de ação da API em cada um dos dias.
  acoesPorDia?: Record<string, number>;
}

export interface CampanhaTeste {
  nome: string;
  // Sem objetivo, a campanha é de vendas.
  objetivo?: string;
  // Sem status, a campanha está ativa.
  status?: string;
  // A meta de otimização do conjunto, que escolhe a regra do catálogo. Sem
  // ela, vale a regra de "qualquer" do objetivo (ADR-0007).
  metaOtimizacao?: string;
  anuncios: AnuncioTeste[];
}

export interface ContaTeste {
  nome: string;
  fusoHorario: string;
  moeda: string;
  campanhas: CampanhaTeste[];
}

// Os IDs internos pelo nome de cada entidade cadastrada.
export type IdsEntidades = Record<string, string>;

const INVESTIMENTO_DIARIO = "10.00";
const IMPRESSOES_DIARIAS = 100;
const OBJETIVO_PADRAO = "OUTCOME_SALES";
const STATUS_PADRAO = "ACTIVE";

// IDs da Meta inventados e sorteados, com 15 dígitos, para não colidir com
// o seed, com a massa de referência nem com outro arquivo de teste.
function sortearIdMeta(): string {
  return `7${String(randomInt(0, 10 ** 14)).padStart(14, "0")}`;
}

async function inserirComId(
  cliente: Client,
  comando: string,
  parametros: unknown[],
): Promise<string> {
  const { rows } = await cliente.query<{ id: string }>(
    `${comando} RETURNING id`,
    parametros,
  );
  return rows[0].id;
}

async function cadastrarAnuncio(
  cliente: Client,
  empresaId: string,
  execucaoId: string,
  conjuntoId: string,
  criativoId: string,
  anuncio: AnuncioTeste,
): Promise<string> {
  const anuncioId = await inserirComId(
    cliente,
    `INSERT INTO normalizado.anuncio
       (empresa_id, conjunto_anuncio_id, criativo_id, id_meta, nome, status, execucao_id)
     VALUES ($1, $2, $3, $4, $5, 'ACTIVE', $6)`,
    [
      empresaId,
      conjuntoId,
      criativoId,
      sortearIdMeta(),
      anuncio.nome,
      execucaoId,
    ],
  );
  for (const dia of new Set(anuncio.dias)) {
    await cliente.query(
      `INSERT INTO normalizado.metrica_diaria_anuncio
         (empresa_id, anuncio_id, data, investimento, impressoes, execucao_id)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [
        empresaId,
        anuncioId,
        dia,
        INVESTIMENTO_DIARIO,
        IMPRESSOES_DIARIAS,
        execucaoId,
      ],
    );
    for (const [tipoAcao, quantidade] of Object.entries(
      anuncio.acoesPorDia ?? {},
    )) {
      await cliente.query(
        `INSERT INTO normalizado.acao_diaria_anuncio
           (empresa_id, anuncio_id, data, tipo_acao, quantidade, execucao_id)
         VALUES ($1, $2, $3, $4, $5, $6)`,
        [empresaId, anuncioId, dia, tipoAcao, quantidade, execucaoId],
      );
    }
  }
  return anuncioId;
}

async function cadastrarCampanha(
  cliente: Client,
  empresaId: string,
  execucaoId: string,
  contaId: string,
  criativoId: string,
  campanha: CampanhaTeste,
): Promise<IdsEntidades> {
  const campanhaId = await inserirComId(
    cliente,
    `INSERT INTO normalizado.campanha
       (empresa_id, conta_anuncio_id, id_meta, nome, objetivo, status, execucao_id)
     VALUES ($1, $2, $3, $4, $5, $6, $7)`,
    [
      empresaId,
      contaId,
      sortearIdMeta(),
      campanha.nome,
      campanha.objetivo ?? OBJETIVO_PADRAO,
      campanha.status ?? STATUS_PADRAO,
      execucaoId,
    ],
  );
  const conjuntoId = await inserirComId(
    cliente,
    `INSERT INTO normalizado.conjunto_anuncio
       (empresa_id, campanha_id, id_meta, status, meta_otimizacao, execucao_id)
     VALUES ($1, $2, $3, 'ACTIVE', $4, $5)`,
    [
      empresaId,
      campanhaId,
      sortearIdMeta(),
      campanha.metaOtimizacao ?? null,
      execucaoId,
    ],
  );

  const ids: IdsEntidades = { [campanha.nome]: campanhaId };
  for (const anuncio of campanha.anuncios) {
    ids[anuncio.nome] = await cadastrarAnuncio(
      cliente,
      empresaId,
      execucaoId,
      conjuntoId,
      criativoId,
      anuncio,
    );
  }
  return ids;
}

async function cadastrarConta(
  cliente: Client,
  empresaId: string,
  execucaoId: string,
  conta: ContaTeste,
): Promise<IdsEntidades> {
  const contaId = await inserirComId(
    cliente,
    `INSERT INTO normalizado.conta_anuncio
       (empresa_id, id_meta, nome, fuso_horario, moeda, execucao_id)
     VALUES ($1, $2, $3, $4, $5, $6)`,
    [
      empresaId,
      sortearIdMeta(),
      conta.nome,
      conta.fusoHorario,
      conta.moeda,
      execucaoId,
    ],
  );
  const criativoId = await inserirComId(
    cliente,
    `INSERT INTO normalizado.criativo (empresa_id, conta_anuncio_id, id_meta, execucao_id)
     VALUES ($1, $2, $3, $4)`,
    [empresaId, contaId, sortearIdMeta(), execucaoId],
  );

  let ids: IdsEntidades = { [conta.nome]: contaId };
  for (const campanha of conta.campanhas) {
    ids = {
      ...ids,
      ...(await cadastrarCampanha(
        cliente,
        empresaId,
        execucaoId,
        contaId,
        criativoId,
        campanha,
      )),
    };
  }
  return ids;
}

export async function cadastrarEntidades(
  cliente: Client,
  empresaId: string,
  contas: ContaTeste[],
): Promise<IdsEntidades> {
  const execucaoId = await inserirComId(
    cliente,
    "INSERT INTO normalizado.execucao_carga (empresa_id, tipo) VALUES ($1, 'diaria')",
    [empresaId],
  );

  let ids: IdsEntidades = {};
  for (const conta of contas) {
    ids = {
      ...ids,
      ...(await cadastrarConta(cliente, empresaId, execucaoId, conta)),
    };
  }
  return ids;
}

// De baixo para cima, porque as FKs não apagam em cascata (ADR-0009 §1).
// Vem antes de removerMassaAcesso, que apaga as empresas.
export async function removerEntidades(
  cliente: Client,
  empresas: string[],
): Promise<void> {
  const tabelas = [
    "metrica_diaria_anuncio",
    "anuncio",
    "criativo",
    "conjunto_anuncio",
    "campanha",
    "conta_anuncio",
    "execucao_carga",
  ];
  for (const tabela of tabelas) {
    await cliente.query(
      `DELETE FROM normalizado.${tabela} WHERE empresa_id = ANY($1::uuid[])`,
      [empresas],
    );
  }
}
