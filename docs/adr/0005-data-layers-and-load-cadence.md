# ADR-0005: Camadas de dados, cadência da carga e recuperação

- Status: Aceito
- Data: 30/10/2026

## Contexto

O tratamento de dados é intensivo. A Meta revisa conversões de dias passados (R-17), e precisamos de atualização de hora em hora e de até 37 meses de histórico (R-19). O banco é um projeto Supabase em plano pago, com backup diário automático e sem pausa por inatividade (R-01).

## Opções consideradas

### Camadas

| Opção | Prós | Contras |
|---|---|---|
| **Três esquemas: `bruto`, `normalizado`, `analitico`** | Permite auditar e reprocessar sem nova chamada à API; 3FN com restrições na camada central; desnormalização isolada | A camada `bruto` consome espaço, o que exige retenção |
| Só `normalizado` + views | Menos espaço | Um erro de transformação exigiria reextrair; não há trilha de auditoria |

### Cadência

| Opção | Prós | Contras |
|---|---|---|
| **Horária leve + diária pesada** | Dados de hoje e de ontem atualizados de hora em hora com poucas chamadas; a janela de 28 dias e o alcance por período rodam uma vez por dia | Duas rotinas para manter |
| Horária completa (28 dias a cada hora) | Uma rotina só | 24 vezes mais chamadas para o mesmo resultado; pressiona o limite de 60 pontos por conta no nível Limited (R-15) |

## Decisão

**Camadas**
- `bruto`: guarda cada resposta da API como `jsonb`, com execução, empresa, conta, endpoint, parâmetros e data de referência. A retenção é de **35 dias** de data de referência: a janela de 28 dias mais uma margem.
- `normalizado`: modelo em 3FN, fonte da verdade.
- `analitico`: views e funções lidas pelo painel.

**Cadência**
- **Horária**, em minuto quebrado (ex.: `17 * * * *`) para fugir do pico do início da hora (R-08): hoje e ontem, com métricas e ações no nível de anúncio e quebras por campanha.
- **Diária**, de madrugada, também em minuto quebrado. Executa:
  - reprocessamento dos **28 dias** anteriores (R-17);
  - alcance e impressões por semana ISO, mês e ano (ADR-0006);
  - cadastro de entidades e criativos;
  - cópia de miniaturas para o Storage;
  - retenção de `bruto`;
  - registro do uso das cotas do plano.
- **Histórica**: ao cadastrar uma conta, importa até 37 meses fatiados por mês. Cada fatia é uma transação atômica e idempotente, e a carga pode ser retomada pela tabela de controle.

**Recuperação**
- Banco: backup diário automático do Supabase, com a retenção do plano contratado (R-01).
- Métricas da Meta: também recuperáveis por reextração pela carga histórica, até 37 meses, o que cobre perdas além da retenção do backup.
- Schema: reconstruído pelas migrations.

**Capacidade**: se o volume se aproximar das cotas do plano (RF-52), revisar nesta ordem: reduzir a retenção de `bruto`; reduzir o histórico das quebras; aceitar o custo adicional de armazenamento.

## Consequências

- RTO de 24 h e RPO de 24 h para os dados operacionais (backup diário), e RPO de 0 para as métricas dentro de 37 meses (RNF-12).
- Em repositório público, os workflows agendados são desativados após 60 dias sem atividade (R-08; Q-11). O indicador de atraso do painel (RF-28) e o destaque de carga parada (RNF-13) tornam o problema visível.
- O agendamento do GitHub pode atrasar ou descartar jobs (R-08), o que o RNF-08 tolera com 2 h de defasagem.

## Referências

Consultadas em 29/10/2026.
- https://developers.facebook.com/docs/marketing-api/insights/best-practices
- https://supabase.com/pricing
- https://supabase.com/docs/guides/platform/backups
- https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows
