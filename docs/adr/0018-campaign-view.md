# ADR-0018: Destaque e métricas de apoio da visão da campanha

- Status: Aceito
- Data: 12/11/2026

## Contexto

A visão da campanha mostra um cartão de destaque com o resultado principal e o KPI do objetivo e as métricas de apoio (`docs/REQUIREMENTS.md` §3.1). O resultado, o KPI e o apoio de cada campanha vêm da resolução do catálogo, com a sobrescrita (ADR-0007), mas nenhuma função de `analitico` expõe as métricas de apoio. O §3.1 também não diz se o investimento entra no apoio, o que acontece quando a sobrescrita põe no destaque uma métrica que a regra traz no apoio, nem o que o destaque mostra numa campanha sem resultado principal (§7.2).

Pontos decididos neste ADR:
- De onde o painel lê o destaque e o apoio;
- Quais métricas aparecem no apoio;
- O que o destaque mostra sem resultado principal e sem dados no período.

## Opções consideradas

### Leitura do destaque e do apoio

| Opção | Prós | Contras |
|---|---|---|
| **Uma função de `analitico` para a campanha em foco, com o resultado, o KPI e o apoio** | Uma linha, só da campanha. O painel não tem regra de objetivo | Uma função a mais |
| As métricas de apoio como coluna da `listar_entidades` | Reaproveita a listagem, que já traz o resultado e o KPI | A listagem traz as filhas de uma entidade: para achar a própria campanha, a página listaria todas as da conta |
| O mapa de regras inteiro para o painel | Uma leitura para qualquer campanha | O painel teria de repetir a precedência do ADR-0007 para escolher a regra |

### Investimento no apoio

| Opção | Prós | Contras |
|---|---|---|
| **Sempre, no início do apoio** | A pergunta "quanto investimos" tem resposta em toda campanha, como nos totais do Geral e da conta. É o que a migration da promoção de app já supunha ao tirar o investimento do apoio dela | O apoio da tela tem uma métrica a mais que a regra do catálogo |
| Só quando a regra o traz | O apoio é exatamente o do catálogo | A maioria das regras não o traz, e a campanha ficaria sem o investimento |

### Destaque sem resultado principal

| Opção | Prós | Contras |
|---|---|---|
| **Uma frase que diz que o objetivo não tem resultado principal, com o objetivo e o status** | Explica a ausência a quem não conhece o catálogo, e nenhum número de outra métrica aparece | Difere do "—" da lista de campanhas da conta (ADR-0014) |
| "—" no lugar dos cartões | O mesmo sinal da lista | Um traço sem rótulo não diz o que falta |
| Sem destaque | Nada a explicar | A página perde o objetivo e o status, e a ausência fica sem explicação |

## Decisão

- **Leitura**: `analitico.obter_campanha` devolve o objetivo e o status em rótulo de negócio, o resultado principal e o KPI resolvidos e as métricas de apoio da regra, em ordem de exibição, mesmo com sobrescrita (ADR-0009 §4).
- **Destaque**: o resultado principal e o KPI, nessa ordem, cada um com o cartão e a série, com o objetivo e o status.
- **Apoio**: o investimento, seguido das métricas de apoio da regra, cada uma com o cartão e a série. Uma métrica aparece uma vez: a que está no destaque sai do apoio.
- **Sem resultado principal**: o destaque mostra o objetivo, o status e a frase "O objetivo desta campanha não tem resultado principal definido.", sem cartões. O apoio continua.
- **Sem dados no período**: não há destaque nem apoio, e a página diz "Nenhum dado no período.", como as visões Geral e da conta. Sem entrega, a campanha não tem moeda nem valor a destacar.
- **Métrica fora da `obter_desempenho`**: o alcance, a frequência e o custo por mil pessoas alcançadas aparecem como "Não disponível", sem série, como no ADR-0013.

## Consequências

- Mudar o resultado, o KPI ou o apoio de uma regra no catálogo, ou a sobrescrita de uma campanha, muda a tela sem mudar o painel.
- O destaque das campanhas de reconhecimento fica "Não disponível" até o painel exibir o alcance (ADR-0016).
- No período sem entrega, a página da campanha não mostra o objetivo nem o status.
