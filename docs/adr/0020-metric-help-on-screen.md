# ADR-0020: Ajuda das métricas na tela

- Status: Aceito
- Data: 13/11/2026

## Contexto

Toda métrica exibida tem rótulo de negócio e explicação curta, lidos do catálogo (RF-30; RNF-01; ADR-0007). O cartão de cada métrica trazia a explicação num parágrafo sempre visível, mas a série e as células de resultado e de custo da lista de campanhas mostravam só o rótulo. A mesma métrica aparece várias vezes numa página: no cartão, na série e em cada campanha da lista. A ajuda precisa abrir pelo teclado e ser lida pelo leitor de tela (RNF-03).

Pontos decididos neste ADR:
- Como a explicação aparece;
- Em quais lugares ela aparece.

## Opções consideradas

### Forma da ajuda

| Opção | Prós | Contras |
|---|---|---|
| **Um "O que é isso?" que abre a explicação, com `details` e `summary` nativos** | O navegador põe o controle na ordem do teclado, abre com Enter ou espaço e diz ao leitor de tela se está aberto. Funciona sem JavaScript, e os componentes continuam sendo do servidor | A explicação fica a um toque de distância, e o bloco aberto empurra o conteúdo abaixo dele |
| Parágrafo sempre visível, como no cartão | Nenhuma ação para ler | Repetido em cada série e em cada linha da lista, o texto pesa mais que os números |
| Dica ao passar o cursor, pelo atributo `title` ou por um componente próprio | Não ocupa espaço | O `title` não abre pelo teclado nem no toque. O componente próprio exige JavaScript no navegador e o tratamento do foco, do Esc e do anúncio ao leitor de tela |

### Onde a ajuda aparece

| Opção | Prós | Contras |
|---|---|---|
| **Em cada lugar com o rótulo de uma métrica: o cartão, a série e as células de resultado e de custo da lista de campanhas** | Quem lê qualquer número tem a explicação ao lado dele | A mesma explicação se repete na página |
| Só no cartão | Uma ajuda por métrica | A série e a lista ficam sem explicação, e a lista mostra resultados que não têm cartão na página |

## Decisão

- **Forma**: o controle "O que é isso?" abre a explicação do catálogo, com `details` e `summary`, e começa fechado. O rótulo da métrica entra oculto no controle, só para o leitor de tela, para que as ajudas de uma página tenham nomes diferentes: "O que é isso? (Investimento)".
- **Lugares**: o cartão, abaixo do valor, no lugar do parágrafo; a série, abaixo da legenda, que continua sendo só o rótulo; e cada célula de resultado e de custo da lista de campanhas, abaixo do valor. A célula sem métrica, com "—", não tem ajuda.
- **Origem**: o texto vem só do catálogo, pela mesma leitura que traz o rótulo (`analitico.listar_metricas`). Nenhum componente tem texto de métrica.
- **Verificação**: os testes de integração de cada visão leem todas as métricas exibidas e falham se alguma não tiver a ajuda com a explicação do catálogo (RF-30).

## Consequências

- A explicação deixa de ficar sempre visível no cartão e passa a abrir no "O que é isso?", como no resto da página.
- Mudar uma explicação no catálogo muda todas as ajudas da métrica, sem mudar componente.
- A explicação fechada continua no HTML, e por isso entra na verificação do RNF-02 sobre o texto da página.
