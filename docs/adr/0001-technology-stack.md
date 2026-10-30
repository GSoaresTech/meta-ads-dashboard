# ADR-0001: Stack tecnológica

- Status: Aceito
- Data: 29/10/2026
- Atualizado em: 30/10/2026, com o executor de testes do painel

## Contexto

O produto é um painel de análise de Meta Ads para pessoas de negócio, multiempresa, com tratamento de dados intensivo. A base foi definida com a stack Supabase (Postgres), Vercel para o painel e um App da Meta na BM. Pontos decididos neste ADR:

- Onde roda a ETL e em que linguagem;
- O framework do painel;
- O plano de hospedagem;
- A nomenclatura no código;
- O executor de testes do painel.

Requisitos que pesam na decisão:
- Atualização de hora em hora (RF-06);
- Carga histórica de até 37 meses por conta, que pode exigir jobs assíncronos da Meta de até 1 h (R-18, R-19);
- Transações explícitas sobre várias tabelas (CLAUDE.md §6);
- Custo de infraestrutura previsível (RNF-23).

## Opções consideradas

### Ambiente da ETL

| Opção | Prós | Contras |
|---|---|---|
| **(a) Python no GitHub Actions**, com conexão direta ao Postgres | Jobs de até 6 h (R-07) comportam a carga histórica e os jobs assíncronos. Bom ecossistema de tratamento de dados. Transação explícita com `psycopg` pelo pooler de sessão (IPv4, com advisory lock) (R-02). Minutos gratuitos em repositório público | Duas linguagens no repositório. O agendamento pode atrasar ou descartar jobs no pico (R-08) |
| (b) TypeScript em Supabase Edge Functions + `pg_cron` | Mesma linguagem do painel, tudo dentro do Supabase | 400 s de relógio e 2 s de CPU por execução (R-03): a carga histórica e os jobs assíncronos exigiriam fatiar tudo numa máquina de estados. Transação multitabela só via função `plpgsql` |
| (c) Funções e cron da Vercel | Mesmo deploy do painel | No Hobby, o cron roda no máximo uma vez por dia, com ±59 min de precisão, e as funções duram até 300 s (R-06), o que é incompatível com a atualização horária |

### Hospedagem do painel

| Opção | Prós | Contras |
|---|---|---|
| **Vercel Hobby** | Custo zero; integração com a nossa conta do GitHub | Os termos restringem o plano a uso pessoal e não comercial, e definem uso comercial como ganho financeiro de qualquer pessoa envolvida no projeto (R-04). Não há proteção por senha (R-05) |
| Vercel Pro | Cumpre os termos em uso comercial; cron por minuto; funções até 800 s | US$ 20/mês por assento de desenvolvedor (R-05) |
| Outra hospedagem | — | Sai da arquitetura que definimos para o projeto |

### Nomenclatura no código

| Opção | Prós | Contras |
|---|---|---|
| **Português no padrão de cada linguagem** (camelCase em TS, snake_case em Python e SQL), com campos da Meta preservados em `bruto` e traduzidos a partir de `normalizado` | Segue o idioma de cada ecossistema e o lint padrão; o modelo de dados fica todo em português | Exige um mapa de tradução de campos |
| snake_case em tudo | Uniforme | Contraria o lint e o ecossistema TS/React |
| Nomes da Meta até `analitico` | Menos mapeamento | Mistura idiomas no modelo; contraria a regra de código em português |

### Executor de testes do painel

O painel precisa de testes de unidade, como os da formatação pt-BR com a cobertura do RNF-19, e de componente. A documentação do Next.js traz guias para Vitest e Jest nesse papel, e os dois têm a mesma limitação: não executam Server Components `async`, para os quais ela recomenda testes de ponta a ponta.

| Opção | Prós | Contras |
|---|---|---|
| **Vitest**, com Testing Library e jsdom | TypeScript, JSX e ESM sem configuração de transpilação, porque o Vite já os transforma. Os aliases do `tsconfig.json` são resolvidos pelo próprio Vite (`resolve.tsconfigPaths`). A API é compatível com a do Jest, e a cobertura vem de um pacote oficial do próprio Vitest | O Vite entra só para os testes, ao lado do Turbopack do build. O jsdom 30 exige Node 22.22.2, 24.15 ou 26 em diante |
| Jest, com `next/jest`, Testing Library e jsdom | Transforma com o compilador do Next e carrega o `next.config` e os `.env` | O suporte a ESM ainda é experimental. Exige pacotes e configuração a mais (`jest-environment-jsdom`, `ts-node`, `@types/jest`), além de repetir os aliases no `moduleNameMapper` |
| Playwright | Testa o painel rodando, inclusive Server Components `async` e cabeçalhos HTTP | É ponta a ponta: exige navegador e servidor, e não substitui os testes de unidade |

## Decisão

- **ETL**: Python no GitHub Actions, em workflows agendados. Conexão por `psycopg` ao pooler de sessão do Supabase.
- **Banco**: Supabase (Postgres). O schema é versionado por migrations do Supabase CLI e testado com pgTAP (`supabase test db`).
- **Painel**: Next.js com TypeScript `strict`, gráficos com Recharts e acesso ao banco só no servidor.
- **Hospedagem**: Vercel Hobby.
- **Testes do painel**: Vitest com Testing Library e jsdom, para testes de unidade e de componente. Os testes de ponta a ponta ficam fora desta decisão.
- **Nomenclatura**: português no padrão de cada linguagem. O mapa de tradução dos campos da Meta é único e versionado.
- **Autenticação**: nenhuma; o acesso funciona como descrito no ADR-0004.

## Consequências

- Duas cadeias de ferramentas, Python e TypeScript, cada uma com lint, formatação e testes próprios na CI.
- **Risco (Q-01)**: pelos termos, o que define o uso comercial no Vercel Hobby é haver ganho financeiro de quem desenvolve ou opera o projeto, não de quem é a conta. Gatilho de revisão: primeiro cliente pagante ou qualquer remuneração ligada ao projeto. A saída é migrar para o Pro, sem mudança de código.
- Server Components `async` não rodam no Vitest. Eles só são cobertos por testes de ponta a ponta, cuja ferramenta ainda não foi decidida.

## Referências

Consultadas em 29/10/2026; detalhes em `docs/REQUIREMENTS.md` §4.1 e §9.
- https://supabase.com/docs/guides/functions/limits
- https://supabase.com/docs/guides/database/connecting-to-postgres
- https://vercel.com/docs/limits/fair-use-guidelines
- https://vercel.com/docs/cron-jobs/usage-and-pricing
- https://vercel.com/docs/functions/limitations
- https://docs.github.com/en/actions/reference/limits
- https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows

Executor de testes do painel, consultadas em 30/10/2026:
- https://nextjs.org/docs/app/guides/testing
- https://nextjs.org/docs/app/guides/testing/vitest
- https://nextjs.org/docs/app/guides/testing/jest
- https://jestjs.io/docs/ecmascript-modules
- https://vite.dev/config/shared-options
