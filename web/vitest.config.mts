import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    tsconfigPaths: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/configuracao.ts"],
    coverage: {
      // RNF-19 mede só a formatação pt-BR, centralizada num módulo (CLAUDE.md
      // §7). Componentes ficam fora: Server Components `async` não rodam no
      // Vitest (ADR-0001).
      include: ["lib/formatacao*"],
      thresholds: { lines: 80 },
    },
  },
});
