# ADR-0016: Alcance e frequência no painel

- Status: Aceito
- Data: 10/11/2026

## Contexto

O alcance e a frequência vêm do alcance extraído por semana ISO, mês e ano (ADR-0006), e a §3.3 do `docs/REQUIREMENTS.md` diz quando o painel mostra esse valor e quando mostra "Não disponível". Faltava definir quatro situações:

- **Período em andamento**: a rotina diária extrai a semana, o mês e o ano em andamento só até ontem (ADR-0006), e os atalhos "este mês" e "este ano" vão até hoje (ADR-0012). Nenhum intervalo que chega a hoje coincide exatamente com o que foi extraído.
- **Geral com mais de uma conta**: a §3.3 não diz se contam todas as contas da empresa ou só as que tiveram entrega no período.
- **Coincidência**: a semana, o mês e o ano podem começar no mesmo dia, e o período em andamento termina antes do fim de calendário.
- **Período sem linha de alcance**: a API não devolve o período sem entrega (R-20), a carga histórica não extrai o que começa antes do limite de 37 meses (R-19), e uma extração que falha ou ainda não chegou ao período também não deixa linha.

Pontos decididos neste ADR:
- O alcance do período em andamento;
- Quais contas contam no Geral;
- Quando um período exibido coincide com o extraído;
- O período de calendário sem linha de alcance.

## Opções consideradas

### Período em andamento

| Opção | Prós | Contras |
|---|---|---|
| **Valor extraído até o último dia da rotina diária, com essa data** | "Este mês" e "este ano" mostram o alcance, resultado principal das campanhas de reconhecimento (`docs/REQUIREMENTS.md` §7.2). É o valor que o ADR-0006 já grava | O valor não inclui hoje, e o painel precisa dizer até que dia ele vale |
| "Não disponível" até o período fechar | O valor sempre cobre o período exibido inteiro | "Este mês" e "este ano" nunca têm alcance, e a semana e o mês em andamento ficam sem valor nas séries |

### Contas do Geral

| Opção | Prós | Contras |
|---|---|---|
| **Todas as contas cadastradas da empresa** | Leitura literal da §3.3. A série do Geral fica toda com valor ou toda indisponível | Uma conta inativa ou ainda sem dados basta para tirar o alcance do Geral |
| Só as contas com entrega em cada período | Mostra o alcance sempre que não há o que deduplicar | A série pode alternar entre valor e "Não disponível", conforme as contas que tiveram entrega em cada ponto |

### Período sem linha de alcance

| Opção | Prós | Contras |
|---|---|---|
| **Separar pelo motivo: antes do limite, sem entrega e ainda não extraído** | Cada "Não disponível" tem explicação, e o período sem entrega mostra zero, como as métricas aditivas da `obter_desempenho` | Um motivo além dos da §3.3, para um estado que só ocorre quando a extração falha ou ainda não chegou ao período |
| Tratar toda ausência como "Não disponível" | Uma regra só | O período sem entrega, cujo alcance é zero, fica sem número, e a explicação não diz o motivo |

## Decisão

- **Coincidência**: um período exibido, que pode ser o intervalo inteiro ou cada dia, semana, mês ou ano da série cortado no intervalo, mostra o valor extraído de uma semana ISO, de um mês ou de um ano da entidade quando começa no primeiro dia desse período de calendário, termina dentro dele e chega pelo menos ao último dia extraído. Quando mais de um extraído serve, como a semana e o mês que começam no mesmo dia, vale o extraído até mais tarde. Sem linha extraída, coincidem a semana, o mês ou o ano inteiro e o período em andamento exibido do primeiro dia até hoje, no fuso da conta.
- **Período em andamento**: por essa regra, "este mês", "este ano" e a semana ou o mês em andamento de uma série mostram o valor extraído até o último dia da rotina diária, com essa data. O período exibido que termina antes do último dia extraído é período livre.
- **Métricas que dependem do alcance**: a frequência usa as impressões da mesma resposta da API (ADR-0006), e o custo por mil pessoas alcançadas usa o investimento dos mesmos dias do alcance.
- **Geral**: o Geral tem alcance só na empresa com uma conta cadastrada, e então ele é o da conta. Com duas ou mais, mesmo inativas ou sem dados, é "Não disponível" (`docs/REQUIREMENTS.md` §3.3).
- **Período sem linha de alcance**: o período exibido que coincide sem linha extraída é:
  - "Não disponível" pelo limite de 37 meses, quando começa antes do primeiro dia que a carga histórica extrairia hoje: hoje menos 37 meses no fuso da conta, com a margem de um dia da carga histórica (R-19). O período que começa antes desse dia nunca ganha linha, e a linha extraída antes, quando o período ainda estava dentro do limite, continua valendo;
  - zero de alcance, com a frequência e o custo sem valor, quando a entidade não teve entrega nele, porque a API omite o período sem entrega (R-20);
  - "Não disponível" por ainda não ter sido extraído, quando teve entrega, como "este mês" no dia 1, antes da rotina diária, ou depois de uma extração que falhou.

## Consequências

- O alcance do período em andamento fica atrás das métricas aditivas, que a carga horária atualiza (ADR-0005). O painel mostra até que dia ele vale.
- "Ontem" que cai no primeiro dia de uma semana ou de um mês coincide com o período em andamento extraído só até esse dia e mostra o alcance dele, e "hoje" nesse dia é o período em andamento ainda sem linha. Nos outros dias, "ontem" e "hoje" são período livre.
- Durante a carga histórica, as semanas anteriores à janela da rotina diária ainda não têm métricas nem alcance e aparecem com alcance zero, como as aditivas da `obter_desempenho` aparecem zeradas.
- Uma empresa com mais de uma conta nunca tem alcance no Geral, e a lista de contas mostra o de cada uma.
- O período extraído só até antes do fim, porque a rotina diária parou ou a conta foi desativada, continua com o valor até o último dia extraído, mesmo depois de encerrado, e o painel mostra essa data. Com a rotina parada, aparece também o aviso de atraso do RF-28.
- **Gatilho de revisão**: se o alcance do Geral fizer falta em empresas com contas inativas, passamos a contar só as contas com entrega.
