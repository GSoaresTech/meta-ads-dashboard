import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import PaginaInicial from "@/app/page";

test("exibe o título do painel", () => {
  render(<PaginaInicial />);

  expect(
    screen.getByRole("heading", { level: 1, name: "Painel de Meta Ads" }),
  ).toBeDefined();
});
