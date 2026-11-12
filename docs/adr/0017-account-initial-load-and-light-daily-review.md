# ADR-0017: Carga inicial da conta e revisão diária leve

- Status: Aceito
- Data: 11/11/2026
- Atualizado em: 12/11/2026, com a medição da horária
- Substitui: a cadência do ADR-0005 e a extração diária do alcance do ADR-0006

## Contexto

A rotina diária do ADR-0005 relê todo dia o cadastro completo de cada conta, com as campanhas, os conjuntos e os anúncios arquivados. Também relê o alcance de todas as semanas, meses e anos que tocam a janela de 28 dias, com o ano por job assíncrono quando a resposta síncrona falha (ADR-0006; R-39).

Na empresa em produção, só a extração levou de 21 a 57 min por dia entre 07 e 10/11/2026, pelo log do Actions, e 23 min 37 s em 10/11. O teto do RNF-07 é de 60 min por empresa. A parte mais pesada é o cadastro. A aresta de anúncios, com o criativo expandido, sai em páginas de 100 e levou cerca de 5 min na conta com mais de 10 mil anúncios (R-42). O cadastro da conta com mais anúncios levou o `total_cputime` de `ads_management` a 67% e recebeu erros de limite (R-37). Já os insights de 28 dias custam poucas páginas por conta.

Pouco muda no cadastro de um dia para o outro: entram entidades novas, e algumas mudam de nome, status ou meta. As novas já entram pelo ID quando aparecem nos insights, nas quebras ou no alcance (ADR-0009 §5).

Pontos decididos neste ADR:
- Quando roda o cadastro completo;
- O que a extração diária lê;
- Qual alcance por período a extração diária recalcula;
- Onde fica a cópia das miniaturas do RF-38, que o ADR-0005 punha na cadência diária.

## Opções consideradas

### Cadastro completo

| Opção | Prós | Contras |
|---|---|---|
| **Uma vez por conta, na carga inicial, antes do histórico** | Tira da carga recorrente a parte mais pesada. A conta nova continua entrando sem mudança de código (RF-22) | Uma entidade que muda sem ter entrega continua com o cadastro antigo |
| Todo dia, como no ADR-0005 | Cadastro sempre atualizado | Relê milhares de anúncios arquivados por dia, perto do teto do RNF-07 e da cota de `ads_management` (R-37) |
| Uma vez por semana, em rotina própria | Atraso máximo de uma semana | Mais um workflow agendado, que continua relendo o cadastro inteiro |

### Alcance na extração diária

| Opção | Prós | Contras |
|---|---|---|
| **A semana, o mês e o ano que contêm ontem, e os dos dias perdidos depois de uma falha** | No dia normal, 9 consultas por conta, sempre no mesmo ano. O ano em andamento continua atualizado, e "este ano" não congela (ADR-0016). O período que termina no dia de uma revisão que falhou não fica cortado | Uma semana ou um mês encerrado tem a última leitura na primeira revisão bem-sucedida depois do fim dele, mesmo que a Meta ainda o revise (R-17) |
| Só a semana, o mês e o ano que contêm ontem, sempre | A regra mais simples | Se a revisão do dia seguinte ao fim de um período falhar, o alcance dele fica cortado no penúltimo dia, e nenhuma revisão seguinte o relê (RF-04) |
| Os períodos que tocam a janela de 28 dias, como no ADR-0006 | Revisa o alcance dos períodos encerrados dentro da janela | Relê todo dia semanas e meses já fechados e, na virada do ano, dois anos por job assíncrono |

### Cópia das miniaturas

| Opção | Prós | Contras |
|---|---|---|
| **Na revisão diária, só dos criativos sem cópia ou alterados** | Uma só rotina de cópia, para o criativo venha de onde vier. A URL é lida na mesma execução da cópia (R-26) | A primeira revisão depois da carga inicial copia todos os criativos da conta |
| Na carga inicial, para os criativos do cadastro, e na revisão, para os que entram depois | A cópia em massa fica no job de até 5 h | Duas rotinas de cópia. O cadastro não traz a URL (R-42), e a carga inicial teria de ler cada criativo de novo de qualquer forma |
| Na horária, junto da releitura pelo ID | Miniatura no painel em até 1 h | Download e upload dentro dos 10 min da horária (RNF-07) |

## Decisão

**Cadência**, que substitui a do ADR-0005:
- **Horária**, em minuto quebrado (ex.: `17 * * * *`) para fugir do pico do início da hora (R-08): hoje e ontem de cada conta, com métricas e ações no nível de anúncio e quebras por campanha. Relê pelo ID as campanhas, os conjuntos, os anúncios e os criativos com entrega nesses dois dias, para que nomes, status e metas de otimização fiquem atualizados sem o cadastro completo.
- **Revisão diária leve**, de madrugada, em `43 6 * * *`, 03:43 em Brasília, porque o cron do GitHub usa UTC. Executa:
  - os insights diários por anúncio com as ações (RF-02) e as quebras (RF-03) dos **28 dias** anteriores (RF-05; R-17);
  - o alcance e as impressões da semana ISO, do mês e do ano que contêm ontem, cada um do primeiro dia até ontem (ADR-0006; ADR-0016). Depois de uma revisão que falhou, a seguinte retoma do dia seguinte ao último já extraído na conta e relê os períodos que contêm cada dia desde então, limitados à janela de 28 dias. Assim, o período que terminou no dia da falha não fica cortado (RF-04). A conta sem alcance extraído, como a que não teve entrega, relê os períodos da janela inteira;
  - pelo ID, só as entidades que os insights, as quebras e o alcance trazem e o banco ainda não tem;
  - a cópia das miniaturas para o Storage;
  - a retenção de `bruto` (RF-21);
  - o registro do uso das cotas do plano (RF-52).

  Não lê o cadastro completo. O dia da janela sai do fuso que a carga inicial gravou, e a conta ainda sem fuso fica de fora até a carga inicial dela.
