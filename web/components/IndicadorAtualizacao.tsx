import { LIMITE_ATUALIZACAO_HORAS } from "@/lib/atualizacao";
import { formatarInstante, formatarNumero } from "@/lib/formatacao";

import estilos from "./IndicadorAtualizacao.module.css";

interface Propriedades {
  // Nulo enquanto a empresa não teve carga bem-sucedida.
  ultimaCargaEm: Date | null;
  // O fuso em que a página conta o "hoje" (RF-26).
  fuso: string;
  desatualizada: boolean;
  // O intervalo exibido inclui hoje.
  parcial: boolean;
}

// RF-28: o horário da última carga bem-sucedida, o aviso de atraso e a marca
// dos dados de hoje, que ainda mudam a cada carga.
export function IndicadorAtualizacao({
  ultimaCargaEm,
  fuso,
  desatualizada,
  parcial,
}: Readonly<Propriedades>) {
  return (
    <section aria-label="Atualização dos dados" className={estilos.indicador}>
      <p className={estilos.horario}>
        {ultimaCargaEm === null ? (
          "Nenhuma atualização concluída até agora."
        ) : (
          <>
            Atualizado em{" "}
            <time dateTime={ultimaCargaEm.toISOString()}>
              {formatarInstante(ultimaCargaEm, fuso)}
            </time>
            .
          </>
        )}
      </p>
      {desatualizada && (
        <p>
          <span className={estilos.etiqueta}>Dados desatualizados</span> Nenhuma
          atualização nas últimas {formatarNumero(LIMITE_ATUALIZACAO_HORAS)}{" "}
          horas: os números podem não mostrar o que aconteceu desde então.
        </p>
      )}
      {parcial && (
        <p>
          <span className={estilos.etiqueta}>Dados parciais</span> O dia de hoje
          ainda está em andamento, e os números dele mudam a cada atualização.
        </p>
      )}
    </section>
  );
}
