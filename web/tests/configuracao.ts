import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// A limpeza automática do Testing Library só se registra com um afterEach
// global, que o Vitest não expõe sem `globals: true`; sem ela, cada render
// se acumula no document.body e um teste enxerga o DOM do anterior.
afterEach(() => {
  cleanup();
});
