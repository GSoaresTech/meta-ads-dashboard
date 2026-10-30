# ADR-0007: Catálogo de métricas e de resultados como dado

- Status: Aceito
- Data: 29/10/2026

## Contexto

As campanhas têm objetivos diferentes e, portanto, resultados diferentes: reconhecimento, tráfego, conversas, cadastros, vendas. O mapeamento objetivo → resultado principal muda com o tempo (objetivos legados, novas metas de otimização) e tem exceções por campanha, como uma campanha de engajamento usada para gerar conversas. Rótulos e explicações das métricas precisam ser iguais na tela, nas consultas e na documentação.

A API documenta `cost_per_result` (R-24), mas o formato do campo de resultados e a equivalência dele com a coluna "Resultados" do Gerenciador não estão confirmados (Q-05).

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| **Catálogo em tabelas, com seed por migration e sobrescrita por campanha** | Muda sem alterar código; rótulo, explicação e fórmula numa única fonte; exceções viram linhas | Exige telas ou funções para a sobrescrita |
| Lógica no código (`switch` por objetivo) | Direta | Toda mudança vira deploy; textos divergem entre telas |
| Usar só o campo de resultados da API | Fiel ao Gerenciador | Formato não confirmado; sem rótulo de negócio; sem sobrescrita |

## Decisão

- **Tabela de métricas**: código, rótulo, explicação curta, fórmula descritiva, unidade (moeda, número, percentual), aditividade e origem (campo ou `action_type`).
- **Tabela de resultado por objetivo**: objetivo da API, meta de otimização (ou "qualquer"), nome do objetivo no painel, métrica de resultado principal, KPI principal e métricas de apoio.
- **Tabela de sobrescrita por campanha**: campanha, métrica de resultado principal e KPI, mantida pelo operador (RF-49).
- **Precedência**: sobrescrita > objetivo + meta de otimização do conjunto > objetivo + "qualquer" > "Não classificado".
- **Conjuntos divergentes**: o resultado é resolvido por conjunto de anúncios. Se os conjuntos de uma campanha divergirem, a campanha usa o do conjunto com maior investimento nos últimos 28 dias (Q-08).
- **Atribuição**: os resultados usam a configuração de atribuição de cada conjunto (`use_unified_attribution_setting=true`), para que os números se aproximem do Gerenciador (R-22; Q-04).
- **Seed**: o catálogo global inicial é o do `docs/REQUIREMENTS.md` §7, carregado por migration. Mudanças no catálogo global também entram por migration, como dado versionado. Depois do seed, ele é a fonte da verdade, e o §7 passa a apontar para ele. Sobrescritas e metas são dados operacionais, fora do repositório.
- **Validação**: quando o campo de resultados da API estiver confirmado, a ETL compara o resultado do catálogo com ele e registra divergências (RF-16).

## Consequências

- Objetivos desconhecidos não quebram a carga: viram "Não classificado" e geram aviso (RF-15).
- Rótulos e explicações existem só no catálogo; a tela e a documentação apontam para ele.

## Referências

- https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights/ (consultado em 29/10/2026)
- https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats (consultado em 29/10/2026)
