# Meta Ads Dashboard

Painel de análise das campanhas de Meta Ads (Facebook e Instagram) feito para pessoas de negócio, não para especialistas em mídia.

Donos, gestão comercial e marketing veem quanto investiram e o que cada campanha trouxe, seja conversas, cadastros, vendas ou alcance. Não é preciso conhecer o Gerenciador de Anúncios para ler os números.
- **Eixo de entidade**: Geral (todas as contas da empresa) → conta → campanha → anúncio.
- **Eixo de tempo**: dia ou período livre → semana → mês → ano.
- Os números batem entre os níveis, cada métrica tem explicação na tela e o resultado principal de cada campanha aparece de acordo com o objetivo dela.

O sistema é multiempresa e não traz nenhum cliente embutido, onde cada empresa é cadastrada como operação de dados, sem mudança de código.

## Arquitetura em uma linha

Meta Marketing API → ETL em Python (GitHub Actions) → Postgres no Supabase (`bruto` → `normalizado` → `analitico`) → painel em Next.js na Vercel.

## Onde está cada coisa

| Onde | O quê |
|---|---|
| [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) | O que o sistema deve fazer: requisitos com critérios de aceite, catálogo de métricas, restrições de plataforma e questões em aberto |
| [`docs/adr/`](docs/adr/) | Por que: uma decisão de arquitetura por arquivo |
| [`CLAUDE.md`](CLAUDE.md) | Como: regras de desenvolvimento |
| [Issues](https://github.com/GSoaresTech/meta-ads-dashboard/issues) e [milestones](https://github.com/GSoaresTech/meta-ads-dashboard/milestones) | Tarefas, organizadas por épico |

Todos os dados de exemplo deste repositório são fictícios.
