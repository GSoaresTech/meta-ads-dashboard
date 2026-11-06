# ADR-0010: Provisionamento do Supabase e da Vercel

- Status: Aceito
- Data: 03/11/2026
- Atualizado em: 06/11/2026, com a região das funções da Vercel

## Contexto

O banco roda num projeto Supabase em plano pago (R-01), e o painel, na Vercel Hobby (ADR-0001). Ao provisionar as duas plataformas, três pontos ficaram em aberto:
- A organização Pro do Supabase é compartilhada com outro projeto, que não pertence a este repositório. O disco é cotado por projeto, mas Storage e egress são cotados pela organização. Quando ela passa da cota, a restrição por uso excessivo em geral atinge todos os projetos dela (R-28).
- Como as migrations chegam ao banco de produção.
- Que variáveis o projeto da Vercel recebe antes de existir o papel de banco restrito do painel (ADR-0004).

## Opções consideradas

### Cotas na organização compartilhada

| Opção | Prós | Contras |
|---|---|---|
| **Parcela fixa da cota da organização reservada a este projeto** | O alerta do RF-52 usa só o uso que este projeto consegue medir. Os dois projetos não disputam a mesma folga sem perceber | A parcela do outro projeto é respeitada fora deste repositório. Uma parcela mal calibrada antecipa ou atrasa o alerta |
| Comparar o uso total da organização com a cota inteira | Mede exatamente o que gera cobrança e restrição | A ETL precisaria de uma credencial com acesso à organização inteira, inclusive ao outro projeto |
| Organização própria para este projeto | Cotas e restrições isoladas | Outra assinatura do plano Pro |

### Aplicação de migrations em produção

| Opção | Prós | Contras |
|---|---|---|
| **`supabase db push --linked` manual, depois do merge** | Nenhuma credencial com poder sobre o schema fica no Actions. O `--dry-run` mostra antes o que será aplicado | Depende de alguém rodar o comando, e a `main` pode ficar à frente do banco por algum tempo |
| Workflow com disparo manual | Cada aplicação fica registrada no Actions | Exige guardar em secrets de um repositório público (ADR-0008) a senha do banco e o token pessoal do Supabase CLI, que dá acesso a todos os projetos da conta, inclusive ao outro projeto da organização |
| Workflow a cada merge na `main` | O banco acompanha a `main` sem intervenção | Os mesmos secrets, e uma migration com defeito chega à produção sem pausa para conferência |

### Variáveis do projeto da Vercel

| Opção | Prós | Contras |
|---|---|---|
| **Nenhuma até existir o papel restrito do painel** | O painel nunca recebe credencial com mais privilégio do que precisa | Nenhum, enquanto o painel não lê o banco |
| String de conexão do usuário `postgres` desde já | O painel pode conectar ao banco mais cedo | Dá ao painel acesso total ao banco, contra o papel restrito do ADR-0004 |

## Decisão

- **Organização**: compartilhada, com o spend cap ligado. Reservamos a este projeto **30%** das cotas de Storage, egress e egress em cache da organização. O disco de 8 GB é todo deste projeto. As cotas e a parcela ficam nas constantes `COTA_*` e `PARCELA_COTA_ORGANIZACAO` da configuração da ETL, com a data da consulta.
- **Migrations**: aplicadas manualmente com `supabase db push --linked`, a partir da `main` atualizada depois do merge do PR que traz a migration. Antes, conferimos o projeto ligado e rodamos o `--dry-run`. Os comandos ficam no `CLAUDE.md` §2.
- **Vercel**: projeto ligado ao repositório, com Root Directory `web` e deploy de produção a partir da `main`. As funções rodam em `gru1`, em São Paulo, ao lado do banco, pelo `web/vercel.json`: na região padrão, `iad1`, em Washington, cada consulta ao banco cruzaria o continente. Não há variáveis até o papel restrito do painel existir. Quando ele existir, a conexão do painel entra na variável de servidor `URL_BANCO`, do tipo Secret, sem o prefixo `NEXT_PUBLIC_`. A URL leva `sslmode`: sem ele, o node-postgres não cifra a conexão, ao contrário do libpq da ETL, e o painel recusa uma URL sem TLS fora do banco local. Com `sslmode=require` sozinho, o node-postgres verifica o certificado como no `verify-full`; com `uselibpqcompat=true`, segue o libpq.
- **ETL**: o secret `URL_BANCO` do Actions aponta para o pooler de sessão (R-02).

## Consequências

- Um excesso do outro projeto pode restringir este, e o alerta do RF-52 não o enxerga. O spend cap evita a cobrança, mas não a restrição. Acompanhamos o uso total na página de uso da organização no Supabase.
- O crédito de computação do Pro cobre uma instância Micro, e o spend cap não cobre computação (R-28). Com dois projetos na organização, a fatura mensal fica acima do preço base do plano.
- O token do Supabase CLI de quem aplica migrations também enxerga o outro projeto. Por isso, conferir o projeto ligado faz parte do procedimento.
- A Vercel publica a `main` logo após o merge, antes do `db push`. Por isso, uma mudança do painel que dependa de schema novo entra num PR posterior ao da migration, depois de a migration estar aplicada em produção.
- **Gatilhos de revisão**: mais de uma pessoa aplicando migrations leva a um workflow com disparo manual e ambiente protegido. Se o outro projeto passar da parcela dele ou se sofrermos uma restrição causada por ele, avaliamos uma organização própria.

## Referências

- https://vercel.com/docs/functions/configuring-functions/region (consultado em 06/11/2026)

Consultadas em 03/11/2026.
- https://supabase.com/pricing
- https://supabase.com/docs/guides/platform/billing-on-supabase
- https://supabase.com/docs/guides/platform/billing-faq
- https://supabase.com/docs/guides/platform/cost-control
- https://supabase.com/docs/guides/platform/manage-your-usage/disk-size
- https://supabase.com/docs/guides/platform/manage-your-usage/storage-size
- https://supabase.com/docs/guides/platform/manage-your-usage/egress
- https://supabase.com/docs/guides/deployment/database-migrations
- https://supabase.com/docs/reference/cli/supabase-db-push
- https://supabase.com/docs/reference/cli/supabase-link
- https://supabase.com/docs/guides/database/connecting-to-postgres
- https://vercel.com/docs/git
- https://vercel.com/docs/builds/configure-a-build
- https://vercel.com/docs/environment-variables
