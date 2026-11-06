# ADR-0014: Totais e lista de campanhas da visão da conta

- Status: Aceito
- Data: 06/11/2026

## Contexto

A visão da conta mostra os totais da conta e a lista de campanhas com objetivo, resultado principal e custo por resultado (`docs/REQUIREMENTS.md` §3.1). O ADR-0013 decidiu quais tipos de resultado aparecem no Geral, mas não fala da conta, e a `listar_resultados` só lê a empresa inteira. O §3.1 também não diz o que é o "custo por resultado" de uma campanha cujo KPI não é um custo por ocorrência, nem como a lista mostra resultados de tipos diferentes.

Pontos decididos neste ADR:
- Quais tipos de resultado aparecem nos totais da conta e de onde eles vêm;
- O que é a coluna de custo por resultado;
- Como a lista mostra resultados de tipos diferentes.

## Opções consideradas

### Tipos de resultado da conta

| Opção | Prós | Contras |
|---|---|---|
| **O resultado principal das campanhas da conta com entrega, lido da própria lista de campanhas** | A mesma regra do Geral, restrita à conta. A lista já tem o resultado resolvido e a entrega de cada campanha, sem consulta nem parâmetro novos | O painel monta os tipos em vez de recebê-los do banco, como no Geral |
| Acrescentar o nível e a entidade à `listar_resultados` | Uma só função escolhe os tipos em todos os níveis | Muda uma assinatura para devolver o que a lista já traz, e mais uma consulta por página |
| Os tipos da empresa inteira na moeda da conta | Reaproveita a `listar_resultados` como está | Uma conta só de vendas mostraria "Cadastros: 0" por causa de outra conta da mesma moeda |

### Custo por resultado

| Opção | Prós | Contras |
|---|---|---|
| **O KPI resolvido da campanha (ADR-0007), com o rótulo dele** | Um dado só no catálogo, já com a sobrescrita. É o par que a campanha destaca (RF-31) | Nas campanhas de reconhecimento, o KPI é o custo por mil pessoas alcançadas, e não o custo por pessoa |
| Investimento dividido pelo resultado, calculado para a lista | O mesmo cálculo em todas as linhas | Duplica o que o catálogo já define e divergiria do KPI da página da campanha |

### Resultados de tipos diferentes na lista

| Opção | Prós | Contras |
|---|---|---|
| **Uma tabela com o rótulo do catálogo em cada célula ("Compras: 6")** | As colunas ficam fixas, e cada número diz o que é | Repete o rótulo entre as linhas |
| Uma coluna por tipo de resultado | Sem repetição | A maioria das células fica vazia, e as colunas mudam com o período |
| Agrupar as campanhas por tipo de resultado | Os números de cada grupo são comparáveis | Quebra a ordem por nome e acrescenta um nível que o §3.1 não pede |

## Decisão

- **Tipos**: os totais da conta são o investimento e o resultado principal das campanhas dela com entrega no período, com a sobrescrita aplicada. A entrega e os totais são os da `obter_desempenho`, como no ADR-0013.
- **Leitura**: os tipos saem da lista de campanhas, e a `listar_resultados` continua sendo só da empresa. A `listar_entidades` traz o objetivo, o status, o resultado e o KPI de cada campanha (ADR-0009 §4), e a mesma chamada da `obter_desempenho` no intervalo inteiro serve aos totais e à lista.
- **Custo por resultado**: a coluna é o KPI resolvido da campanha, com o rótulo do catálogo.
- **Tabela**: uma linha por campanha com entrega no período, em ordem de nome, com o rótulo do catálogo em cada célula de métrica.
- **Sem resultado no catálogo**: a campanha "Não classificado" aparece na lista, com "—" no resultado e no custo, e não gera tipo nos totais. O investimento dela continua somando no total da conta.
- **Métrica fora da `obter_desempenho`**: o alcance e o custo por mil pessoas alcançadas aparecem como "Não disponível", como no ADR-0013.

## Consequências

- O total de um tipo soma todas as campanhas da conta, inclusive as que têm outro resultado principal, como no Geral. Por isso ele pode ser maior que a soma das linhas da lista daquele tipo.
- Os cartões da conta mudam com o período, conforme as campanhas que tiveram entrega nele.
- A tabela tem cinco colunas e passa da largura de 360 px. O RF-29 pede que ela vire cartões em telas estreitas.
