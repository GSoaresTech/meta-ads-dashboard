# Diretrizes de desenvolvimento

Regras de desenvolvimento deste repositório. Valem para qualquer sessão, humana ou assistida. Regras marcadas [INEGOCIÁVEL] não admitem exceção.

## 1. Visão do projeto

Este é um painel de análise das campanhas de Meta Ads (Facebook e Instagram) para pessoas de negócio, não para especialistas em mídia. O sistema é genérico e multiempresa, onde nasce sem cliente, e cada empresa entra como operação de dados. Os números aparecem em dois eixos combináveis, sempre consistentes entre os níveis:
- Entidade: Geral → conta → campanha → anúncio;
- Tempo: dia ou período livre → semana ISO → mês → ano.

Leitura intuitiva significa rótulos de negócio, explicação de cada métrica na tela, resultado principal conforme o objetivo da campanha e formato brasileiro.

Cada informação vive em um só lugar; os demais apontam para ela:
- `docs/REQUIREMENTS.md`: o que o sistema deve fazer. Tem os RF e RNF com critérios de aceite, o mapa de navegação, o catálogo de métricas, as restrições de plataforma verificadas e as questões em aberto.
- `docs/adr/`: por que cada decisão foi tomada, um ADR por decisão.
- Este arquivo: como desenvolver.
- Issues e milestones do GitHub: as tarefas (§11.4).

## 2. Stack

Decidida no ADR-0001:
- Banco: Supabase (Postgres). O schema muda só por migrations do Supabase CLI em `supabase/migrations/`.
- ETL: Python, executado por workflows agendados do GitHub Actions. Conecta ao Postgres pelo pooler de sessão do Supabase (IPv4, porta 5432) com `psycopg`.
- Painel: Next.js com TypeScript (modo `strict`), hospedado na Vercel (Hobby), com gráficos em Recharts. O banco é acessado só no servidor.
- Fonte de dados: Meta Marketing API (Insights), lida por um System User da BM do operador. A versão da API fica numa única constante.
- Testes: `pytest` na ETL, pgTAP com `supabase test db` no banco e Vitest com Testing Library no painel.

Banco local (exige o Supabase CLI e o Docker), na raiz do repositório:
- `supabase start`: sobe o Supabase local com `supabase/config.toml`.
- `supabase test db`: roda os testes pgTAP de `supabase/tests/` contra o banco local.
- `supabase stop`: para o Supabase local.

ETL (exige Python 3.13 ou mais novo), na raiz do repositório:
- `python3 -m venv .venv`: cria o ambiente virtual, fora do Git.
- `.venv/bin/python -m pip install -e . --group dev`: instala a ETL e as ferramentas fixadas no `pyproject.toml` (exige pip 25.1 ou mais novo, por causa de `--group`).
- `.venv/bin/ruff check`: lint, com limite de complexidade (RNF-21) e type hints obrigatórios.
- `.venv/bin/ruff format --check`: confere a formatação; sem `--check`, formata.
- `.venv/bin/python -m pytest`: roda os testes de `tests/`.
- `.venv/bin/python -m coverage run -m pytest`: roda os mesmos testes medindo a cobertura do pacote `etl`.
- `.venv/bin/python -m coverage report`: mostra a cobertura medida e falha abaixo de 80% (RNF-19).

Painel (exige o Node.js na faixa do campo `engines` do `web/package.json`, com o npm que vem junto), em `web/`:
- `npm ci`: instala as dependências exatamente como fixadas no `package-lock.json`.
- `npm run dev`: sobe o painel local em `http://localhost:3000`.
- `npm run lint`: lint com ESLint, com limite de complexidade (RNF-21).
- `npm run format:check`: confere a formatação com Prettier; `npm run format` formata.
- `npm run build`: build de produção, que também faz a checagem de tipos.
- `npm test`: roda os testes do painel com o Vitest.
- `npm run test:coverage`: roda os testes medindo a cobertura do módulo de formatação (`lib/formatacao*`) e falha abaixo de 80% (RNF-19).

