# ADR-0006: Métricas não aditivas por período

- Status: Aceito
- Data: 29/10/2026
- Atualizado em: 04/11/2026, com o alinhamento de `time_increment` verificado na API, o filtro de status por nível e o início dos períodos tirado do calendário

## Contexto

Alcance conta pessoas únicas, então não pode ser somado entre dias, entre anúncios nem entre contas: o alcance de um mês não é a soma do alcance dos dias. A frequência deriva do alcance e herda a mesma limitação. Mesmo assim, o alcance é o resultado principal das campanhas de reconhecimento (`docs/REQUIREMENTS.md` §7.2), e as visões semanal, mensal e anual são as mais usadas por gestão.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| **Extrair da API já agregado por semana ISO, mês e ano**, por entidade | Valor correto, deduplicado pela Meta; o painel continua lendo só o banco | Chamadas extras na execução diária e na histórica; não cobre o período livre |
| Consultar a API ao vivo no período livre | Cobre qualquer intervalo | Exige token da Meta no servidor do painel e depende do limite de taxa no momento da consulta; quebra a regra de o painel ler só o banco |
| Mostrar só na visão diária | Simples | Perde o KPI das campanhas de reconhecimento nas visões de gestão |

## Decisão

- Extrair `reach` e `impressions` agregados pela API para cada conta, campanha e anúncio:
  - por **semana ISO**: segunda a domingo, com `time_increment=7` e o `since` numa segunda-feira. Os blocos começam no `since` e seguem de 7 em 7 dias, cada um com o alcance deduplicado no próprio bloco (R-20);
  - por **mês**: `time_increment=monthly`, com o `since` no dia 1, porque o primeiro bloco começa no `since` e vai até o fim do mês (R-20);
  - por **ano**: um `time_range` de 1º de janeiro até 31 de dezembro ou até hoje.
- Nos níveis de campanha e de anúncio, a consulta filtra `ad.effective_status` pela lista de status do cadastro mais `DELETED`, como a dos insights diários. A lista por nível omite os objetos excluídos, cujas métricas entram no total do pai, e esse é o filtro que a Meta documenta para eles (R-38). O nível de conta vai sem filtro.
- A semana e o mês em andamento vêm cortados no `until`. Um período sem entrega não vem na resposta e não gera linha (R-20).
- A frequência do período é `impressões ÷ alcance` da mesma resposta.
- A execução diária recalcula as semanas, os meses e o ano que tocam a janela de 28 dias. O `since` de cada consulta vem de `normalizado.calendario`: a segunda-feira da semana do primeiro dia da janela, o dia 1 do mês dele e o 1º de janeiro de cada ano que a janela toca. O `until` é o último dia da janela, e a janela que cruza a virada do ano consulta os dois anos. A carga histórica preenche todos os períodos.
- O painel exibe alcance e frequência segundo as regras do `docs/REQUIREMENTS.md` §3.3.

## Consequências

- Uma tabela própria guarda alcance por entidade × tipo de período × início do período, com `UNIQUE` nesse grão. O tamanho é desprezível (`docs/REQUIREMENTS.md` §4.2).
- Chamadas extras por conta na execução diária: uma consulta para as semanas, uma para os meses e uma para cada ano, vezes 3 níveis, com paginação, fatiadas ou por job assíncrono quando a resposta síncrona falha por excesso de linhas (R-39). Isso cabe no limite do nível Limited quando a ETL respeita os cabeçalhos de uso (R-15).
- O filtro por `ad.effective_status` no nível de campanha segue o exemplo da documentação, que usa filtros `ad.*` nesse nível. Nenhuma das contas conferidas tem objeto excluído com insights em 37 meses (R-38), então a leitura de uma campanha excluída por esse filtro não foi observada.
- Fora das quebras, o alcance não tem restrição conhecida de histórico além dos 37 meses, e veio em semanas de até 36 meses atrás (R-18). Com quebras, a Meta não devolve alcance para datas a mais de 13 meses em consultas padrão (R-18), outro motivo para não exibir alcance nas quebras.
- Na carga histórica, a semana, o mês e o ano que começam antes do limite de 37 meses (R-19) ficam sem alcance: a API recusa o `since` anterior ao limite, e um bloco iniciado depois da segunda-feira, do dia 1 ou de 1º de janeiro não é o período inteiro. O ano mais antigo do histórico fica sempre nessa situação, salvo quando o limite cai em 1º de janeiro. O painel mostra esses períodos como "Não disponível" (`docs/REQUIREMENTS.md` §3.3).

## Referências

Consultadas em 29/10/2026.
- https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights/
- https://developers.facebook.com/docs/marketing-api/insights/best-practices

Consultadas em 04/11/2026.
- https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights/
- https://developers.facebook.com/blog/post/2025/10/16/ads-insights-api-metric-availability-updates/
- https://developers.facebook.com/documentation/ads-commerce/marketing-api/best-practices/manage-your-ad-object-status.md
- https://developers.facebook.com/docs/marketing-api/insights/best-practices
