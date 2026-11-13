# ADR-0021: Comparação com o período anterior

- Status: Aceito
- Data: 13/11/2026

## Contexto

O RF-27 pede, ao lado de cada métrica, a variação percentual em relação ao período anterior equivalente. O critério de aceite fixa dois casos: "mês passado" (setembro) compara com agosto, e um intervalo livre de 10 dias, com os 10 dias imediatamente anteriores. Sem dado no período anterior, a variação é "—". A issue pede ainda que uma queda de custo apareça como melhora.

Faltava definir:
- O período anterior de "este mês" e "este ano", que vão até hoje (ADR-0012), e o de um intervalo de meses inteiros;
- Onde fica a regra de que a alta de uma métrica é melhora ou piora;
- Como a melhora e a piora aparecem numa página quase toda acromática, em que nenhuma cor entra para status (ADR-0015);
- Em quais lugares da página a variação aparece.

## Opções consideradas

### Período anterior de "este mês" e "este ano"

| Opção | Prós | Contras |
|---|---|---|
| **O mesmo trecho do mês ou do ano anterior** | "Este mês" em 13/11 compara 01–13/11 com 01–13/10, e "este ano", o ano até a data com o mesmo trecho do ano passado, o que respeita a sazonalidade | O mesmo intervalo pode ser dois atalhos, como 01–13/01, que é "este mês" e "este ano". A regra depende do atalho, e não só das datas |
| Os mesmos N dias imediatamente antes | Regra única pelas datas, como o "período anterior" do Gerenciador de Anúncios | "Este ano" em 13/11 compara com 17/02–31/12 do ano passado, que mistura meses diferentes, com a Black Friday e o Natal |

### Sentido da melhora

| Opção | Prós | Contras |
|---|---|---|
| **Atributo do catálogo, com `alta`, `queda` e `indiferente`** | Segue o ADR-0007: a tela não tem regra de métrica, e uma métrica nova escolhe o sentido na migration que a cria | Uma coluna a mais no catálogo |
| Regra na tela pelo código ou pela unidade, como "custo melhora na queda" | Nenhuma mudança no banco | Lista de métricas no código, contra o ADR-0007. A unidade não basta: o valor das compras é moeda e melhora na alta |

### Indicação de melhora e piora

| Opção | Prós | Contras |
|---|---|---|
| **Seta da direção e a palavra "melhora" ou "piora", em texto secundário** | Segue o ADR-0015, sem cor. A palavra é lida pelo leitor de tela e não depende de distinguir cores | Ocupa uma linha a mais no cartão |
| Verde para melhora e vermelho para piora | Convenção conhecida | Contra o ADR-0015, que não admite cor de status, e ilegível para quem não distingue as duas cores |

### Onde a variação aparece

| Opção | Prós | Contras |
|---|---|---|
| **No cartão de cada métrica: os totais do Geral e da conta, o destaque e o apoio da campanha e as métricas do anúncio** | Uma leitura a mais por visão, só da entidade em foco | A lista de campanhas e as séries ficam sem variação |
| Também em cada linha da lista de campanhas | Mostra qual campanha melhorou | Uma leitura do período anterior para todas as campanhas, e a lista compara as campanhas entre si, não com o passado |

## Decisão

- **Período anterior**: uma única função do painel o calcula a partir do atalho ou do intervalo livre e do intervalo já resolvido:
  - "este mês": do primeiro dia do mês anterior até o mesmo dia dele, ou até o último dia, se o mês anterior for mais curto;
  - "este ano": do primeiro dia do ano anterior até a mesma data dele, com 29/02 virando 28/02;
  - "hoje", "ontem" e os últimos 7 e 30 dias: o mesmo número de dias imediatamente antes, mesmo quando o intervalo cobre um mês inteiro, como os últimos 30 dias em 1º de maio;
  - "mês passado" e o intervalo livre de meses inteiros, do primeiro dia de um mês ao último dia de outro, como de setembro a outubro: o mesmo número de meses inteiros imediatamente antes;
  - o intervalo livre que não é de meses inteiros: o mesmo número de dias imediatamente antes.
- **Valor anterior**: o total do período anterior, lido pela `analitico.obter_desempenho` com a granularidade `periodo`, da entidade em foco e das mesmas métricas. A granularidade escolhida não muda a comparação.
- **Variação**: (atual − anterior) ÷ anterior, arredondada na casa exibida, para que a seta e a avaliação nunca acompanhem um "0%". É "—" quando o período anterior não tem o valor, quando ele é nulo ou zero, ou quando o atual não tem valor. As razões já vêm recalculadas das somas de cada período (RF-33).
- **Sentido**: a coluna `sentido_melhora` de `normalizado.metrica`, sem valor padrão, com `alta`, `queda` ou `indiferente`, lida pela `analitico.listar_metricas`. Todo custo melhora na queda. O investimento e a frequência são indiferentes, porque gastar mais ou repetir mais o anúncio depende do plano da campanha.
- **Exibição**: abaixo do valor do cartão, a seta da direção e a variação, seguidas de "melhora" ou "piora" quando a métrica não é indiferente e a variação não é zero. O intervalo do período anterior aparece uma vez na página, abaixo do intervalo selecionado.

## Consequências

- Mudar o sentido de uma métrica é migration no catálogo, sem mudar componente.
- O mesmo intervalo pode ter períodos anteriores diferentes conforme o atalho: em janeiro, "este mês" compara com dezembro, e "este ano", com o mesmo trecho de janeiro do ano anterior. A página mostra as datas do período anterior.
- "Hoje" e "este mês" e "este ano", que vão até hoje, comparam um dia parcial com um dia inteiro. O indicador de dados parciais da página (RF-28) avisa disso.
- A métrica que a leitura não traz, como o alcance (ADR-0013), fica com a variação "—".
- **Gatilho de revisão**: se a lista de campanhas precisar mostrar quem melhorou, a variação entra nela com uma leitura do período anterior para as campanhas.
