import { exigirAcesso } from "@/lib/acesso";

export default async function PaginaInicial() {
  await exigirAcesso();

  return (
    <main>
      <h1>Painel de Meta Ads</h1>
    </main>
  );
}