Não invente comandos; registre-os aqui quando existirem.

## 3. Arquitetura de dados

```
Meta API ──extrair──▶ bruto ──transformar──▶ normalizado ──views/funções──▶ analitico ──▶ painel (servidor)
```

- **`bruto`**: guarda a resposta da API como recebida (`jsonb`), com os nomes de campo da Meta. A retenção é curta (ADR-0005); para recuperar mais que isso, extraia de novo.
- **`normalizado`**: modelo em 3FN, com chaves e restrições, nomes em português. É a fonte da verdade.
- **`analitico`**: views e funções lidas pelo painel; é o único lugar com desnormalização. O painel nunca lê `bruto` nem `normalizado`.

Toda execução, seja horária, diária ou histórica (ADR-0005), segue a ordem extrair → transformar → carregar:
1. **Extrair**: faz o I/O de rede, fora de qualquer transação.
2. **Transformar**: funções puras.
3. **Carregar**: uma transação curta por empresa ou por fatia.

## 4. Multiempresa

- Toda tabela de negócio tem `empresa_id NOT NULL` com FK para a tabela de empresas, e os índices de consulta começam por ele.
- O RLS fica habilitado em toda tabela. Enquanto o painel não tiver login, não existe política para `anon`/`authenticated`, o que nega todo acesso pela API REST. O painel lê dados só por funções de `analitico` que recebem a credencial de acesso e resolvem a empresa dentro do banco (ADR-0004).
- Toda função ou view nova em `analitico` ganha um teste pgTAP provando que a credencial da empresa A devolve zero linhas da empresa B.
- Cadastrar, desativar ou excluir uma empresa é operação de dados (runbook), nunca mudança de código. Se uma tarefa exigir editar arquivo para atender uma empresa específica, o desenho está errado: pare e revise.
- [INEGOCIÁVEL] Nenhum nome, ID de conta, ID de BM, token ou dado de empresa real entra em arquivo versionado, log de CI, issue ou PR. Seeds e fixtures usam empresas fictícias ("Empresa Exemplo") e IDs inventados.

## 5. Normalização e padronização

- A camada `normalizado` segue a 3FN: cada fato fica num só lugar, e nada derivável é armazenado. CTR, CPC e custo por resultado são calculados em `analitico`.
- Os IDs da Meta são a chave natural, em coluna `text NOT NULL UNIQUE` (ex.: `id_meta`). Nunca use `bigint` nem `number`: de 15 a 18 dígitos ultrapassam o inteiro seguro do JavaScript. As FKs usam a chave interna `id`.
- Hierarquia: empresa → conta de anúncio → campanha → conjunto de anúncios → anúncio → criativo (N:1, reutilizável). Grãos:
  - métricas: anúncio × dia;
  - quebras: campanha × dia × categoria;
  - alcance: entidade × período (semana, mês ou ano).
- Ações e conversões (`actions`, `action_values`) ficam numa tabela longa: grão + `tipo_acao` + quantidade + valor. Não crie uma coluna por tipo nem faça o painel consultar `jsonb`. `cost_per_action_type` não é armazenado, porque é derivável.
- O catálogo de métricas, o mapa objetivo → resultado principal e as sobrescritas por campanha são dados em tabelas, nunca `if`/`switch` no código (ADR-0007).
- A tabela de calendário é a única fonte para agrupar dia → semana ISO → mês → ano. É proibido espalhar `date_trunc`/`extract` de semana ou mês pelas views.
- Desnormalização só existe em `analitico`.
- Tipos:
  - dinheiro: `numeric`, convertido de `Decimal` em Python, nunca `float`/`real`/`double`;
  - instantes: `timestamptz`;
  - datas de métrica: `date`, no fuso da conta, como a API entrega.
