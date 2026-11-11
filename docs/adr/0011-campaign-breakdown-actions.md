# ADR-0011: Ações das quebras por campanha

- Status: Aceito
- Data: 05/11/2026
- Atualizado em: 11/11/2026, com as regras sem resultado principal no lugar da questão em aberto

## Contexto

O RF-03 pede as quebras por campanha e dia nas combinações idade+gênero, plataforma+posicionamento e região, "com as métricas-base e as ações do resultado principal". O ADR-0009 §2 tinha ido além: guardar nas quebras todos os tipos de ação do catálogo de métricas, para que uma sobrescrita do resultado (RF-49) valesse também para o histórico sem reextração. A tabela `normalizado.acao_quebra_diaria_campanha` não muda com nenhuma das duas leituras: ela aceita qualquer tipo de ação.

A quebra por região tem uma restrição da Meta: `region` é do "Tipo 1", e a API não devolve as métricas de ação de fora da Meta com essa quebra (R-23). A documentação não lista quais tipos de ação ficam de fora. A tabela longa de ações segue a regra do `CLAUDE.md` §5: a ausência de linha significa zero, porque a API omite os tipos sem ocorrência. O `CHECK` da tabela também não aceita uma linha com quantidade e valor nulos.

Pontos decididos neste ADR:
- quais tipos de ação a carga das quebras grava;
- como a ausência de um tipo de ação na quebra por região é lida.

## Opções consideradas

### Tipos de ação gravados

| Opção | Prós | Contras |
|---|---|---|
| **(a) Só o tipo de ação do resultado principal de cada campanha, resolvido na carga** | É o que o RF-03 pede. Menos linhas que o ADR-0009 previa | Uma mudança do resultado (sobrescrita, ou outro conjunto passando a dominar o investimento) só chega às quebras dos dias recarregados |
| (b) Todos os tipos de ação do catálogo (ADR-0009 §2) | A sobrescrita vale para o histórico sem reextração | Grava ações que o painel não mostra nas quebras; volume que a §4.2 não estimou |
| (c) Todos os tipos de ação da resposta | Nada se perde | Mais volume ainda, com tipos que nenhuma métrica do catálogo lê |

### Ausência de ação na quebra por região

| Opção | Prós | Contras |
|---|---|---|
| **(a) Gravar só o que a API devolve e registrar que, na região, a ausência de um tipo de ação de fora da Meta é "não disponível"** | Não inventa zero nem valor. As ações da Meta, como conversas e cliques no link, ficam | A leitura depende de saber quais tipos são de fora da Meta, e isso ainda não está no catálogo |
| (b) Marcar já no catálogo, por migration, as métricas de ação de fora da Meta | A regra vira dado desde já (ADR-0007) | Sai do escopo da extração. A lista de tipos ainda não foi verificada (Q-12) |
| (c) Não gravar ações na quebra por região | Simples | Descarta ações da Meta que a API devolve na região |

## Decisão

- **Tipos de ação**: a carga das quebras grava, para cada campanha, só o tipo de ação da métrica de resultado principal dela, com a quantidade e o valor. O valor serve às métricas de apoio do mesmo tipo, como o valor das compras.
  - O resultado principal vem de `normalizado.resolver_resultado_campanha` (ADR-0009 §4), lida na transação da carga, depois das entidades. A mesma resolução vale para todos os dias da janela carregada.
  - A carga das quebras roda depois da dos insights diários da mesma janela, porque a resolução usa os conjuntos e o investimento dos últimos 28 dias que ela carrega. Uma campanha que só as quebras trazem é lida pelo ID sem os conjuntos, e resolve pela regra de "qualquer" do objetivo até a próxima recarga desses dias.
  - A campanha cujo resultado não é métrica de ação, como o alcance, ou que não tem resultado, como "Não classificado" e as regras sem resultado principal (`docs/REQUIREMENTS.md` §7.2), fica sem ações nas quebras. As métricas-base dela são gravadas normalmente.
  - Isto substitui o ponto "Ações das quebras" do ADR-0009 §2.
- **Região**: a carga grava só os tipos de ação que a API devolve, sem completar os ausentes com zero.
  - Na quebra por região, a falta de linha de um tipo de ação de fora da Meta significa "não disponível", e não zero. É a única exceção à regra da tabela longa do `CLAUDE.md` §5.
  - A função de `analitico` que lê as quebras (RF-36) aplica essa leitura, e o painel avisa quando o resultado principal da campanha é desse tipo (`docs/REQUIREMENTS.md` §3.3).
  - Quais tipos de ação do catálogo são de fora da Meta ainda não está verificado (Q-12). Quando estiver, a marcação entra no catálogo, como dado (ADR-0007).

## Consequências

- **Mudança de resultado**: uma sobrescrita (RF-49), ou um conjunto que passa a dominar o investimento da campanha (ADR-0007), só chega às quebras nos dias recarregados. Na execução diária, são os 28 dias da janela (RF-05). Os dias anteriores ficam sem linha do tipo novo até uma recarga histórica das quebras da campanha (RF-07), possível até 37 meses (R-19). O banco não guarda qual tipo cada dia carregou, e, pela regra da tabela longa, esses dias aparecem com zero do resultado novo até a recarga.
- **Volume**: no máximo uma linha de ação por linha de quebra, abaixo do que o ADR-0009 previa. A medição da Q-09 continua valendo para a estimativa da §4.2.
- **Região e compras**: o `omni_purchase` soma compras na Meta e fora dela. Se a API o devolver na região só com a parte da Meta, o número gravado é parcial, e não ausente. Isso faz parte da Q-12.

## Referências

Consultadas em 05/11/2026.
- https://developers.facebook.com/documentation/ads-commerce/marketing-api/insights/breakdowns.md
