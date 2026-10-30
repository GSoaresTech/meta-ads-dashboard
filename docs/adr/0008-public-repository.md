# ADR-0008: Repositório público

- Status: Aceito
- Data: 29/10/2026

## Contexto

Seguimos o desenvolvimento em um repositório público, no GitHub, como portfólio e material acessível para qualquer usuário. O sistema trata dados comerciais de empresas atendidas (investimento, resultados, nomes de campanhas), que não podem vazar. Num repositório público, ficam visíveis o código, o histórico do Git, issues, PRs e, para qualquer conta logada, os logs e artefatos do GitHub Actions (R-09).

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| **Público** | Portfólio; executores do Actions gratuitos (R-07); varredura de segredos gratuita (R-11) | Logs, artefatos e histórico expostos; workflows agendados desativados após 60 dias sem atividade (R-08) |
| Privado, plano Free do GitHub | Código fechado | Cota de Actions limitada, que a carga horária tende a esgotar; proteção de branch possivelmente só em plano pago |
| Privado, plano pago do GitHub | Código fechado, com proteção | Custo mensal |

## Decisão

Repositório público. As salvaguardas viram regras do `CLAUDE.md`:
- Dados reais de empresa fora de arquivos, logs, issues e PRs (§4);
- Logs só com campos de uma lista permitida (§8);
- Segredos, workflows e artefatos (§12).

## Consequências

- O código e as decisões ficam visíveis. Quem conhece o desenho não ganha acesso, porque os dados dependem de credenciais fora do repositório.
- O risco que sobra é erro humano, como um print com dado real ou uma fixture mal anonimizada. A revisão do diff linha a linha (CLAUDE.md §9) e a varredura automática de segredos reduzem esse risco.
- Os workflows agendados dependem de atividade no repositório a cada 60 dias (Q-11).

## Referências

Consultadas em 29/10/2026.
- https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/monitoring-workflows/using-workflow-run-logs
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts
- https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions
- https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions
- https://docs.github.com/en/code-security/secret-scanning/introduction/about-secret-scanning
- https://docs.github.com/en/code-security/secret-scanning/introduction/about-push-protection
- https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows
