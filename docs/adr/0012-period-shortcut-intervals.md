# ADR-0012: Intervalos dos atalhos de período

- Status: Aceito
- Data: 06/11/2026

## Contexto

O RF-26 pede atalhos de período calculados no fuso da conta, e as datas das métricas ficam no fuso de cada conta, como a Meta entrega (R-17). Faltava definir o intervalo correto de um atalho em três situações:

- **Contas em fusos diferentes**: uma empresa pode ter contas com deslocamentos UTC diferentes, e já temos esse caso em produção, com 5 h de diferença. O nível Geral soma essas contas, e "hoje" e "ontem" cobrem dias diferentes em cada uma. Às 03:43 de Brasília, o "ontem" de uma conta em Brasília ainda está em andamento numa conta em UTC−8.
- **Últimos 7 e 30 dias**: os requisitos não dizem se o intervalo inclui o dia parcial de hoje, e a referência de insights da Meta também não diz se `last_7d` e `last_30d` o incluem.
- **Descida de nível**: a URL guarda a seleção (RF-24), e a conta aberta a partir do Geral pode estar em outro fuso.

Pontos decididos neste ADR:
- O "hoje" do nível Geral;
- O fim dos atalhos de últimos dias;
- O que acontece com o atalho ao descer de nível;
- O período de abertura do painel.

## Opções consideradas

### "Hoje" do nível Geral

Em todas as opções, a série do Geral soma, em cada data, o dia de cada conta no fuso dela. Com dados diários, essa é a única soma possível.

| Opção | Prós | Contras |
|---|---|---|
| **Fuso mais atrasado entre as contas** | "Ontem" e os dias anteriores já estão encerrados em todas as contas. Nenhum atalho mostra como fechado um dia que ainda corre numa delas | Nas horas de diferença, o "hoje" mostra o dia anterior, já fechado, das contas adiantadas |
| Fuso mais adiantado | O "hoje" sempre inclui o dia corrente de cada conta adiantada | "Ontem" pode ainda estar em andamento nas contas atrasadas |
| Fuso fixo (`America/Sao_Paulo`) | Uma constante, sem depender das contas | Numa empresa só com contas em outro fuso, o "hoje" do Geral fica deslocado em relação ao da conta |

### Fim dos últimos 7 e 30 dias

| Opção | Prós | Contras |
|---|---|---|
| **Terminar ontem** | Só dias completos. A comparação com o período anterior (RF-27) não confronta um dia parcial com um dia inteiro | Os dados de hoje ficam fora desses atalhos |
| Terminar hoje | Segue "este mês" e "este ano", que vão até hoje | O último dia fica parcial |

### Atalho ao descer de nível

| Opção | Prós | Contras |
|---|---|---|
| **Recalcular o atalho no fuso de cada nível** | Segue o RF-26: cada conta usa o próprio fuso. A seleção é a mesma em todos os níveis, e o endereço salvo continua relativo ao dia em que é aberto | Nas horas de diferença entre os fusos, as datas e os números da conta podem não bater com os do Geral |
| Um só "hoje" por empresa, em todos os níveis | Descer nunca muda as datas, e os níveis sempre somam | Nessas horas, a conta adiantada deixa de usar o próprio fuso, contra o RF-26 |
| Levar as datas resolvidas nos links | Descer nunca muda as datas | O atalho se perde na descida, e recarregar a página deixa de mostrar "últimos 7 dias" (RF-24) |

## Decisão

- **Geral**: o "hoje" é o dia corrente mais atrasado entre as contas da empresa, e os demais atalhos partem dele. A conta ainda sem a primeira extração não tem fuso e fica de fora. Sem nenhuma conta com fuso, vale o dia em UTC, como na rotina diária (ADR-0009 §5).
- **Conta, campanha e anúncio**: o "hoje" é o dia corrente no fuso da conta.
- **Cálculo**: a `analitico.obter_trilha` devolve os fusos que cada nível abrange, e o painel escolhe o dia pelo próprio relógio, que os testes fixam (RF-26).
- **Últimos 7 e 30 dias**: terminam ontem, sem o dia parcial de hoje. "Este mês" e "este ano" vão até hoje.
- **Descida**: a URL leva o atalho pelo nome, e cada nível o recalcula no próprio fuso. Cada página mostra as datas do intervalo.
- **Abertura**: sem período na URL, o painel abre nos últimos 30 dias, por dia. É também o padrão da API de insights (`last_30d`). Valor desconhecido ou intervalo inválido na URL volta a esse padrão, sem erro.

## Consequências

- Numa empresa com um só fuso, nada muda: o Geral e as contas têm o mesmo "hoje".
- Com contas em fusos diferentes, nas horas de diferença entre eles, o mesmo atalho pode cobrir datas diferentes no Geral e na conta adiantada. Na virada do mês ou do ano, "este mês" e "este ano" podem cair em meses ou anos diferentes. Nessas horas, a soma das contas pode não bater com o Geral, porque os intervalos não são os mesmos. O RF-32 continua valendo para o mesmo intervalo, e as datas exibidas em cada página mostram o que foi selecionado.
- Nessas horas, o dia corrente das contas adiantadas não aparece no "hoje" do Geral. Ele entra quando a conta mais atrasada chega ao mesmo dia.
- Toda conta com fuso entra na regra do Geral, inclusive uma conta inativa, que não tem dia aberto.
- **Gatilho de revisão**: se a leitura nas horas de diferença atrapalhar o negócio, adotamos um só "hoje" por empresa em todos os níveis e revemos o RF-26.

## Referências

Consultada em 06/11/2026.
- https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights/
