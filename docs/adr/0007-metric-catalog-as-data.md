# ADR-0007: Catálogo de métricas e de resultados como dado

- Status: Aceito
- Data: 29/10/2026
- Atualizado em: 04/11/2026, com a janela de atribuição e o formato de `results` verificados na API

## Contexto

As campanhas têm objetivos diferentes e, portanto, resultados diferentes: reconhecimento, tráfego, conversas, cadastros, vendas. O mapeamento objetivo → resultado principal muda com o tempo (objetivos legados, novas metas de otimização) e tem exceções por campanha, como uma campanha de engajamento usada para gerar conversas. Rótulos e explicações das métricas precisam ser iguais na tela, nas consultas e na documentação.

O campo `results` da API traz, em cada item, o `indicator` do resultado que a Meta escolheu e o valor na janela padrão (R-24). Parte desses indicadores são métricas fora do catálogo, como ThruPlays e visitas ao perfil (R-24; `docs/REQUIREMENTS.md` §7.2).

A referência diz que `use_unified_attribution_setting=true` reproduz o Gerenciador. Nos testes de 04/11/2026, o parâmetro não mudou nenhum valor: o que a API devolve é igual à janela padrão, `7d_click` + `1d_view`, em mais de 99% dos casos, mesmo nos conjuntos com outra configuração. O `attribution_setting` dos insights também diverge do `attribution_spec` do conjunto (R-22).

## Opções consideradas

### Catálogo

| Opção | Prós | Contras |
|---|---|---|
| **Catálogo em tabelas, com seed por migration e sobrescrita por campanha** | Muda sem alterar código; rótulo, explicação e fórmula numa única fonte; exceções viram linhas | Exige telas ou funções para a sobrescrita |
| Lógica no código (`switch` por objetivo) | Direta | Toda mudança vira deploy; textos divergem entre telas |
| Usar só o campo de resultados da API | Mesmo resultado que a Meta escolhe | Sem rótulo de negócio; sem sobrescrita; parte dos indicadores não está no catálogo (R-24) |

### Atribuição

| Opção | Prós | Contras |
|---|---|---|
| **Janela padrão da API** (`7d_click` + `1d_view`) | É o valor de `actions` e de `results` sem parâmetro algum; nenhuma mudança de schema | Pode divergir do Gerenciador nos conjuntos configurados só com clique ou com visualização engajada (Q-04) |
| Pedir as janelas explícitas e somar as da configuração de cada conjunto | Pode se aproximar do Gerenciador nesses conjuntos | A configuração diverge entre o cadastro do conjunto e os insights, então não há fonte confiável dela (R-22). As quebras, extraídas por campanha, teriam de passar a ser extraídas por conjunto |
| `use_unified_attribution_setting=true` (decisão anterior) | Documentado como igual ao Gerenciador | Não muda nenhum valor (R-22) |

## Decisão

- **Tabela de métricas**: código, rótulo, explicação curta, fórmula descritiva, unidade (moeda, número, percentual), aditividade e origem (campo ou `action_type`).
- **Tabela de resultado por objetivo**: objetivo da API, meta de otimização (ou "qualquer"), nome do objetivo no painel, métrica de resultado principal, KPI principal e métricas de apoio.
- **Tabela de sobrescrita por campanha**: campanha, métrica de resultado principal e KPI, mantida pelo operador (RF-49).
- **Precedência**: sobrescrita > objetivo + meta de otimização do conjunto > objetivo + "qualquer" > "Não classificado".
- **Conjuntos divergentes**: o resultado é resolvido por conjunto de anúncios. Se os conjuntos de uma campanha divergirem, a campanha usa o do conjunto com maior investimento nos últimos 28 dias (Q-08).
- **Atribuição**: os resultados usam a janela padrão da API, `7d_click` + `1d_view`, o mesmo valor de `results` (R-22, R-24). A ETL não envia `use_unified_attribution_setting` nem `action_attribution_windows`. Se esse valor bate com o Gerenciador nos conjuntos com outra configuração é *a confirmar* (Q-04).
- **Seed**: o catálogo global inicial é o do `docs/REQUIREMENTS.md` §7, carregado por migration. Mudanças no catálogo global também entram por migration, como dado versionado. Depois do seed, ele é a fonte da verdade, e o §7 passa a apontar para ele. Sobrescritas e metas são dados operacionais, fora do repositório.
- **Validação**: quando o `indicator` de `results` é `actions:<tipo>` e o tipo tem métrica no catálogo, a ETL compara o resultado do catálogo com o valor de `results` e registra divergências (RF-16, R-24). Os indicadores de pixel (`offsite_conversion.fb_pixel_lead`, `offsite_conversion.fb_pixel_purchase`) não têm métrica própria no catálogo, e compará-los com `lead` e `omni_purchase`, iguais nas campanhas observadas (R-21), depende da Q-10.

## Consequências

- Objetivos desconhecidos não quebram a carga: viram "Não classificado" e geram aviso (RF-15).
- Rótulos e explicações existem só no catálogo; a tela e a documentação apontam para ele.
- A janela de atribuição de cada conjunto (`janela_atribuicao_conjunto`, ADR-0009) continua no cadastro, mas não entra no cálculo dos resultados.
- As combinações de objetivo e meta de otimização sem linha própria no catálogo caem na linha genérica do objetivo até a Q-10 ser resolvida (`docs/REQUIREMENTS.md` §7.2).

## Referências

- https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights/ (consultado em 29/10/2026 e em 04/11/2026)
- https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats (consultado em 29/10/2026)
- https://developers.facebook.com/blog/post/2025/10/16/ads-insights-api-metric-availability-updates/ (consultado em 04/11/2026)
