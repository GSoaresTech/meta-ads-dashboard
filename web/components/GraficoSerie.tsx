"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  formatarEixoMetrica,
  formatarMetrica,
  formatarPeriodo,
  formatarRotuloEixo,
  type UnidadeMetrica,
} from "@/lib/formatacao";
import type { Granularidade } from "@/lib/periodo";
import type { PontoSerie } from "@/lib/resumo-desempenho";

const ALTURA_PX = 200;
const DISTANCIA_MINIMA_ROTULOS_PX = 24;
const COR_SERIE = "#2a78d6";
const OPACIDADE_AREA = 0.1;
const COR_GRADE = "#e3e2de";
const COR_TEXTO = "#52514e";

const ESTILO_EIXO = { fontSize: 12, fill: COR_TEXTO };

interface Propriedades {
  rotulo: string;
  unidade: UnidadeMetrica;
  moeda: string;
  granularidade: Granularidade;
  pontos: PontoSerie[];
}

// Só o desenho fica no navegador: os pontos chegam prontos do servidor, e a
// credencial nunca passa por aqui. Uma métrica por gráfico, porque moeda e
// quantidade não dividem um eixo.
export function GraficoSerie({
  rotulo,
  unidade,
  moeda,
  granularidade,
  pontos,
}: Readonly<Propriedades>) {
  return (
    <ResponsiveContainer width="100%" height={ALTURA_PX}>
      <AreaChart
        data={pontos}
        margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
      >
        <CartesianGrid vertical={false} stroke={COR_GRADE} />
        <XAxis
          dataKey="inicio"
          tickFormatter={(inicio: string) =>
            formatarRotuloEixo(inicio, granularidade)
          }
          minTickGap={DISTANCIA_MINIMA_ROTULOS_PX}
          tick={ESTILO_EIXO}
          tickLine={false}
          axisLine={{ stroke: COR_GRADE }}
        />
        <YAxis
          width="auto"
          tickFormatter={(valor: number) =>
            formatarEixoMetrica(valor, unidade, moeda)
          }
          tick={ESTILO_EIXO}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip
          separator=": "
          itemStyle={{ color: COR_TEXTO }}
          formatter={(valor) => [
            formatarMetrica(
              typeof valor === "number" ? valor : null,
              unidade,
              moeda,
            ),
            rotulo,
          ]}
          labelFormatter={(_, itens) => {
            const ponto = itens[0]?.payload as PontoSerie | undefined;
            return ponto ? formatarPeriodo(ponto.inicio, ponto.fim) : "";
          }}
        />
        <Area
          dataKey="valor"
          type="linear"
          stroke={COR_SERIE}
          strokeWidth={2}
          fill={COR_SERIE}
          fillOpacity={OPACIDADE_AREA}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
