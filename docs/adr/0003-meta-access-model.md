# ADR-0003: Acesso às contas da Meta e guarda do token

- Status: Aceito
- Data: 29/10/2026

## Contexto

As extrações usam um App da Meta da BM do operador. A BM já é verificada. Pela nossa experiência com apps semelhantes, contas de anúncio dentro da BM podem ser lidas sem publicar o app. É preciso escolher como cada empresa concede acesso às contas e onde fica o token. Os níveis de acesso, os limites de taxa e os tipos de token da Meta estão nas restrições R-13 a R-16 do `docs/REQUIREMENTS.md`.

## Opções consideradas

### Modelo de acesso

| Opção | Prós | Contras |
|---|---|---|
| **(a) Contas dentro da BM do operador** (próprias ou compartilhadas pela BM da empresa como parceira), lidas por um System User do operador | Um token serve a todas as empresas. O cadastro de empresa não envolve fluxo de login nem código. Corresponde à nossa experiência com apps semelhantes | Pela documentação, o nível Limited serve "só para desenvolvimento" (R-13). Contas compartilhadas podem contar como "de outras pessoas" e exigir acesso avançado (R-14; Q-02) |
| (b) Facebook Login for Business: cada empresa autoriza o app e há um token por empresa | Delegação explícita por empresa | Exige acesso avançado via App Review e um fluxo de login web, o que contraria o painel sem login (ADR-0004). Multiplica os tokens a guardar |

### Token

| Opção | Prós | Contras |
|---|---|---|
| **Sem validade, em secret do GitHub Actions** | Simples; nenhuma renovação pode falhar | Se vazar, dá leitura de todas as contas até ser revogado. A Meta recomenda o token de 60 dias (R-16) |
| 60 dias com renovação automática, guardado no Supabase Vault | Recomendado pela Meta; a exposição fica limitada no tempo | Uma falha de renovação não percebida para a extração |

## Decisão

- **Acesso**: opção (a). As contas de anúncio de cada empresa ficam dentro da BM do operador, por propriedade ou compartilhamento como parceira, e são atribuídas a um System User do operador com a permissão `ads_read`. O app começa sem publicação, no nível Limited.
- **Token**: System User sem validade, guardado como secret do repositório no GitHub Actions e lido só pela ETL. A rotação é manual, pelo runbook, e a revogação é imediata se houver suspeita de vazamento.

## Consequências

- O cadastro de empresa (ADR-0002) não gera token novo nem secret novo.
- A ETL controla o ritmo pelos cabeçalhos de uso e prefere consultas agregadas (nível de anúncio com `time_increment=1` numa única chamada paginada) a muitas chamadas pequenas (RF-08).
- **Gatilho para pedir acesso avançado a `ads_read` e o nível Full**: erros de acesso negado em contas compartilhadas, ou erros de limite de taxa em mais de 5% das execuções de um mês. A BM verificada já cumpre o pré-requisito de verificação.
- O link "ver publicação" (RF-39) pode exigir permissões de Página e de Instagram além de `ads_read` (Q-06).

## Referências

Consultadas em 29/10/2026.
- https://developers.facebook.com/docs/marketing-api/access
- https://developers.facebook.com/docs/permissions/reference/ads_read
- https://developers.facebook.com/docs/marketing-api/overview/rate-limiting
- https://developers.facebook.com/docs/marketing-api/businessmanager/systemuser/install-apps-and-generate-tokens
- https://developers.facebook.com/docs/facebook-login/facebook-login-for-business
