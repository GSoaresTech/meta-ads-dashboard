# ADR-0004: Acesso ao painel por link secreto, sem login

- Status: Aceito
- Data: 29/10/2026

## Contexto

Decidimos inicialmente que o painel começa sem autenticação nem tela de login, pois a prioridade é a estrutura do painel. Mas o painel fica numa URL pública e mostra investimento e resultados de várias empresas. Sem nenhuma barreira, qualquer pessoa com a URL veria os dados de todas, o que quebraria o isolamento do ADR-0002.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| **Link secreto por empresa + credencial do operador** | Sem tela de login. Mantém o isolamento entre empresas. Revogar é operação de dados | Não identifica a pessoa. Um link vazado dá acesso até ser revogado |
| Senha única compartilhada (HTTP Basic no middleware) | Mais simples | Quem tem a senha vê todas as empresas: não isola |
| Password Protection da Vercel | Sem código | Indisponível no Hobby; no Pro custa US$ 20/mês por projeto (R-05). Também não isola empresas |
| Vercel Authentication | Disponível no Hobby, para previews e produção | Restringe o acesso a quem tem conta na Vercel com acesso ao projeto (*a confirmar*), o que é inviável para pessoas de negócio; também não isola empresas |
| Público | Zero esforço | Expõe dados de todas as empresas |

## Decisão

Adotar link secreto por empresa e credencial do operador, ambos implementados como **credenciais de acesso** no banco.

- **Credencial**: token aleatório gerado no servidor (recomendado: 32 bytes em base64url) e exibido uma única vez. O banco guarda só o hash SHA-256, o escopo (uma `empresa_id` ou "operador"), a data de criação e a de revogação. Como o token é aleatório e de alta entropia, SHA-256 basta, sem hash lento (RNF-15).
- **Entrada**: o link `/acesso/<token>` troca o token por um cookie `HttpOnly`, `Secure`, `SameSite=Lax` e redireciona para uma URL sem token, para que o token não fique nas URLs de navegação.
  - O cookie guarda o próprio token e é de sessão, sem validade: some quando o navegador fecha, e a pessoa volta pelo link. Como o banco resolve a credencial a cada requisição, a revogação vale já na seguinte (RF-45).
  - O redirecionamento é um 303 com `Cache-Control: no-store`, para que nenhum cache guarde a resposta com o cookie. O link de empresa leva a `/empresas/<id>`, a visão da empresa pelo ID interno, que o operador também abre. O link do operador leva à raiz.
  - O token vai ao banco como parâmetro, nunca no texto do comando, que o Postgres grava no log quando o comando falha. Um valor com caractere fora do base64url não é de nenhuma credencial e é recusado antes de chegar ao banco.
- **Resolução no banco**: o servidor do painel passa a credencial do cookie para funções de `analitico`. Elas calculam o hash, verificam se a credencial não está revogada, resolvem o escopo e filtram os dados. O papel de banco usado pelo painel só pode executar essas funções, sem `SELECT` nas tabelas.
- **Operador**: a credencial do operador dá acesso a todas as empresas e às funções de escrita da área do operador (links, metas, sobrescritas, cadastro de empresa).
- **Rotas**: para credencial inválida, revogada ou fora do escopo, a resposta é 404, não 403, para não revelar se a empresa existe.
- **Cabeçalhos**: `Referrer-Policy: no-referrer`, para que o token não vaze ao clicar em "ver publicação", e `X-Robots-Tag: noindex, nofollow`, contra indexação (RNF-18).
  - Eles vêm do `headers()` do `next.config`, que o roteador do Next.js aplica antes dos redirecionamentos, do Proxy e das rotas, e valem para páginas, rotas, 404 e erros.
  - O redirecionamento da barra no fim do caminho e o caminho que não decodifica saem do roteador sem eles (R-43). O `proxy.ts` responde aos dois no lugar do roteador, com o mesmo 308 e com 400, e as respostas do Proxy recebem os cabeçalhos.

## Consequências

- O isolamento é testável no banco (RNF-14) e independe do código do painel.
- No `next start`, o 308 com que o Next.js troca barras repetidas ou invertidas por uma só sai sem os cabeçalhos, porque nenhuma configuração o alcança (R-43). Ele só leva a outro endereço do próprio painel, que responde com eles.
- Não há auditoria por pessoa. Um link encaminhado dá acesso a quem o recebe; a mitigação é revogar e gerar outro (RF-45).
- A credencial do operador é o segredo mais sensível do painel. Ela é guardada fora do repositório, num gerenciador de senhas, e rotacionada pelo runbook.
- **Gatilhos para migrar ao Supabase Auth**: pedido de acesso individual, necessidade de auditoria por pessoa ou mais de uma pessoa operando. As funções de `analitico` passam então a resolver o escopo por `auth.uid()` e pelo vínculo usuário–empresa (ADR-0002).

## Referências

- https://vercel.com/docs/deployment-protection (consultado em 29/10/2026)
- https://vercel.com/docs/plans/hobby (consultado em 29/10/2026)