- A conta guarda o fuso (IANA) e a moeda (ISO 4217, com `CHECK`). Valores de moedas diferentes nunca são somados.
- Textos são aparados, e string vazia vira `NULL`. Enums da API são `text` com `CHECK` ou FK para o catálogo.
- `NULL` é diferente de zero: métrica-base ausente é `NULL`. Na tabela longa de ações, a ausência de linha significa zero, porque a API omite os tipos sem ocorrência.

## 6. Integridade e ACID

- **Atomicidade**: cada carga de empresa, ou de fatia histórica, roda numa única transação por conexão direta (`psycopg`). Nunca carregue via PostgREST, `supabase-js` ou `supabase-py`, em que cada requisição é uma transação isolada.
- **Consistência**: as regras moram no banco, com PK, FK, `NOT NULL`, `UNIQUE` e `CHECK` (moeda, datas, valores ≥ 0, status em domínio fechado). Validação no código não substitui restrição.
- **Isolamento**: o leitor vê o estado anterior ou o posterior à transação, nunca o meio. Execuções concorrentes da mesma empresa são impedidas com `pg_try_advisory_xact_lock` pela chave da empresa (RF-19).
- **Durabilidade e recuperação**: o banco tem o backup diário automático do Supabase. As métricas da Meta também podem ser recuperadas por reextração, até 37 meses, e o schema é reconstruível pelas migrations (ADR-0005).
- **Upsert**: idempotente pela chave natural (`INSERT ... ON CONFLICT ... DO UPDATE`); rodar duas vezes produz o mesmo estado. Na janela reprocessada, substitua o conjunto completo de linhas do intervalo (apagar e inserir na mesma transação), para não deixar órfãos os tipos de ação que sumiram na revisão da Meta.
- **Controle de execuções** (RF-20): os registros de início e fim usam transações próprias, para que a falha fique registrada mesmo depois do rollback da carga.
- A falha de uma empresa não interrompe nem desfaz as outras. O laço é por empresa, cada uma com sua transação e captura de erro. O job sai com código diferente de zero se alguma empresa falhou, para disparar a notificação (RF-50).

## 7. Painel para pessoas de negócio

- Rótulos, explicações, fórmulas e aditividade vêm só do catálogo de métricas no banco (ADR-0007). Nenhum texto de métrica fica fixo em componente.
- Nenhum nome de campo ou valor de enum da API aparece na tela (`spend`, `OUTCOME_SALES`, `ACTIVE`).
- Agregue e exiba conforme `docs/REQUIREMENTS.md` §3.3 e §7.1: métricas aditivas somam, razões são recalculadas a partir das somas, e alcance e frequência nunca são somados. Um teste prova a aditividade entre níveis (RF-32).
- O formato é pt-BR via `Intl` com `pt-BR`. A formatação fica centralizada num módulo; é proibido formatar número ou data inline.
- A prévia do anúncio é montada pelo painel com dados do banco e do Storage. Nunca use o iframe da Meta (R-25).

## 8. Clean Code

- Cada função tem uma responsabilidade, é pequena e tem nome iniciado por verbo (`extrair_insights_diarios()`, `carregarDesempenho()`). A complexidade é verificada pelo linter.
- Extrair, transformar e carregar ficam em módulos distintos. A transformação é pura (sem rede, banco, relógio ou aleatoriedade) e concentra a lógica testável; o I/O fica nas bordas.
- Números de negócio são constantes nomeadas num módulo de configuração (`JANELA_REPROCESSAMENTO_DIAS = 28`, `RETENCAO_BRUTO_DIAS = 35`, `VERSAO_API_META`). Nada de número mágico.
- Trate os erros explicitamente; nunca use `except` genérico silencioso.
  - Limite de taxa e erros transitórios da Meta: tente de novo com backoff exponencial e jitter, respeitando os cabeçalhos de uso (`X-Business-Use-Case-Usage`, `X-Ad-Account-Usage`, `X-FB-Ads-Insights-Throttle`), até `MAXIMO_TENTATIVAS`.
  - Erro definitivo: falha da empresa, registrada.
