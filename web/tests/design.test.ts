import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

import { expect, test } from "vitest";

// Toda página e todo elemento do painel seguem os tokens de app/tokens.css
// (RNF-26; ADR-0015). O teste percorre as pastas, e não uma lista, para valer
// também para o que for criado depois.
const RAIZ = join(import.meta.dirname, "..");
const PASTAS = ["app", "components"];
const ARQUIVO_TOKENS = join("app", "tokens.css");

const DESVIOS: { regra: string; padrao: RegExp }[] = [
  { regra: "cor hexadecimal", padrao: /#[0-9a-f]{3,8}\b/i },
  { regra: "cor por função", padrao: /\b(rgba?|hsla?|oklch)\(/i },
  { regra: "sombra", padrao: /box-?shadow/i },
  { regra: "fonte fora dos tokens", padrao: /font-?family\s*:(?!\s*var\()/i },
];

function listarArquivos(pasta: string): string[] {
  return readdirSync(pasta, { withFileTypes: true }).flatMap((item) => {
    const caminho = join(pasta, item.name);
    return item.isDirectory() ? listarArquivos(caminho) : [caminho];
  });
}

function listarArquivosVisuais(): string[] {
  return PASTAS.flatMap((pasta) => listarArquivos(join(RAIZ, pasta)))
    .filter((caminho) => /\.(css|tsx)$/.test(caminho))
    .filter((caminho) => relative(RAIZ, caminho) !== ARQUIVO_TOKENS);
}

function acharDesvios(caminho: string): string[] {
  const conteudo = readFileSync(caminho, "utf-8");
  return DESVIOS.filter(({ padrao }) => padrao.test(conteudo)).map(
    ({ regra }) => `${relative(RAIZ, caminho)}: ${regra}`,
  );
}

test("RNF-26: nenhum CSS ou componente usa cor, sombra ou fonte fora dos tokens", () => {
  expect(listarArquivosVisuais().flatMap(acharDesvios)).toEqual([]);
});

test("a própria verificação percorre os componentes e os estilos", () => {
  const arquivos = listarArquivosVisuais().map((caminho) =>
    relative(RAIZ, caminho),
  );

  expect(arquivos).toContain(join("components", "GraficoSerie.tsx"));
  expect(arquivos).toContain(join("components", "CartaoMetrica.module.css"));
  expect(arquivos).toContain(join("app", "layout.tsx"));
  expect(arquivos).not.toContain(ARQUIVO_TOKENS);
});
