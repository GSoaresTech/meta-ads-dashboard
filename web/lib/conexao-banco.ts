import { parse } from "pg-connection-string";

// Sem sslmode na URL, o node-postgres não cifra a conexão, ao contrário do
// libpq da ETL, e o token de acesso iria ao banco em texto puro. Só o banco
// local, na mesma máquina, dispensa o TLS.
const HOSTS_LOCAIS = new Set(["127.0.0.1", "localhost"]);

// A leitura é a do próprio node-postgres, para que a regra valha para o que
// ele de fato fará com a URL. A mensagem não leva a URL, que tem a senha.
export function exigirTls(urlBanco: string): void {
  const { host, ssl } = parse(urlBanco);
  if (!ssl && !HOSTS_LOCAIS.has(host ?? "")) {
    throw new Error(
      "URL_BANCO sem TLS: fora do banco local, a URL precisa de sslmode",
    );
  }
}