- Os logs são estruturados (JSON), com `execucao_id` e o UUID interno da empresa em toda linha.
- [INEGOCIÁVEL] Os logs do Actions são públicos. Nunca registre nome de empresa, IDs da Meta, nome de campanha ou anúncio, valor monetário, token ou URL com token. O logger aceita só campos de uma lista permitida, e um valor sensível inevitável que não é secret é mascarado com `::add-mask::`.
- Comentários explicam o porquê, não o quê. Nada de código morto, código comentado ou `TODO`: pendência vira issue (§11.4).
- Python leva type hints em toda função pública.

## 9. Testes e qualidade

- Os testes vão no mesmo commit do código que eles provam (§11.2).
- As fixtures são montadas a partir de respostas reais da API e anonimizadas antes do commit:
  - IDs trocados por inventados, com o mesmo formato;
  - nomes, textos, páginas e URLs substituídos;
  - nenhum dado pessoal.

  Revise o diff de cada fixture linha a linha.
- **Idempotência**: dois carregamentos da mesma entrada produzem estado idêntico.
- **Atomicidade**: uma falha injetada no meio da carga não deixa nenhuma linha da execução, e as outras empresas carregam normalmente.
- **Banco** (pgTAP, `supabase test db`, em `supabase/tests/`): restrições (PK, FK, `CHECK`, `UNIQUE`), isolamento entre empresas em toda função de `analitico`, aditividade entre níveis e calendário.
- **Unidade**: transformação pura da ETL e formatação pt-BR, com cobertura ≥ 80% (RNF-19).
- **CI**: obrigatória em todo PR, com lint, formatação, testes e varredura de segredos. Vermelho não entra na `main`.

## 10. Nomenclatura

Estrutura do repositório e documentos (`.md`, `.pdf`) ficam em inglês. Código, SQL, testes e demais arquivos ficam em português sempre que possível, no padrão de cada linguagem. O conteúdo dos documentos é em português.

| O quê | Idioma | Padrão | Exemplo |
|---|---|---|---|
| Pastas | inglês | minúsculas | `etl/`, `web/`, `supabase/migrations/`, `docs/adr/`, `tests/fixtures/` |
| Arquivos `.md` | inglês | MAIÚSCULAS na raiz e em `docs/` | `README.md`, `CLAUDE.md`, `docs/REQUIREMENTS.md` |
| Documentos de referência | inglês | `kebab-case` | `docs/meta-access-checklist.pdf` |
| ADRs | inglês | `NNNN-titulo-em-kebab-case.md` | `docs/adr/0002-multi-tenant-model.md` |
| Módulos Python | português | `snake_case.py` | `etl/extracao.py`, `etl/transformacao.py`, `etl/carga.py` |
| Funções e variáveis Python | português | `snake_case`, função começa com verbo | `extrair_insights_diarios()`, `normalizar_acoes()`, `investimento_total` |
| Funções e variáveis TS | português | `camelCase`, função começa com verbo | `carregarDesempenho()`, `formatarMoeda()`, `investimentoTotal` |
| Componentes React | português | `PascalCase`, arquivo com o nome do componente | `CartaoMetrica.tsx`, `TabelaCampanhas.tsx` |
| Tipos e interfaces TS | português | `PascalCase` | `MetricaDiaria`, `NivelEntidade` |
| Demais módulos TS | português | `kebab-case.ts`; arquivos reservados do Next.js mantêm o nome do framework | `lib/catalogo-metricas.ts`, `page.tsx` |
| Constantes | português | `MAIUSCULAS` | `JANELA_REPROCESSAMENTO_DIAS`, `MAXIMO_TENTATIVAS` |
| Rotas do painel | português | `kebab-case` | `/campanhas/[id]`, `/area-operador/metas` |
| Esquemas do banco | português | `snake_case` | `bruto`, `normalizado`, `analitico` |
| Tabelas | português | `snake_case`, singular | `empresa`, `conta_anuncio`, `metrica_diaria_anuncio` |
| Colunas | português | `snake_case`; `id`, `<tabela>_id`, `id_meta`, `*_em` para instantes | `empresa_id`, `id_meta`, `investimento`, `criado_em` |
| Funções SQL | português | `snake_case`, começa com verbo | `analitico.obter_desempenho()`, `normalizado.registrar_execucao()` |
| Migrations | português | `<timestamp>_<descricao>.sql`, gerado por `supabase migration new` | `20261105120000_cria_metrica_diaria_anuncio.sql` |
| Testes de banco | português | `snake_case_test.sql` | `supabase/tests/isolamento_empresas_test.sql` |
| Testes Python | português | `test_<modulo>.py`, função `test_<comportamento>` (prefixo exigido pelo pytest) | `tests/test_transformacao.py`, `test_upsert_e_idempotente()` |
| Fixtures | português | `snake_case.json` | `tests/fixtures/insights_anuncio_dia.json` |
| Workflows | português | `kebab-case.yml` | `.github/workflows/carga-horaria.yml`, `ci.yml` |
| Variáveis de ambiente | português | `MAIUSCULAS`; prefixos exigidos pela plataforma são mantidos | `TOKEN_SISTEMA_META`, `URL_BANCO` |
| Branches | tipo em inglês, descrição em português | `<tipo>/<codigo-da-issue>-<descricao>` | `feat/e4-02-insights-diarios` |

