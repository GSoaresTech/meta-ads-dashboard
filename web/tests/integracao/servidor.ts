import { spawn, type ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";
import { once } from "node:events";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import type { TestProject } from "vitest/node";

import { conectarBancoLocal, URL_BANCO_LOCAL } from "./banco-local";

// Sobe o servidor de produção do Next.js (`next start`) uma vez para a suíte.
// O build vem antes, no script test:integracao, para que o teste nunca rode
// contra um build antigo.
//
// O servidor conecta ao banco local como painel_leitor, o papel do painel em
// produção, para que os testes provem que ele basta (ADR-0009 §3). O papel
// nasce sem senha, que nunca autentica; a suíte define uma senha sorteada e,
// no fim, devolve a que havia.

const RAIZ_PAINEL = fileURLToPath(new URL("../..", import.meta.url));
const CLI_NEXT = fileURLToPath(
  new URL("../../node_modules/next/dist/bin/next", import.meta.url),
);
const HOST = "127.0.0.1";
const ESPERA_MAXIMA_SERVIDOR_MS = 30_000;
const INTERVALO_TENTATIVAS_MS = 200;
const BYTES_SENHA = 24;

declare module "vitest" {
  export interface ProvidedContext {
    urlPainel: string;
  }
}

interface ServidorPainel {
  processo: ChildProcess;
  url: string;
  saida: string[];
}

async function reservarPorta(): Promise<number> {
  const servidor = createServer();
  servidor.listen(0, HOST);
  await once(servidor, "listening");
  const endereco = servidor.address();
  servidor.close();
  await once(servidor, "close");

  if (endereco === null || typeof endereco === "string") {
    throw new Error("não foi possível reservar uma porta local");
  }
  return endereco.port;
}

function iniciarServidor(
  porta: number,
  ambiente: NodeJS.ProcessEnv,
): ServidorPainel {
  const processo = spawn(
    process.execPath,
    [CLI_NEXT, "start", "--hostname", HOST, "--port", String(porta)],
    { cwd: RAIZ_PAINEL, env: ambiente, stdio: ["ignore", "pipe", "pipe"] },
  );
  const saida: string[] = [];
  processo.stdout?.on("data", (trecho: Buffer) => saida.push(String(trecho)));
  processo.stderr?.on("data", (trecho: Buffer) => saida.push(String(trecho)));

  return { processo, url: `http://${HOST}:${porta}`, saida };
}

async function aguardarServidor(servidor: ServidorPainel): Promise<void> {
  const limite = Date.now() + ESPERA_MAXIMA_SERVIDOR_MS;

  while (Date.now() < limite) {
    if (encerrouServidor(servidor)) {
      break;
    }
    try {
      await fetch(servidor.url, { redirect: "manual" });
      return;
    } catch (erro) {
      // O fetch levanta TypeError quando a conexão é recusada, enquanto o
      // servidor ainda não abriu a porta.
      if (!(erro instanceof TypeError)) {
        throw erro;
      }
      await new Promise((resolver) =>
        setTimeout(resolver, INTERVALO_TENTATIVAS_MS),
      );
    }
  }

  servidor.processo.kill();
  throw new Error(
    `o servidor do painel não respondeu:\n${servidor.saida.join("")}`,
  );
}

// Morto por sinal, o processo fica com exitCode nulo e signalCode preenchido.
function encerrouServidor(servidor: ServidorPainel): boolean {
  return (
    servidor.processo.exitCode !== null || servidor.processo.signalCode !== null
  );
}

async function encerrarServidor(servidor: ServidorPainel): Promise<void> {
  if (encerrouServidor(servidor)) {
    return;
  }
  const saida = once(servidor.processo, "exit");
  servidor.processo.kill();
  await saida;
}

// O hash guardado, ou nulo, para devolver ao papel a senha que ele tinha, que
// alguém pode ter definido com \password para usar o painel local.
async function lerSenhaPainelLeitor(): Promise<string | null> {
  const cliente = await conectarBancoLocal();
  try {
    const { rows } = await cliente.query<{ rolpassword: string | null }>(
      "SELECT rolpassword FROM pg_catalog.pg_authid WHERE rolname = 'painel_leitor'",
    );
    return rows[0].rolpassword;
  } finally {
    await cliente.end();
  }
}

// Um hash SCRAM é guardado como veio, e por isso a mesma função devolve a
// senha anterior.
async function definirSenhaPainelLeitor(senha: string | null): Promise<void> {
  const cliente = await conectarBancoLocal();
  try {
    const valor = senha === null ? "NULL" : cliente.escapeLiteral(senha);
    await cliente.query(`ALTER ROLE painel_leitor PASSWORD ${valor}`);
  } finally {
    await cliente.end();
  }
}

// O URL_BANCO do ambiente é substituído, para que o servidor nunca conecte a
// outro banco que não o local.
function montarUrlPainelLeitor(senha: string): string {
  const url = new URL(URL_BANCO_LOCAL);
  url.username = "painel_leitor";
  url.password = senha;
  return url.toString();
}

export default async function configurarServidor(
  projeto: TestProject,
): Promise<() => Promise<void>> {
  const senhaAnterior = await lerSenhaPainelLeitor();
  const senha = randomBytes(BYTES_SENHA).toString("hex");
  await definirSenhaPainelLeitor(senha);

  const servidores: ServidorPainel[] = [];
  const encerrar = async () => {
    await Promise.all(servidores.map(encerrarServidor));
    await definirSenhaPainelLeitor(senhaAnterior);
  };

  try {
    const servidor = iniciarServidor(await reservarPorta(), {
      ...process.env,
      URL_BANCO: montarUrlPainelLeitor(senha),
    });
    servidores.push(servidor);
    await aguardarServidor(servidor);

    projeto.provide("urlPainel", servidor.url);
  } catch (erro) {
    // Sem isto, um servidor que não sobe deixaria a senha sorteada no papel.
    await encerrar();
    throw erro;
  }

  return encerrar;
}
