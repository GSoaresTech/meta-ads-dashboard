import { defineConfig } from "vitest/config";

// Testes de integração: requisições HTTP ao servidor de produção do Next.js,
// que sobe no globalSetup. Cobrem o que o Vitest com jsdom não executa, como
// Server Components `async`, rotas e cabeçalhos HTTP (ADR-0001).
export default defineConfig({
  resolve: {
    tsconfigPaths: true,
  },
  test: {
    environment: "node",
    include: ["tests/integracao/**/*.test.ts"],
    globalSetup: ["./tests/integracao/servidor.ts"],
  },
});
