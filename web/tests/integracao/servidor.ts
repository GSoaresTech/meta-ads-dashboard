import { spawn, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import type { TestProject } from "vitest/node";

// Sobe o servidor de produção do Next.js (`next start`) uma vez para a suíte.
// O build vem antes, no script test:integracao, para que o teste nunca rode
// contra um build antigo.

const RAIZ_PAINEL = fileURLToPath(new URL("../..", import.meta.url));
const CLI_NEXT = fileURLToPath(
  new URL("../../node_modules/next/dist/bin/next", import.meta.url),
);
const HOST = "127.0.0.1";
const ESPERA_MAXIMA_SERVIDOR_MS = 30_000;
const INTERVALO_TENTATIVAS_MS = 200;

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
    if (servidor.processo.exitCode !== null) {
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

async function encerrarServidor(servidor: ServidorPainel): Promise<void> {
  if (servidor.processo.exitCode !== null) {
    return;
  }
  const saida = once(servidor.processo, "exit");
  servidor.processo.kill();
  await saida;
}

export default async function configurarServidor(
  projeto: TestProject,
): Promise<() => Promise<void>> {
  const servidor = iniciarServidor(await reservarPorta(), process.env);
  await aguardarServidor(servidor);
  projeto.provide("urlPainel", servidor.url);

  return () => encerrarServidor(servidor);
}
