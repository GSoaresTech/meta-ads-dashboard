import Link from "next/link";

import { formatarData } from "@/lib/formatacao";
import {
  montarEndereco,
  PARAMETROS,
  PERIODO_INTERVALO,
  type Selecao,
} from "@/lib/navegacao";
import {
  ATALHOS,
  GRANULARIDADES,
  type Atalho,
  type Granularidade,
  type Intervalo,
} from "@/lib/periodo";

const ROTULOS_ATALHO: Record<Atalho, string> = {
  hoje: "Hoje",
  ontem: "Ontem",
  "ultimos-7-dias": "Últimos 7 dias",
  "ultimos-30-dias": "Últimos 30 dias",
  "este-mes": "Este mês",
  "mes-passado": "Mês passado",
  "este-ano": "Este ano",
};

const ROTULOS_GRANULARIDADE: Record<Granularidade, string> = {
  dia: "Dia",
  semana: "Semana",
  mes: "Mês",
  ano: "Ano",
};

interface Propriedades {
  // O caminho da página atual, para onde toda escolha volta.
  caminho: string;
  selecao: Selecao;
  // O intervalo já resolvido no fuso da entidade em foco.
  intervalo: Intervalo;
}

// Links e um formulário GET, sem estado no cliente: a URL é o estado, e
// voltar e recarregar o preservam (RF-24).
export function SeletorPeriodo({
  caminho,
  selecao,
  intervalo,
}: Readonly<Propriedades>) {
  return (
    <section aria-label="Período e granularidade">
      <p>
        <time dateTime={intervalo.inicio}>
          {formatarData(intervalo.inicio)}
        </time>{" "}
        a <time dateTime={intervalo.fim}>{formatarData(intervalo.fim)}</time>
      </p>

      <nav aria-label="Atalhos de período">
        <ul>
          {ATALHOS.map((atalho) => (
            <li key={atalho}>
              <Link
                href={montarEndereco(caminho, { ...selecao, periodo: atalho })}
                aria-current={selecao.periodo === atalho ? "true" : undefined}
              >
                {ROTULOS_ATALHO[atalho]}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      <form method="get" action={caminho} aria-label="Intervalo livre">
        <input
          type="hidden"
          name={PARAMETROS.periodo}
          value={PERIODO_INTERVALO}
        />
        <input
          type="hidden"
          name={PARAMETROS.granularidade}
          value={selecao.granularidade}
        />
        <label>
          Início
          <input
            type="date"
            name={PARAMETROS.inicio}
            defaultValue={intervalo.inicio}
            required
          />
        </label>
        <label>
          Fim
          <input
            type="date"
            name={PARAMETROS.fim}
            defaultValue={intervalo.fim}
            required
          />
        </label>
        <button type="submit">Aplicar intervalo</button>
      </form>

      <nav aria-label="Granularidade">
        <ul>
          {GRANULARIDADES.map((granularidade) => (
            <li key={granularidade}>
              <Link
                href={montarEndereco(caminho, { ...selecao, granularidade })}
                aria-current={
                  selecao.granularidade === granularidade ? "true" : undefined
                }
              >
                {ROTULOS_GRANULARIDADE[granularidade]}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </section>
  );
}