Na camada `bruto`, os nomes de campo da Meta ficam como chegam (`spend`). A partir de `normalizado`, eles são traduzidos (`investimento`) por um mapa único e versionado.

## 11. Git e tarefas

### 11.1 Branches (trunk-based)

- A `main` é protegida (PR e CI verde obrigatórios) e **sempre deployável**. Review de outra pessoa não é exigido; quem abre o PR responde pelo diff (§11.3).
- Branches são curtas, saem da `main` e levam o código da issue: `feat/e4-02-insights-diarios`, `fix/e4-04-alcance-semana-iso`, `chore/e1-04-ci`. Vida máxima: dias. Branch que passa de uma semana é sinal de escopo grande demais: fatie a issue.
- Antes de abrir o PR, atualize a branch por **rebase sobre a `main`** (histórico linear, sem merge commits de ida e volta). O merge do PR é por fast-forward/rebase. Use squash só quando a branch acumulou commits ruidosos que não valem preservar.

### 11.2 Commits logicamente isolados [INEGOCIÁVEL]

- Cada commit é **uma mudança coesa, completa e explicável em uma frase**, e o repositório compila e passa nos testes em cada commit. Exemplo de fatiamento correto de uma issue: `feat(db): migration da tabela de métricas diárias` → `feat(etl): transformação de insights em métricas diárias` → `feat(etl): carga idempotente das métricas diárias`. Cada um traz seus testes **no mesmo commit** do código que eles provam.
- Proibido:
  - commit "wip", "ajustes" ou "fix2";
  - misturar refatoração com feature no mesmo commit;
  - commit gigante de fim de dia com tudo junto.

  Se o trabalho se misturou, separe com `git add -p` antes de commitar.
- A mensagem segue o padrão `tipo(escopo): descrição imperativa`. Tipos: `feat`, `fix`, `test`, `refactor`, `chore`, `docs`. Escopos usuais: `db`, `etl`, `painel`, `ci`, `adr`. Omita o escopo quando a mudança for transversal.
  - A referência vai no corpo: `Ref: #12`, a issue. RF/RNF e ADR podem ir junto: `Ref: #12, RF-05, ADR-0005`.
  - O corpo explica **por quê** quando a razão não é óbvia pelo diff. O histórico é documentação de decisão: escreva para quem vai ler daqui a um ano.