- **Carga inicial da conta**: o cadastro completo (RF-01) e a carga histórica (RF-07), no mesmo ponto de entrada, `etl.carga_historica`, registrado como execução `historica`.
  - O cadastro completo roda uma vez por conta. A conta ativa sem fuso ainda não o teve, porque só ele grava o fuso, na mesma transação das entidades.
  - Ele vem antes das fatias, que contam os dias no fuso dele, numa transação própria por conta, com o lock da empresa (RF-19). A falha no cadastro de uma conta não segura o cadastro nem o histórico das outras, e a conta continua sem fuso para a execução seguinte.
  - O cadastro das contas novas de todas as empresas vem antes das fatias de qualquer uma. O histórico de uma empresa pode ocupar o prazo de várias execuções, e a conta nova de outra não espera por ele. Cada empresa tem uma execução para os cadastros e outra para as fatias.
  - Depois do cadastro, a execução planeja e carrega as fatias de até 37 meses, como antes.
  - Roda como job da carga diária, depois da revisão, e por disparo manual, para carregar uma conta nova ou retomar sem esperar a madrugada seguinte (RF-22).
  - Cada execução deixa de começar etapas novas, de cadastro ou de fatia, depois de 3 h. Ela cabe nas 5 h do RNF-07, abaixo das 6 h por job do Actions (R-07). As 2 h restantes cobrem a etapa em andamento quando a cota da conta se esgota e cada chamada espera a recuperação (R-37). A execução seguinte continua de onde ela parou.
- **Fora da carga recorrente**: o cadastro completo e o alcance dos períodos que não contêm ontem nem um dia perdido. A semana e o mês têm a última leitura na primeira revisão bem-sucedida depois do último dia deles, normalmente no dia seguinte. O ano anterior tem a última leitura em 1º de janeiro.

**Miniaturas (RF-38)**: a cópia para o Storage fica na revisão diária, só para os criativos ainda sem cópia ou alterados desde a última. O `thumbnail_url` é lido pelo ID do criativo na mesma execução, porque vence em poucos dias (R-26) e não vem no cadastro (R-42). Assim, a cópia cobre o criativo que entra pelo cadastro da carga inicial e o que entra pelas leituras pelo ID da horária e da revisão.

## Consequências

- A extração recorrente deixa de ler a conta e as arestas de anúncios, conjuntos e campanhas. Em 11/11/2026, nas quatro contas da empresa em produção, as consultas da revisão leve levaram 9,8 min, contra 20 min 51 s da extração da rotina completa no mesmo dia, pelo log do Actions. A medição foi feita só na API, sem a leitura pelo ID dos objetos novos, que depende do banco e não faz chamada quando não há objeto novo. A conta com mais campanhas levou 5 min, e três das quatro contas tiveram consultas por job assíncrono (R-39).
- Em 12/11/2026, nas quatro contas da empresa em produção, a extração da horária levou 2 min 51 s, com 159 leituras pelo ID dos anúncios, conjuntos e campanhas com entrega em ontem e hoje, dentro dos 10 min do RNF-07. A medição foi feita só na API, sem a carga. Nenhuma campanha das quebras ficou de fora das que vêm pelos anúncios.
- Uma entidade que muda sem ter entrega hoje nem ontem continua no banco com o nome, o status e a meta da última leitura, até voltar a ter entrega. Um exemplo é a campanha renomeada depois de encerrada.
- O alcance de uma semana ou de um mês encerrado tem a última leitura na primeira revisão bem-sucedida que vem depois do fim dele. Se a Meta revisar esse alcance dentro dos 28 dias (R-17), o banco fica com essa leitura.
- A conta recém-cadastrada não entra na revisão até a carga inicial gravar o fuso, o que acontece na mesma madrugada, depois da revisão, ou no disparo manual. A partir da noite seguinte, ela tem os 28 dias da revisão, mesmo que o histórico ainda não tenha terminado.
- O critério do RF-01 continua valendo: todo anúncio com entrega nos últimos 28 dias entra pelo ID, com conjunto, campanha e criativo, quando o banco ainda não o tem.
- A primeira revisão depois da carga inicial copia as miniaturas de todos os criativos da conta. Numa conta com milhares de anúncios, essa cópia pode não caber numa só revisão (RNF-07) e precisa continuar nas seguintes.
- Na tabela de controle, o cadastro da conta nova fica numa execução `historica` própria, com as linhas dele na contagem da execução (RF-20).
- Duas cargas iniciais da mesma empresa ao mesmo tempo, fora da concorrência do workflow, podem ler o mesmo cadastro, e a segunda o carrega de novo depois do lock. Os dados continuam consistentes, como nas fatias, ao custo da cota da segunda leitura.
- **Gatilho de revisão**: se o cadastro desatualizado de entidades sem entrega fizer falta no painel, voltamos a ler o cadastro completo em cadência própria, como a semanal.
