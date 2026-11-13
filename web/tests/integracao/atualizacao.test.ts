// @vitest-environment jsdom
import type { Client } from "pg";
import { afterAll, beforeAll, describe, expect, test } from "vitest";

import { formatarInstante } from "@/lib/formatacao";
import { montarCaminho } from "@/lib/navegacao";

import {
  cadastrarEntidades,
  conectarBancoLocal,
  criarMassaAcesso,
  removerEntidades,
  removerMassaAcesso,
  type IdsEntidades,
  type MassaAcesso,
} from "./banco-local";
import { requisitar } from "./http";

// Prova por HTTP o indicador de atualização (RF-28): o horário da última carga
// bem-sucedida, o aviso de atraso depois de 3 h e a marca de dados parciais
// no intervalo que inclui hoje. As cargas são gravadas em relação ao relógio
// do banco, o mesmo da máquina do servidor, com folga de 1 h para cada lado
// do limite; a fronteira exata fica no teste unitário, com relógio fixo.
const FUSO = "America/Sao_Paulo";
const CONTA = "Conta Exemplo Atualização";
const AVISO_ATRASO = "Dados desatualizados";
const MARCA_PARCIAL = "Dados parciais";

let cliente: Client;
let massa: MassaAcesso;
let massaSemCarga: MassaAcesso;
let ids: IdsEntidades;
let cargaRecente: Date;
let cargaAntiga: Date;

// Uma execução terminada há tantas horas, com o status pedido. Devolve o fim,
// que é o instante da carga quando ela é bem-sucedida.
async function registrarExecucao(
  empresaId: string,
  status: "sucesso" | "falha",
  horasAtras: number,
): Promise<Date> {
  const { rows } = await cliente.query<{ terminado_em: Date }>(
    `INSERT INTO normalizado.execucao_carga
       (empresa_id, tipo, status, iniciado_em, terminado_em, erro)
     VALUES (
       $1, 'horaria', $2,
       now() - make_interval(hours => $3::int, mins => 5),
       now() - make_interval(hours => $3::int),
       CASE WHEN $2 = 'falha' THEN 'erro de teste' END
     )
     RETURNING terminado_em`,
    [empresaId, status, horasAtras],
  );
  return rows[0].terminado_em;
}

beforeAll(async () => {
  cliente = await conectarBancoLocal();
  massa = await criarMassaAcesso(cliente, "Atualização");
  massaSemCarga = await criarMassaAcesso(cliente, "Atualização Sem Carga");

  ids = await cadastrarEntidades(cliente, massa.empresaA, [
    {
      nome: CONTA,
      fusoHorario: FUSO,
      moeda: "BRL",
      campanhas: [],
    },
  ]);

  // Na empresa A, a falha mais recente não conta como carga.
  cargaRecente = await registrarExecucao(massa.empresaA, "sucesso", 1);
  await registrarExecucao(massa.empresaA, "falha", 0);
  cargaAntiga = await registrarExecucao(massa.empresaB, "sucesso", 4);
  await registrarExecucao(massaSemCarga.empresaA, "falha", 0);
});

afterAll(async () => {
  const empresas = [
    massa.empresaA,
    massa.empresaB,
    massaSemCarga.empresaA,
    massaSemCarga.empresaB,
  ];
  await removerEntidades(cliente, empresas);
  await removerMassaAcesso(cliente, massa);
  await removerMassaAcesso(cliente, massaSemCarga);
  await cliente.end();
});

// O texto do indicador, que é uma região própria da página.
async function lerIndicador(
  caminho: string,
  credencial: string,
  periodo: string,
): Promise<{ texto: string; instante: string | null }> {
  const endereco = `${caminho}?periodo=${periodo}&granularidade=dia`;
  const resposta = await requisitar(endereco, { credencial });
  expect(resposta.status, endereco).toBe(200);
  const documento = new DOMParser().parseFromString(
    await resposta.text(),
    "text/html",
  );
  const indicador = documento.querySelector(
    'section[aria-label="Atualização dos dados"]',
  );
  expect(indicador, endereco).not.toBeNull();
  return {
    texto: indicador?.textContent ?? "",
    instante:
      indicador?.querySelector("time")?.getAttribute("datetime") ?? null,
  };
}

describe("RF-28: horário da última carga bem-sucedida", () => {
  test("o Geral mostra o fim da última carga bem-sucedida no fuso da conta, e não a falha mais recente", async () => {
    const { texto, instante } = await lerIndicador(
      montarCaminho(massa.empresaA, "geral", null),
      massa.tokenA,
      "ontem",
    );

    expect(instante).toBe(cargaRecente.toISOString());
    expect(texto).toContain(formatarInstante(cargaRecente, FUSO));
  });

  test("a página da conta mostra o mesmo horário", async () => {
    const { instante } = await lerIndicador(
      montarCaminho(massa.empresaA, "conta", ids[CONTA]),
      massa.tokenA,
      "ontem",
    );

    expect(instante).toBe(cargaRecente.toISOString());
  });
});

describe('RF-28: aviso "dados desatualizados" depois de 3 h', () => {
  test("a carga de 1 h atrás não tem aviso", async () => {
    const { texto } = await lerIndicador(
      montarCaminho(massa.empresaA, "geral", null),
      massa.tokenA,
      "ontem",
    );

    expect(texto).not.toContain(AVISO_ATRASO);
  });

  test("a carga de 4 h atrás mostra o aviso, com o horário dela", async () => {
    const { texto, instante } = await lerIndicador(
      montarCaminho(massa.empresaB, "geral", null),
      massa.tokenB,
      "ontem",
    );

    expect(instante).toBe(cargaAntiga.toISOString());
    expect(texto).toContain(AVISO_ATRASO);
  });

  test("a empresa sem carga bem-sucedida mostra o aviso, sem horário", async () => {
    const { texto, instante } = await lerIndicador(
      montarCaminho(massaSemCarga.empresaA, "geral", null),
      massaSemCarga.tokenA,
      "ontem",
    );

    expect(instante).toBeNull();
    expect(texto).toContain("Nenhuma atualização concluída");
    expect(texto).toContain(AVISO_ATRASO);
  });
});

describe("RF-28: marca de dados parciais no intervalo que inclui hoje", () => {
  test.each(["hoje", "este-mes", "este-ano"])(
    "o atalho %s, que vai até hoje, mostra a marca",
    async (periodo) => {
      const { texto } = await lerIndicador(
        montarCaminho(massa.empresaA, "conta", ids[CONTA]),
        massa.tokenA,
        periodo,
      );

      expect(texto).toContain(MARCA_PARCIAL);
    },
  );

  test.each(["ontem", "ultimos-7-dias", "mes-passado"])(
    "o atalho %s, que termina antes de hoje, não mostra a marca",
    async (periodo) => {
      const { texto } = await lerIndicador(
        montarCaminho(massa.empresaA, "conta", ids[CONTA]),
        massa.tokenA,
        periodo,
      );

      expect(texto).not.toContain(MARCA_PARCIAL);
    },
  );
});
