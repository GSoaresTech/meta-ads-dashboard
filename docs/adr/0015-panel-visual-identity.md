# ADR-0015: Identidade visual do painel

- Status: Aceito
- Data: 06/11/2026

## Contexto

O painel usava o estilo padrão do navegador, com poucas cores definidas em cada componente. As próximas visões precisam nascer com o mesmo visual, sem que cada uma escolha os próprios valores. O visual também não pode piorar a acessibilidade pedida no RNF-03.

Pontos decididos neste ADR:
- Onde os valores visuais ficam;
- Quais fontes usamos;
- Como garantir que as próximas páginas sigam a identidade.

## Opções consideradas

### Onde ficam os valores

| Opção | Prós | Contras |
|---|---|---|
| **Variáveis CSS num só arquivo, lidas pelos CSS Modules que o painel já usa** | Nenhuma dependência nova. O gráfico lê as mesmas variáveis | A regra precisa de uma verificação própria |
| Tailwind | Limita os valores pela configuração | Dependência e troca da forma de estilizar em todos os componentes |
| Biblioteca de componentes | Componentes prontos | Traz um visual próprio, que teríamos de desfazer |

### Fontes

| Opção | Prós | Contras |
|---|---|---|
| **Inter Tight nos títulos e Inter no texto, pelo `next/font`** | Gratuitas, com acentos, e servidas pelo próprio painel, sem requisição ao Google no navegador | O build precisa de acesso à rede |
| Fonte comercial nos títulos | Mais personalidade | Licença paga por uso |
| Fontes do sistema | Nenhum download | O visual muda de um aparelho para outro |

### Como garantir nas próximas páginas

| Opção | Prós | Contras |
|---|---|---|
| **Regra no `CLAUDE.md` e um teste que percorre os CSS e os componentes** | A CI barra o desvio, inclusive em arquivo novo, sem dependência | Cobre cor, sombra e fonte, e não o uso correto de cada token |
| Só a regra escrita | Nenhum código | Nada impede o desvio |
| Stylelint | Regras mais finas | Mais uma ferramenta na CI, e não olha os componentes `.tsx` |

## Decisão

- **Tokens**: `web/app/tokens.css` é o único lugar com valores literais de cor, fonte, escala, espaço e raio. Os elementos sem classe ficam em `web/app/estilos-globais.css`.
- **Tipografia**: títulos na fonte de título, sempre com peso 400 e tracking de -0,02em. O restante na fonte de texto.
- **Cor**: a página é quase toda acromática, com dois acentos, a brasa e o latão. Azul, verde e outras cores ficam de fora, inclusive para status.
- **Profundidade**: vem da cor da superfície, sem sombra. Os painéis são cinza, e os cartões de dados, brancos sobre eles. As seções se separam por 80 px de espaço, sem linha.
- **Raios**: botão 0, painel `6px 0 0`, cartão de dados e etiqueta 20 px, dica 8 px e pílula de navegação 200 px.
- **Gráficos**: a linha usa a brasa, e a segunda série, quando houver, o latão.
- **Verificação**: o `web/tests/design.test.ts` falha com cor, sombra ou fonte fora dos tokens (RNF-26).

Duas cores têm uso limitado pelo contraste no branco (RNF-03):

| Token | Contraste | Uso |
|---|---|---|
| `--cor-brasa` | 2,9:1 | Sublinhado de link e marca de gráfico. Nunca texto ou fundo de botão |
| `--cor-ardosia` | 3,9:1 | Decoração, como separadores, sublinhados e bordas. Nunca texto que precisa ser lido |

## Consequências

- O texto secundário usa `--cor-aco`, com contraste de 8,5:1.
- Com contraste abaixo de 3:1, a linha do gráfico depende da tabela "Ver os dados", que traz cada valor em texto.
- O build depende de acesso às fontes do Google, o que vale para a CI e para a Vercel.
- O teste não julga composição: o uso certo de cada superfície e raio continua na revisão.
