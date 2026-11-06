// A leitura das páginas de desempenho pelo que a pessoa vê: as seções por
// moeda, os cartões e a tabela de dados de cada série.

export function acharSecao(
  documento: Document,
  titulo: string,
): Element | undefined {
  return [...documento.querySelectorAll("section")].find(
    (secao) => secao.querySelector("h2")?.textContent === titulo,
  );
}

// Cada cartão pelo rótulo, com o valor e a explicação que a pessoa lê.
export function lerCartoes(
  secao: Element | undefined,
): Record<string, string[]> {
  return Object.fromEntries(
    [...(secao?.querySelectorAll("article") ?? [])].map((cartao) => [
      cartao.querySelector("h3")?.textContent ?? "",
      [...cartao.querySelectorAll("p")].map(
        (paragrafo) => paragrafo.textContent ?? "",
      ),
    ]),
  );
}

// As linhas da tabela de dados da série, pela legenda da figura.
export function lerSerie(
  secao: Element | undefined,
  rotulo: string,
): string[][] {
  const figura = [...(secao?.querySelectorAll("figure") ?? [])].find(
    (elemento) => elemento.querySelector("figcaption")?.textContent === rotulo,
  );
  return [...(figura?.querySelectorAll("tbody tr") ?? [])].map((linha) =>
    [...linha.querySelectorAll("td")].map((celula) => celula.textContent ?? ""),
  );
}

export function lerValorMoeda(texto: string): number {
  return Number(texto.replace(/[^\d,]/g, "").replace(",", "."));
}
