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

// A ajuda "o que é isso?" de uma métrica (ADR-0020): o texto do controle, que
// o leitor de tela lê com o rótulo oculto, e a explicação que ela abre.
export interface Ajuda {
  controle: string;
  explicacao: string;
}

export interface MetricaExibida {
  rotulo: string;
  ajuda: Ajuda | undefined;
}

// As colunas da lista de campanhas que trazem uma métrica do catálogo.
const COLUNAS_METRICA = ["Resultado principal", "Custo por resultado"];

// O outro details de uma série é o "Ver os dados", com a tabela.
export function lerAjuda(elemento: Element): Ajuda | undefined {
  const ajuda = [...elemento.querySelectorAll("details")].find(
    (detalhe) => detalhe.querySelector("table") === null,
  );
  return (
    ajuda && {
      controle: ajuda.querySelector("summary")?.textContent ?? "",
      explicacao: ajuda.querySelector("p")?.textContent ?? "",
    }
  );
}

// O texto que a célula mostra, sem o da ajuda que vai junto.
export function lerTextoSemAjuda(elemento: Element): string {
  const copia = elemento.cloneNode(true) as Element;
  copia.querySelectorAll("details").forEach((ajuda) => ajuda.remove());
  return copia.textContent ?? "";
}

function lerCelulasMetrica(tabela: Element): MetricaExibida[] {
  const colunas = [...tabela.querySelectorAll("thead th")].map(
    (cabecalho) => cabecalho.textContent ?? "",
  );
  return [...tabela.querySelectorAll("tbody tr")].flatMap((linha) =>
    [...linha.children]
      .filter((_, indice) => COLUNAS_METRICA.includes(colunas[indice]))
      // A campanha sem resultado no catálogo não tem métrica na célula.
      .filter((celula) => lerTextoSemAjuda(celula).includes(": "))
      .map((celula) => ({
        rotulo: lerTextoSemAjuda(celula).split(": ")[0],
        ajuda: lerAjuda(celula),
      })),
  );
}

// Cada métrica que a página mostra, nos cartões, nas séries e na lista de
// campanhas, com o rótulo que a pessoa lê e a ajuda dela (RF-30).
export function listarMetricasExibidas(documento: Document): MetricaExibida[] {
  const ler = (seletor: string, rotulo: string) =>
    [...documento.querySelectorAll(`main ${seletor}`)].map((elemento) => ({
      rotulo: elemento.querySelector(rotulo)?.textContent ?? "",
      ajuda: lerAjuda(elemento),
    }));
  const tabelas = [...documento.querySelectorAll("main table")].filter(
    (tabela) => tabela.closest("figure") === null,
  );

  return [
    ...ler("article", "h3"),
    ...ler("figure", "figcaption"),
    ...tabelas.flatMap(lerCelulasMetrica),
  ];
}
