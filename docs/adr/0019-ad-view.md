# ADR-0019: Métricas da visão do anúncio

- Status: Aceito
- Data: 12/11/2026

## Contexto

A visão do anúncio mostra as métricas e a série temporal dele, além da miniatura, do link "ver publicação" e da prévia (`docs/REQUIREMENTS.md` §3.1; RF-38 a RF-40). O §3.1 não diz quais métricas são essas. O resultado principal, o KPI e as métricas de apoio são resolvidos por campanha (ADR-0007), e o anúncio não tem regra própria no catálogo. O destaque com o objetivo e o status é da campanha (ADR-0018), e o §3.1 não o pede no anúncio.

Pontos decididos neste ADR:
- Quais métricas o anúncio mostra e de onde o painel as lê;
- Como elas se organizam na página.

## Opções consideradas

### Métricas do anúncio

| Opção | Prós | Contras |
|---|---|---|
| **As da campanha do anúncio: o investimento, o resultado principal, o KPI e as métricas de apoio** | Responde quanto o anúncio entregou do que a campanha busca e a que custo, com os mesmos números que somam a campanha (RF-32). Mudar a regra ou a sobrescrita da campanha muda o anúncio junto | Depende da campanha do anúncio, que a página já tem na trilha |
| Um conjunto fixo, como o investimento, as impressões e os cliques | Independe do objetivo | Não mostra o resultado que interessa ao negócio, e o conjunto ficaria fixo no código, contra o ADR-0007 |
| Todas as métricas do catálogo | Nada a escolher | A maioria não tem relação com o objetivo da campanha, e a leitura do que importa se perde |

### Organização na página

| Opção | Prós | Contras |
|---|---|---|
| **Um bloco por moeda, como os totais das outras visões, com o investimento, o resultado, o KPI e o apoio, nessa ordem** | É o "métricas e série temporal" do §3.1, com o resultado logo depois do investimento, como no Geral e na conta | O resultado não tem a moldura do destaque da campanha |
| O destaque da campanha, com o objetivo e o status | O mesmo desenho da campanha | O objetivo e o status seriam os da campanha numa página do anúncio, e o §3.1 não pede destaque nele |

## Decisão

- **Leitura**: o painel lê o resultado principal, o KPI e o apoio da `analitico.obter_campanha`, com a campanha que a trilha do anúncio traz, e os valores do anúncio da `analitico.obter_desempenho`, no intervalo inteiro e na granularidade escolhida. Não há função nova.
- **Métricas**: o investimento, o resultado principal, o KPI e as métricas de apoio da regra, nessa ordem, cada uma com o cartão e a série. Uma métrica aparece uma vez.
- **Sem resultado principal**: o bloco traz o investimento e o apoio, sem o número de outra métrica no lugar do resultado (§7.2).
- **Sem dados no período**: a página diz "Nenhum dado no período.", como as outras visões.
- **Métrica fora da `obter_desempenho`**: o alcance, a frequência e o custo por mil pessoas alcançadas aparecem como "Não disponível", sem série, como no ADR-0013.
- **Miniatura, link e prévia**: entram acima das métricas, com o RF-38 a RF-40.

## Consequências

- Mudar o resultado, o KPI ou o apoio de uma regra, ou a sobrescrita de uma campanha, muda a campanha e os anúncios dela sem mudar o painel.
- O resultado do anúncio é o mesmo tipo da campanha, e a soma dos anúncios é o número da campanha (RF-32).
- A página do anúncio não mostra o status dele nem o objetivo da campanha.
