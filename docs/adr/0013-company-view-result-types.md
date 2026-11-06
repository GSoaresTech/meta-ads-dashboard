# ADR-0013: Tipos de resultado da visão Geral

- Status: Aceito
- Data: 06/11/2026

## Contexto

A visão Geral mostra totais por moeda "de cada tipo de resultado" (`docs/REQUIREMENTS.md` §3.1). Uma empresa tem campanhas com objetivos diferentes, e resultados de tipos diferentes não se somam: compras e conversas não viram um número só. O resultado principal é definido por campanha (ADR-0007), e o Geral não tem um resultado próprio.

Pontos decididos neste ADR:
- Quais tipos de resultado aparecem no Geral;
- O que o total de cada tipo soma.

## Opções consideradas

### Quais tipos aparecem

| Opção | Prós | Contras |
|---|---|---|
| **O resultado principal das campanhas com entrega no período, em cada moeda** | Segue a precedência do ADR-0007, com a sobrescrita. A campanha de vendas sem nenhuma compra aparece como zero, que é a informação mais importante daquele período | Uma função a mais em `analitico` |
| Todo resultado do catálogo com valor no período | Lê só o catálogo | Toda campanha gera cliques e interações, e por isso esses tipos apareceriam sem campanha com esse objetivo. O zero da campanha de vendas sumiria, e a sobrescrita para uma métrica fora das regras do catálogo ficaria de fora |
| Todo resultado do catálogo, sempre | Os cartões não mudam entre períodos | Mostra zeros de objetivos que a empresa nunca usou |

### O que o total soma

| Opção | Prós | Contras |
|---|---|---|
| **Todas as campanhas da moeda** | É o número da `obter_desempenho`, e assim o total do Geral é a soma das contas (RF-32) | Inclui ocorrências de campanhas cujo resultado principal é outro, como uma compra vinda de uma campanha de tráfego |
| Só as campanhas cujo resultado principal é aquele tipo | Mostra apenas o que cada campanha foi feita para gerar | O total deixa de ser a soma das contas e das campanhas (RF-32) e exige uma agregação nova |

## Decisão

- **Tipos**: em cada moeda, os tipos de resultado do período são o resultado principal resolvido das campanhas com entrega nele, com a sobrescrita aplicada (ADR-0007). A entrega é a da `obter_desempenho`: ter dia de métrica no intervalo. A campanha sem resultado no catálogo não gera tipo.
- **Totais**: o total de cada tipo é o da `obter_desempenho` no nível Geral, que soma todas as campanhas da moeda.
- **Leitura**: `analitico.listar_resultados` devolve uma linha por moeda e tipo (ADR-0009 §4). Ela só escolhe os tipos e não calcula valores.
- **Métrica fora da `obter_desempenho`**: o tipo que não sai dessa função, como o alcance (ADR-0006), aparece como "Não disponível", pelas regras da §3.3 do `docs/REQUIREMENTS.md`.

## Consequências

- Os cartões do Geral mudam com o período, conforme as campanhas que tiveram entrega nele.
- Um tipo aparece só na moeda em que há campanha com esse resultado, mesmo que a `obter_desempenho` tenha o número nas outras.
- O alcance é o resultado das campanhas de reconhecimento e fica "Não disponível" no Geral com mais de uma conta (`docs/REQUIREMENTS.md` §3.3).
