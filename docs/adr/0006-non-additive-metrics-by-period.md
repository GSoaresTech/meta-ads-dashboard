# ADR-0006: Métricas não aditivas por período

- Status: Aceito
- Data: 29/10/2026

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
  - por **semana ISO**: segunda a domingo, um `time_range` por semana, até que a Q-03 confirme o alinhamento de `time_increment=7`;
  - por **mês**: `time_increment=monthly`, documentado como mês de calendário (R-20);
  - por **ano**: um `time_range` de 1º de janeiro até 31 de dezembro ou até hoje.
- A frequência do período é `impressões ÷ alcance` da mesma resposta.
- A execução diária recalcula as semanas, os meses e o ano que tocam a janela de 28 dias. A carga histórica preenche todos os períodos.
- O painel exibe alcance e frequência segundo as regras do `docs/REQUIREMENTS.md` §3.3.

## Consequências

- Uma tabela própria guarda alcance por entidade × tipo de período × início do período, com `UNIQUE` nesse grão. O tamanho é desprezível (`docs/REQUIREMENTS.md` §4.2).
- Chamadas extras por conta na execução diária: cerca de 5 semanas + 2 meses + 1 ano, vezes 3 níveis, com paginação. Isso cabe no limite do nível Limited quando a ETL respeita os cabeçalhos de uso (R-15).
- Fora das quebras, o alcance não tem restrição conhecida de histórico além dos 37 meses. Com quebras, a Meta não devolve alcance para datas a mais de 13 meses em consultas padrão (R-18), outro motivo para não exibir alcance nas quebras.

## Referências

Consultadas em 29/10/2026.
- https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights/
- https://developers.facebook.com/docs/marketing-api/insights/best-practices
