# ADR-0007: Catálogo de métricas e de resultados como dado

- Status: Aceito
- Data: 29/10/2026
- Atualizado em: 04/11/2026, com a janela de atribuição e o formato de `results` verificados na API, em 05/11/2026, com a janela e o desempate do critério de conjuntos divergentes e com os operandos das métricas derivadas, em 11/11/2026, com o resultado fora de `actions`, os legados de mais de um equivalente e os indicadores do pixel na validação, e em 12/11/2026, com a extração dos resultados fora de `actions`

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

- **Tabela de métricas**: código, rótulo, explicação curta, fórmula descritiva, unidade (moeda, número, percentual), aditividade e origem (campo ou `action_type`; na derivada, o numerador, o denominador e o fator da razão, ADR-0009 §2).
- **Tabela de resultado por objetivo**: objetivo da API, meta de otimização (ou "qualquer"), nome do objetivo no painel, métrica de resultado principal, KPI principal e métricas de apoio.
- **Tabela de sobrescrita por campanha**: campanha, métrica de resultado principal e KPI, mantida pelo operador (RF-49).
- **Precedência**: sobrescrita > objetivo + meta de otimização do conjunto > objetivo + "qualquer" > "Não classificado".
- **Conjuntos divergentes**: o resultado é resolvido por conjunto de anúncios. Se os conjuntos de uma campanha divergirem, a campanha usa o do conjunto com maior investimento nos últimos 28 dias (Q-08). Os 28 dias vão até hoje, inclusive, no fuso da conta. No empate, inclusive quando nenhum conjunto investiu na janela, vence o conjunto de menor ID da Meta, em ordem numérica, para que a escolha não mude entre execuções. A campanha sem conjunto usa a regra de "qualquer" do objetivo.
- **Atribuição**: os resultados usam a janela padrão da API, `7d_click` + `1d_view`, o mesmo valor de `results` (R-22, R-24). A ETL não envia `use_unified_attribution_setting` nem `action_attribution_windows`. Se esse valor bate com o Gerenciador nos conjuntos com outra configuração é *a confirmar* (Q-04).
- **Resultado fora de `actions`**: quando o resultado que a Meta conta em `results` não vem em `actions`, a ETL o extrai e grava na tabela longa das ações, no grão anúncio × dia e nas quebras, com o `indicator` de `results` como tipo de ação, com ponto no lugar dos dois-pontos, que o formato do tipo não aceita (ADR-0009 §2). A regra usa a métrica de ação desse tipo, como as demais. São três, todos extraídos e verificados iguais ao valor de `results` (R-24): a visita ao perfil (`profile_visit_view`), que só vem dentro de `results`; o ThruPlay (`video_thruplay_watched_actions`), do campo de mesmo nome; e o contato no site (`conversions.contact_website`), do item `contact_website` do campo `conversions`. O ThruPlay e o contato vêm dos campos próprios, e não de `results`, porque assim valem em todo anúncio, e não só naquele em que são o resultado. Um resultado que ninguém extrai deixa a regra sem resultado principal, para que o painel não mostre o número de outra coisa (`docs/REQUIREMENTS.md` §7.2).
- **Legado de mais de um equivalente**: o equivalente depende do evento do objeto promovido (`CONVERSIONS`) ou do destino do conjunto (`VIDEO_VIEWS`), que o catálogo não guarda (R-40). O legado tem regra própria, no próprio objetivo, sem resultado principal, e a equivalência continua de um legado para um objetivo atual.
- **Seed**: o catálogo global inicial é o do `docs/REQUIREMENTS.md` §7, carregado por migration. Mudanças no catálogo global também entram por migration, como dado versionado. Depois do seed, ele é a fonte da verdade, e o §7 passa a apontar para ele. Sobrescritas e metas são dados operacionais, fora do repositório.
- **Validação**: quando o `indicator` de `results` é `actions:<tipo>` e o tipo tem métrica no catálogo, a ETL compara o resultado do catálogo com o valor de `results` e registra divergências (RF-16, R-24). Os indicadores do pixel (`offsite_conversion.fb_pixel_lead`, `offsite_conversion.fb_pixel_purchase`) não têm métrica própria e valem por `cadastros` e `compras`, iguais a eles em quase todos os conjuntos observados (R-21).

## Consequências

- Objetivos desconhecidos não quebram a carga: viram "Não classificado" e geram aviso (RF-15).
- Rótulos e explicações existem só no catálogo; a tela e a documentação apontam para ele.
- A janela de atribuição de cada conjunto (`janela_atribuicao_conjunto`, ADR-0009) continua no cadastro, mas não entra no cálculo dos resultados.
- As campanhas de visita ao perfil, de ThruPlay e de contato no site mostram o número que a Meta conta em `results` (`docs/REQUIREMENTS.md` §7.2). A visita ao perfil só existe nos anúncios em que ela é o resultado, e por isso só faz sentido como resultado dessas campanhas.
- Pedir `results` faz a API devolver também anúncios e dias sem entrega e sem nenhuma ação, que a transformação descarta, para que a falta de entrega continue sendo a falta da linha (R-24). A linha sem entrega com resultado fica, como a idade desconhecida das quebras, que traz as visitas ao perfil que a Meta não atribui a uma idade (R-23).
- Os dias carregados antes da extração desses resultados não têm os tipos novos. Pela regra da tabela longa, as campanhas de visita ao perfil, de ThruPlay e de contato no site aparecem com zero nesses dias até a reextração deles (RF-07), possível até 37 meses (R-19).
- A comparação do RF-16 lê o tipo de ação de um `indicator` fora de `actions` pela mesma regra do ponto e dos dois-pontos.
- As campanhas com objetivo legado de mais de um equivalente não geram o aviso de "Não classificado" (RF-15), e só as sem equivalente oficial continuam nele.

## Referências

- https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights/ (consultado em 29/10/2026, em 04/11/2026, em 11/11/2026 e em 12/11/2026)
- https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats (consultado em 29/10/2026 e em 11/11/2026)
- https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/ (consultado em 11/11/2026)
- https://developers.facebook.com/blog/post/2025/10/16/ads-insights-api-metric-availability-updates/ (consultado em 04/11/2026)