- Commit, nome de branch e PR (título e corpo) citam só o que existe no repositório ou nas issues dele: issue, RF/RNF, ADR, arquivo. O que vive fora dele, como nome de sessão, conversa, prompt ou documento local, não entra, porque quem lê o histórico não tem como seguir a referência.

### 11.3 Autoria [INEGOCIÁVEL]

- Commits, PRs e reviews têm **sempre e somente autoria humana**. É proibido citar agentes ou ferramentas de IA como autores ou coautores, em qualquer forma: nada de `Co-Authored-By` apontando para IA, nada de trailers ou rodapés "Generated with ...", nada de IA como revisor registrado. Ferramentas que inserem atribuição automática ficam com ela desligada na configuração local de cada pessoa, fora do repositório.
- Ferramenta de IA é ferramenta, como o compilador e o linter. Quem assina o commit **leu, entendeu e responde** por cada linha dele. Se você não consegue explicar uma linha do seu diff, o commit não está pronto, independentemente de quem ou o quê o escreveu.

### 11.4 Tarefas

- Tarefas existem só nas issues do GitHub, e cada épico é um milestone. Não registre tarefas, pendências ou próximos passos em documentos: a issue aponta para RF, ADR e seções, e os documentos não apontam para issues.
- Título: `[TIPO] Código Título`, com o tipo do commit em maiúsculas e o código `E<épico>-<nn>`. Exemplo: `[FEAT] E4-02 Insights Diários por Anúncio e Ações`.
- Corpo: **Contexto**, **Detalhes Técnicos** (com as dependências como `Depende de #N`) e **Critérios de Aceite (Definition of Done)** em checkboxes. Os critérios citam o RF/RNF em vez de copiá-lo.
- Labels de tipo (`feat`, `chore`, `docs`) e de área (`db`, `etl`, `painel`, `ci`, `operacao`). A prioridade é a do requisito no `docs/REQUIREMENTS.md`.

## 12. Segredos e dados pessoais

- O token do System User da Meta fica só num secret do GitHub Actions e é lido só pela ETL (ADR-0003).
- A chave `service_role` e a string de conexão do banco ficam só em secrets do Actions e em variáveis de servidor da Vercel. Nunca use o prefixo `NEXT_PUBLIC_` nelas nem as leve ao navegador.
- As credenciais de acesso ao painel ficam no banco só como hash; o valor aparece uma única vez, na geração (ADR-0004).
- `.env*` fica fora do Git. O `.env.example` é versionado com nomes de variáveis e valores fictícios.
- Segredo commitado é segredo vazado: revogue e troque. Reescrever o histórico não basta.
- Workflows:
  - nunca use `pull_request_target`;
  - dê ao `GITHUB_TOKEN` as permissões mínimas;
  - fixe ações de terceiros por SHA.
- Num repositório público, os artefatos do Actions ficam visíveis para qualquer conta logada no GitHub. Nada de dado em artefato sem criptografia (ADR-0008).
- Dados pessoais: o sistema guarda só métricas agregadas. Leads individuais de formulários não são extraídos (LGPD), e fixtures, seeds e prints não contêm dado pessoal nem dado real de empresa.

## 13. Como trabalhar nesta base

1. Leia a issue e os RF/RNF e ADRs que ela cita antes de programar. Se o trabalho não tem issue, abra uma (§11.4) antes de começar.
2. Consulte a documentação oficial (Meta, Supabase, Vercel, GitHub) antes de assumir comportamento de plataforma, e cite a URL no PR. Itens *a confirmar* no `docs/REQUIREMENTS.md` são verificados antes de virar código.
3. Altere o schema só por migration (`supabase migration new <descricao>`), nunca pelo painel web do Supabase. Migration já aplicada não é editada: corrija com outra.
4. Decisão nova ou alterada vira ADR novo; o antigo recebe "Substituído por ADR-NNNN".
5. Atualize no mesmo PR o documento afetado (RF, catálogo, ADR, runbook).
6. Antes de commitar, fatie o trabalho conforme §11.2.
