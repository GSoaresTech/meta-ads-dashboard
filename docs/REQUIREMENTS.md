# Requisitos

Painel de análise de campanhas da Meta Ads para pessoas de negócio. Este documento diz **o que** o sistema deve fazer e como verificar cada requisito. O porquê das decisões está em `docs/adr/`, as regras de desenvolvimento no `CLAUDE.md` e as tarefas nas issues do GitHub.

Prioridades (MoSCoW):
- **Must**: sem ele, o objetivo central não é atendido.
- **Should**: importante, mas o produto funciona sem.
- **Could**: desejável.

O que foi descartado está na §1.2. Itens marcados *a confirmar* ainda não foram verificados na documentação oficial e precisam ser confirmados antes de virar código.

---

## 1. Objetivo e escopo

### 1.1 Objetivo

Pessoas de negócio (donos, gestão comercial, marketing) precisam entender o resultado dos anúncios da empresa no Facebook e no Instagram sem conhecer o Gerenciador de Anúncios. O painel organiza os números em dois eixos combináveis, entidade e tempo, sempre consistentes entre os níveis. Também destaca o resultado que importa para cada campanha e usa linguagem e formatos brasileiros.

O sistema é genérico e multiempresa. Ele nasce sem cliente, e cada empresa entra como operação de dados, sem mudança de código.

### 1.2 Fora do escopo

| Item | Motivo | Quando Implementar |
|---|---|---|
| Login e contas de usuário (Supabase Auth), papéis por pessoa | Decisão de produto: o painel começa sem login (ADR-0004) | Gatilhos do ADR-0004 |
| Conjunto de anúncios como nível de navegação | Decisão de produto: o nível mais detalhado é o anúncio | Pedido explícito do negócio |
| Quebras no nível de anúncio | Decisão de produto: volume e custo de armazenamento (§4.2) | Pedido explícito do negócio |
| Conversão de moeda | Decisão de produto: totais separados por moeda (RF-34) | Empresa com contas em várias moedas |
| Histórico de mudanças de nome, status e orçamento | Decisão de produto: basta o estado atual das entidades | Pedido explícito do negócio |
| Dados pessoais e leads individuais de formulários | LGPD; o produto trabalha só com agregados (RNF-24) | Não previsto |
| Outras fontes (Google Ads, GA4, CRM) | Decisão de produto: foco em Meta Ads | Novo épico, por decisão de negócio |
| Criar, editar ou pausar campanhas | O painel é somente leitura (`ads_read`) | Não previsto |
| Dados com defasagem menor que 1 hora | A atualização é horária (ADR-0005) | Não previsto |

---

## 2. Usuários, papéis e decisões apoiadas

| Papel | Quem é | Como acessa | O que vê e faz | Decisões que o painel apoia |
|---|---|---|---|---|
| Operador | Equipe que opera o sistema e a BM | Credencial do operador (ADR-0004) | Todas as empresas. Cadastra empresas e contas, gera e revoga links, cadastra metas, sobrescreve o resultado principal de campanhas e acompanha as cargas | Quais empresas estão com dados atrasados ou com falha; se o catálogo classifica bem as campanhas |
| Leitor de empresa | Dono, gestão comercial ou marketing de uma empresa atendida | Link secreto da empresa | Somente os dados da própria empresa, em leitura | Quanto investir por mês; quais campanhas manter ou cortar; qual anúncio funciona melhor; se o custo por resultado está dentro da meta; qual público e qual plataforma respondem melhor |

Sem login (ADR-0004), o sistema não identifica pessoas: quem tem o link de uma empresa é leitor dela.

---

## 3. Mapa de navegação

### 3.1 Eixo de entidade

| Nível | O que é | O que mostra |
|---|---|---|
| Geral | Todas as contas de anúncio da empresa | Totais por moeda de investimento e de cada tipo de resultado; série temporal; lista de contas; quebras; metas da empresa |
| Conta | Uma conta de anúncios | Totais da conta; série temporal; lista de campanhas com objetivo em linguagem de negócio, resultado principal e custo por resultado; quebras |
| Campanha | Uma campanha | Cartão de destaque com o resultado principal e o KPI do objetivo; métricas de apoio; série temporal; lista de anúncios; quebras; meta da campanha |
| Anúncio ("criativo") | Um anúncio, com seu criativo | Miniatura, link "ver publicação", prévia ao passar o cursor; métricas e série temporal; sem quebras |

O conjunto de anúncios existe nos dados e liga o anúncio à campanha. A meta de otimização dele ajuda a definir o resultado principal (§7.2), mas ele não aparece na navegação.

### 3.2 Eixo de tempo

| Granularidade | Definição |
|---|---|
| Dia ou período livre | Um dia ou um intervalo qualquer. Atalhos: hoje (parcial), ontem, últimos 7 dias, últimos 30 dias, este mês, mês passado, este ano e intervalo livre |
| Semana | Semana ISO 8601, de segunda a domingo. Na virada do ano, a semana pertence ao ano ISO |
| Mês | Mês de calendário |
| Ano | Ano de calendário |

Datas seguem o fuso horário da conta de anúncios, que é como a Meta entrega os dados (R-17).

### 3.3 Regras de exibição especiais

| Combinação | Tratamento |
|---|---|
| Alcance e frequência em semana ISO, mês ou ano | Valor extraído da API para aquele período e entidade (ADR-0006) |
| Alcance e frequência em período livre | "Não disponível", com explicação, salvo quando o intervalo coincide exatamente com uma semana ISO, um mês ou um ano |
| Alcance e frequência na visão Geral com mais de uma conta | "Não disponível": a Meta não deduplica pessoas entre contas |
| Alcance e frequência em quebras agregadas por mais de um dia | Não exibidos |
| Quebra por região | Não inclui conversões que acontecem fora da Meta, como compras no site (R-23). O painel avisa quando o resultado principal da campanha é desse tipo |

---

## 4. Restrições e volume

### 4.1 Restrições de plataforma verificadas

Todas foram consultadas em 29/10/2026 nas fontes da §9. Restrições que dependem de confirmação estão marcadas.

| ID | Restrição | Fonte |
|---|---|---|
| R-01 | Supabase em plano pago: o projeto não é pausado por inatividade e tem backup diário automático, com retenção de 7 dias no Pro e 14 no Team. O PITR é um add-on | [S1], [S2] |
| R-02 | Supabase: a conexão direta usa IPv6, e IPv4 nela exige o add-on de IPv4. O pooler compartilhado aceita IPv4 em modo sessão (5432) e transação (6543). No modo transação não há advisory lock de sessão nem prepared statements | [S3] |
| R-03 | Supabase Edge Functions em planos pagos: 400 s de relógio, 2 s de CPU e 256 MB por execução | [S4] |
| R-04 | Vercel Hobby: "restrito a uso pessoal e não comercial". Conta como uso comercial qualquer ganho financeiro de quem participa do projeto | [VC1], [VC2] |
| R-05 | Vercel: Password Protection só no Pro, a US$ 20/mês por projeto. O assento Pro custa US$ 20/mês | [VC3], [VC4] |
| R-06 | Vercel Hobby: cron no máximo uma vez por dia, com precisão de ±59 min; funções com até 300 s | [VC5], [VC6] |
| R-07 | GitHub Actions: executores padrão são gratuitos em repositório público; um job dura no máximo 6 h | [G1], [G2] |
| R-08 | GitHub Actions `schedule`: pode atrasar em carga alta, sobretudo no início de cada hora, e jobs podem ser descartados. Em repositório público, é desativado após 60 dias sem atividade. As notificações vão para quem alterou o cron por último | [G3] |
| R-09 | GitHub: em repositório público, logs e artefatos de workflow ficam visíveis para qualquer conta logada. A retenção padrão é de 90 dias | [G4], [G5], [G6] |
| R-10 | GitHub: secrets não são passados a workflows disparados por forks. `pull_request_target` é arriscado. A redação automática de segredos nos logs não é garantida | [G7], [G8] |
| R-11 | GitHub: a varredura de segredos roda gratuitamente em repositórios públicos. A push protection no nível do usuário vem ativada por padrão | [G9], [G10] |
| R-12 | Meta: a versão mais recente da Graph/Marketing API é a v26.0, de 29/07/2026 | [M1] |
| R-13 | Meta Marketing API Access Tier: Limited é "fortemente limitado por conta" e "só para desenvolvimento"; Full é "levemente limitado". Permite 1 System User + 1 admin no Limited e 10 + 1 no Full. A promoção exige 500 chamadas em 15 dias com menos de 15% de erro | [M2] |
| R-14 | Meta: gerenciar contas de anúncio "de outras pessoas" exige acesso avançado a `ads_read`/`ads_management`, e o acesso avançado exige verificação da empresa. *A confirmar*: se contas compartilhadas com a BM do operador contam como "de outras pessoas" | [M2], [M3] |
| R-15 | Meta, limites de taxa por conta e por hora. Insights: 600 (dev) ou 190.000 (Full) + 400 × anúncios ativos − 0,001 × erros. Pontuação: leitura vale 1 ponto, com teto de 60 (dev) ou 9.000 (Full), decaimento de 300 s e bloqueio de 300 s (dev) ou 60 s (Full) | [M4] |
| R-16 | Meta: o token de System User pode não ter validade ou valer 60 dias (renovável; a Meta recomenda o de 60 dias) | [M5] |
| R-17 | Meta Insights: dados no fuso horário da conta; atualizados a cada 15 min; "não mudam após 28 dias" | [M6] |
| R-18 | Meta Insights: desde 10/06/2025, consultas padrão com quebras e data inicial a mais de 13 meses não retornam alcance. Jobs assíncronos podem levar até 1 h, e o `report_run_id` expira em 30 dias | [M6] |
| R-19 | Meta Insights: no máximo 37 meses de dados (`date_preset=maximum`) | [M7] |
| R-20 | Meta Insights: `time_increment` aceita 1 a 90 dias, `monthly` (mês de calendário) ou `all_days`. *A confirmar*: como os períodos de N dias se alinham e se o alcance vem deduplicado por período | [M7] |
| R-21 | Meta Insights: `actions`, `action_values` e `cost_per_action_type` são listas de `AdsActionStats` (`action_type`, `value`). Tipos documentados: `onsite_conversion.messaging_conversation_started_7d`, `lead`, `onsite_conversion.lead_grouped`, `offsite_conversion.fb_pixel_purchase`, `omni_purchase`, `link_click`, `landing_page_view` | [M7], [M8] |
| R-22 | Meta Insights: a janela `default` equivale a `7d_click` + `1d_view`. Com `use_unified_attribution_setting=true`, vale a configuração do conjunto de anúncios. *A confirmar*: a referência ainda lista `7d_view` e `28d_view`, que fontes não oficiais dizem ter sido removidas em janeiro de 2026 | [M7] |
| R-23 | Meta Insights, combinações de quebra disponíveis: `age`, `gender`, `age`+`gender`, `region`, `publisher_platform`+`platform_position`, entre outras. `region` é do "Tipo 1" e não retorna métricas de ações fora da Meta | [M9] |
| R-24 | Meta Insights: `cost_per_result` é documentado como `list<AdsInsightsResult>`. *A confirmar*: o campo `results` e o formato de `AdsInsightsResult` | [M7] |
| R-25 | Meta: a prévia de anúncio é um iframe válido por 24 h, e as prévias de uma conta só são visíveis para quem tem função nela | [M10], [M11] |
| R-26 | Meta: o `thumbnail_url` do AdCreative aceita `thumbnail_width`/`thumbnail_height` (padrão de 64 px). *A confirmar*: se a URL expira | [M12] |
| R-27 | Meta: o post da Página tem `permalink_url` e a mídia do Instagram tem `permalink`. *A confirmar*: as permissões necessárias (`pages_read_engagement`, `instagram_basic`) para o System User | [M13], [M14] |

### 4.2 Estimativa de volume

Estimativa de projeto, a validar com o volume real da primeira empresa (Q-09). Empresa de referência: 2 contas, 6 campanhas ativas e 20 anúncios ativos por dia em média.

| Tabela (grão) | Linhas por ano | Tamanho por ano (com índices) |
|---|---|---|
| Métricas diárias (anúncio × dia) | ~7,3 mil | ~1,5 MB |
| Ações (anúncio × dia × tipo de ação) | ~180 mil | ~25–30 MB |
| Quebras (campanha × dia × categoria, ~60 categorias) | ~130 mil | ~25–30 MB |
| Alcance por período (entidade × semana/mês/ano) | ~3 mil | < 1 MB |
| Camada `bruto` (35 dias, comprimida) | contínuo | ~10 MB fixos |
| **Total** | | **~50–90 MB/ano** |

Com 37 meses de histórico, a empresa de referência ocupa cerca de 150 a 280 MB.

---

## 5. Requisitos funcionais

### 5.1 Extração

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RF-01 | O sistema deve extrair, para cada conta ativa de cada empresa ativa, o cadastro de campanhas, conjuntos de anúncios, anúncios e criativos. Isso inclui nome, status, objetivo, meta de otimização, título, texto, chamada para ação, miniatura e identificadores do post. | Must | Após a carga diária, todo anúncio com entrega nos últimos 28 dias existe em `normalizado` com campanha, conjunto e criativo válidos. A consulta de órfãos retorna 0 linhas. | Objetivo central |
| RF-02 | O sistema deve extrair insights diários (`time_increment=1`) no nível de anúncio: investimento, impressões, alcance diário, cliques no link, `actions` e `action_values`. | Must | Para um dia já fechado, a soma do investimento por conta no banco difere em no máximo R$ 0,01 do valor retornado pela API no nível de conta para o mesmo dia. | Objetivo central |
| RF-03 | O sistema deve extrair quebras por campanha e dia nas combinações idade+gênero, plataforma+posicionamento e região, com as métricas-base e as ações do resultado principal. | Must | Para uma campanha e um dia, a soma do investimento entre as categorias de cada quebra difere em no máximo 1% do investimento da campanha no dia. | Decisão de produto |
| RF-04 | O sistema deve extrair alcance e impressões já agregados pela API por conta, campanha e anúncio, para cada semana ISO, mês e ano com dados. | Must | O alcance de uma campanha em março de 2026 no banco é igual ao retornado pela API para o intervalo 01/03–31/03/2026 sem quebra diária. | ADR-0006 |
| RF-05 | O sistema deve reprocessar os últimos 28 dias a cada execução diária. | Must | Se a Meta revisar as conversões de um dia dentro da janela, após a execução diária seguinte o valor no banco é igual ao retornado pela API. | Restrição da API (R-17) |
| RF-06 | O sistema deve executar uma carga a cada hora com os dados de hoje e de ontem. | Must | Após uma execução horária, os dados de hoje e de ontem de cada empresa ativa no banco são iguais aos retornados pela API no momento da extração. | Decisão de produto |
| RF-07 | O sistema deve importar até 37 meses de histórico ao cadastrar uma conta, fatiando a carga por mês e permitindo retomá-la. | Must | Uma carga histórica interrompida, ao ser executada de novo, continua da última fatia concluída. O estado final é igual ao de uma execução sem interrupção. | Decisão de produto; R-19 |
| RF-08 | O sistema deve respeitar os limites de taxa da Meta: ler os cabeçalhos de uso, esperar e tentar de novo com backoff exponencial, e usar jobs assíncronos quando a consulta síncrona falhar por volume ou tempo. | Must | Em teste com resposta simulada de limite (códigos 4, 17, 613 ou 80000–80014), a ETL espera e tenta de novo até `MAXIMO_TENTATIVAS`. Ao esgotar as tentativas, registra a falha da empresa e segue para a próxima. | R-15; R-18 |
| RF-09 | O sistema deve gravar cada resposta da API na camada `bruto` antes de transformá-la. | Must | Toda linha carregada em `normalizado` numa execução tem resposta bruta da mesma execução, rastreável pelo `execucao_id`. | ADR-0005 |
| RF-10 | O sistema deve usar uma única constante para a versão da API da Meta. | Should | Uma busca no código encontra a versão (ex.: `v26.0`) em exatamente um lugar. | R-12 |

### 5.2 Tratamento

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RF-11 | O sistema deve traduzir os nomes de campo da API para nomes em português a partir da camada `normalizado`, usando um mapa único e versionado. | Must | Teste: cada campo da API usado na transformação tem entrada no mapa; nenhuma coluna de `normalizado` tem nome de campo da API. | Decisão de produto |
| RF-12 | O sistema deve converter `actions` e `action_values` numa tabela longa: grão + tipo de ação + quantidade + valor. | Must | Uma resposta com 12 itens em `actions` gera 12 linhas. A soma por tipo de ação no banco é igual à da resposta bruta. | CLAUDE.md §5 |
| RF-13 | O sistema deve padronizar os tipos. Dinheiro vai para `numeric` via decimal, nunca float. Datas ficam no fuso da conta. Textos são aparados, com vazio → `NULL`. Ausência de dado é `NULL`, nunca zero. | Must | Teste unitário: `"spend": "12.34"` vira exatamente 12.34; campo ausente vira `NULL`; `"  Nome "` vira `"Nome"`. | CLAUDE.md §5 |
| RF-14 | O sistema deve definir o resultado principal de cada campanha pelo catálogo, a partir do objetivo e da meta de otimização, respeitando a sobrescrita por campanha. | Must | Uma campanha `OUTCOME_ENGAGEMENT` otimizada para conversas exibe "Conversas iniciadas". Depois de registrar uma sobrescrita para ela na área do operador, o resultado definido aparece sem nenhum commit. | Decisão de produto; ADR-0007 |
| RF-15 | O sistema deve tratar objetivos legados pelo catálogo e marcar como "não classificado" qualquer objetivo desconhecido. | Must | Uma campanha com objetivo legado mapeado exibe resultado principal. Uma campanha com objetivo fora do catálogo exibe "Não classificado" e gera um aviso na execução, sem falhar a carga. | Conhecimento de domínio |
| RF-16 | O sistema deve comparar o resultado principal calculado pelo catálogo com o campo de resultados da API, quando disponível, e registrar divergências. | Could | Uma divergência acima de 1% numa campanha gera um aviso na execução, com a campanha identificada pelo ID interno. | R-24 (*a confirmar*) |

### 5.3 Carga

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RF-17 | O sistema deve carregar por upsert pela chave natural e, na janela reprocessada, substituir o conjunto completo de linhas do intervalo. | Must | Duas execuções seguidas com a mesma resposta da API produzem estado idêntico (contagem e soma de verificação das tabelas). Um tipo de ação que some na revisão da Meta deixa de existir no banco. | CLAUDE.md §6 |
| RF-18 | O sistema deve carregar cada empresa (ou cada fatia histórica) numa única transação, isolando a falha de uma empresa das demais. | Must | Com falha injetada após metade das linhas da empresa A, nenhuma linha nova de A persiste, e a empresa B é carregada normalmente. | CLAUDE.md §6 |
| RF-19 | O sistema deve impedir execuções concorrentes da mesma empresa. | Must | Duas execuções simultâneas para a mesma empresa: a segunda espera até 15 min pelo lock e, sem obtê-lo, termina com status `ignorada`, sem escrever dados. | CLAUDE.md §6 |
| RF-20 | O sistema deve registrar cada execução por empresa: tipo, início, fim, status, linhas afetadas por tabela e erro. | Must | Toda execução tem registro. Toda falha tem mensagem de erro não vazia, e o registro existe mesmo quando a carga sofreu rollback. | CLAUDE.md §6 |
| RF-21 | O sistema deve apagar da camada `bruto` as respostas com data de referência anterior a 35 dias. | Must | Após a execução diária, não há linha em `bruto` com data de referência anterior a hoje − 35 dias. | ADR-0005 |
| RF-22 | O sistema deve iniciar a carga histórica de uma conta recém-cadastrada sem intervenção no código. | Must | Ao cadastrar a conta pela área do operador, a próxima execução diária inicia a carga histórica dela. | Objetivo central |

### 5.4 Painel: navegação e períodos

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RF-23 | O painel deve permitir descer de Geral para conta, campanha e anúncio mantendo o período e a granularidade selecionados. | Must | Com "mês atual" selecionado, ao abrir uma campanha, a lista de anúncios aparece filtrada por ela e pelo mesmo mês. | Objetivo central |
| RF-24 | O painel deve refletir na URL o nível, o período e a granularidade (sem o token de acesso), para que voltar e recarregar preservem o estado. | Should | Ao recarregar a página de uma campanha com "últimos 7 dias", a mesma visão reaparece. A URL não contém o token. | Objetivo central; ADR-0004 |
| RF-25 | O painel deve permitir escolher a granularidade de tempo (dia, semana ISO, mês, ano) para séries e tabelas. | Must | Com "Este ano" e granularidade "Mês", a série mostra um ponto por mês, e a soma do investimento dos meses é igual ao total do ano. | Objetivo central |
| RF-26 | O painel deve oferecer atalhos de período (hoje, ontem, últimos 7 e 30 dias, este mês, mês passado, este ano) e intervalo livre. | Must | Cada atalho seleciona o intervalo correto no fuso da conta, verificado por teste com data fixa. | Objetivo central |
| RF-27 | O painel deve mostrar, ao lado de cada métrica, a variação percentual em relação ao período anterior equivalente. | Must | Com "mês passado" (setembro), a variação é calculada contra agosto. Com um intervalo livre de 10 dias, contra os 10 dias imediatamente anteriores. Sem dado no período anterior, mostra "—". | Decisão de produto |
| RF-28 | O painel deve marcar os dados de hoje como parciais, exibir o horário da última carga bem-sucedida e sinalizar atraso. | Must | Se a última carga bem-sucedida da empresa tiver mais de 3 h, o painel exibe o aviso "dados desatualizados". | Decisão de produto |
| RF-29 | O painel deve ter layout utilizável no celular, com tabelas virando cartões e toque no lugar do cursor. | Must | Em 360 px de largura, nenhuma página tem rolagem horizontal, e todas as ações disponíveis no desktop estão acessíveis. | Decisão de produto |

### 5.5 Painel: métricas e leitura

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RF-30 | O painel deve exibir rótulo de negócio e explicação curta de cada métrica, lidos do catálogo de métricas. | Must | Um teste compara as métricas exibidas com o catálogo e falha se alguma não tiver rótulo e explicação. Mudar uma explicação no catálogo muda a tela sem alterar componentes. | Objetivo central; ADR-0007 |
| RF-31 | O painel deve destacar o resultado principal e o KPI de cada campanha conforme o catálogo. | Must | Uma campanha de vendas mostra "Compras" e "Custo por compra" em destaque; uma de mensagens, "Conversas iniciadas" e "Custo por conversa". | Objetivo central |
| RF-32 | O painel deve garantir que, nas métricas aditivas, o total de um nível seja igual à soma do nível abaixo. | Must | Teste de banco: para qualquer empresa e período, a soma do investimento das campanhas é igual ao investimento da conta, e a soma dos anúncios é igual à da campanha. | Objetivo central |
| RF-33 | O painel nunca deve somar métricas não aditivas: alcance e frequência seguem a §3.3, e as razões são recalculadas a partir das somas. | Must | O CTR do mês é igual à soma dos cliques no link dividida pela soma das impressões do mês, num caso de teste em que esse valor difere da média dos CTRs diários. | Conhecimento de domínio; ADR-0006 |
| RF-34 | O painel deve exibir totais separados por moeda quando a empresa tiver contas em moedas diferentes. | Must | Uma empresa fictícia com uma conta em BRL e outra em USD mostra dois totais de investimento na visão Geral e nenhum total combinado. | Decisão de produto |
| RF-35 | O painel deve formatar valores, números, percentuais e datas no padrão brasileiro. | Must | Teste unitário: 1234.56 em BRL vira "R$ 1.234,56"; 0.125 vira "12,5%"; 2026-10-29 vira "29/10/2026". | Objetivo central |
| RF-36 | O painel deve mostrar quebras por idade e gênero, por plataforma e posicionamento, e por região nos níveis Geral, conta e campanha. | Must | Para uma campanha e um mês, cada quebra exibe as categorias com investimento e resultado principal, e a soma do investimento das categorias difere em no máximo 1% do total da campanha. | Decisão de produto |
| RF-37 | O painel deve exibir objetivo e status da campanha em linguagem de negócio (ex.: "Vendas", "Ativa"). | Should | Nenhum valor de enum da API (ex.: `OUTCOME_SALES`, `ACTIVE`) aparece na interface. | Objetivo central |

### 5.6 Painel: anúncios

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RF-38 | O sistema deve copiar a miniatura de cada anúncio para o Storage do Supabase e o painel deve exibi-la a partir dessa cópia. | Must | Com a extração parada por 7 dias, as miniaturas continuam carregando no painel. | Decisão de produto; R-26 |
| RF-39 | O painel deve oferecer, em cada anúncio, um link "ver publicação" que abre o post no Facebook ou no Instagram. | Must | Para um anúncio cujo post é público, o link abre a publicação. Sem permalink disponível, o link fica oculto e há uma explicação curta. | Decisão de produto; R-27 |
| RF-40 | O painel deve mostrar, ao passar o cursor sobre o anúncio no desktop, um cartão de prévia no formato do feed com nome da página, texto, imagem, título e chamada para ação. No celular, a prévia abre com um toque. | Must | A prévia aparece em até 300 ms após o cursor parar sobre o anúncio, sem chamar a API da Meta, só com dados do banco e do Storage. | Decisão de produto; R-25 |

### 5.7 Metas

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RF-41 | O operador deve poder cadastrar, editar e encerrar metas. Cada meta tem escopo (empresa por mês ou campanha), métrica do catálogo, valor-alvo, sentido (no máximo ou no mínimo) e vigência. | Must | Uma meta "custo por conversa ≤ R$ 15,00" para uma campanha fictícia é cadastrada na área do operador e aparece no painel da empresa sem deploy. | Decisão de produto |
| RF-42 | O painel deve exibir, junto da métrica, a meta vigente e o status (atingida, não atingida, em andamento). | Must | Com custo por conversa de R$ 12,00 e meta de no máximo R$ 15,00 num mês encerrado, o status é "atingida". No mês corrente, é "em andamento". | Decisão de produto |

### 5.8 Empresas e acesso

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RF-43 | O operador deve poder cadastrar uma empresa e suas contas de anúncio informando só o nome da empresa e os IDs das contas. Fuso e moeda são lidos da API. | Must | Após cadastrar a "Empresa Exemplo 2" pela área do operador, os dados dela aparecem no painel depois da execução seguinte. | Objetivo central; ADR-0002 |
| RF-44 | O operador deve poder gerar um link secreto por empresa. | Must | O link gerado é exibido uma única vez e abre o painel da empresa. | ADR-0004 |
| RF-45 | O operador deve poder revogar um link. | Must | Na requisição seguinte à revogação, o link revogado recebe 404. | ADR-0004 |
| RF-46 | O link de uma empresa deve mostrar exclusivamente os dados dela. | Must | Com o link da empresa A, nenhuma rota ou parâmetro devolve dados da empresa B; a tentativa retorna 404. | ADR-0002; ADR-0004 |
| RF-47 | O operador deve acessar, com uma credencial própria, a visão de todas as empresas e a área do operador. | Must | Sem a credencial do operador, as rotas da área do operador retornam 404. Com ela, todas as empresas ativas aparecem listadas. | ADR-0004 |
| RF-48 | O operador deve poder desativar uma empresa, interrompendo a extração e o acesso pelo link e preservando os dados. | Should | Depois de desativada, a empresa não aparece nas execuções seguintes, e o link dela retorna 404. | Objetivo central |
| RF-49 | O operador deve poder sobrescrever o resultado principal de uma campanha na área do operador. | Must | Mesmo critério de RF-14. | Decisão de produto |

### 5.9 Operação e monitoramento

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RF-50 | O sistema deve notificar o operador quando uma execução falhar para qualquer empresa. | Must | Uma falha simulada de uma empresa faz o workflow terminar com código diferente de zero, o que dispara a notificação do GitHub. A falha aparece na área do operador. | Decisão de produto |
| RF-51 | A área do operador deve listar as execuções recentes por empresa, com status, duração, linhas afetadas e erro. | Should | As últimas 48 h de execuções aparecem com filtro por empresa e status. | Decisão de produto |
| RF-52 | O sistema deve registrar diariamente o uso de banco, Storage e egress e alertar o operador ao ultrapassar 70% das cotas incluídas no plano. | Must | Com o uso acima de 70% de uma cota (constantes `COTA_*` de configuração), a execução diária registra um aviso, e a área do operador o destaca. | RNF-23 |
| RF-53 | O repositório deve conter um runbook para cadastrar e desativar empresa, gerar e revogar link, rotacionar o token da Meta, restaurar o banco a partir do backup e reconstruí-lo por reextração. | Should | Uma pessoa que não participou do desenvolvimento cadastra uma empresa fictícia seguindo só o runbook. | RNF-22 |

---

## 6. Requisitos não funcionais

### 6.1 Usabilidade

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RNF-01 | As explicações de métrica são curtas. | Must | 100% das explicações do catálogo têm no máximo 200 caracteres. | Objetivo central |
| RNF-02 | Nenhum nome de campo da API aparece na interface. | Must | Um teste percorre os textos renderizados e encontra 0 ocorrências da lista de campos da API (`spend`, `impressions`, `cpc`, `ctr`, `reach`, `actions` e outros). | Objetivo central |
| RNF-03 | O painel é acessível e utilizável no celular. | Must | Lighthouse (modo mobile) com Acessibilidade ≥ 90 nas páginas Geral, campanha e anúncio. | Decisão de produto |
| RNF-04 | Uma pessoa sem experiência em Meta Ads responde às perguntas de negócio usando só o painel. | Should | Num teste com pelo menos 1 pessoa de negócio, cada uma das 3 perguntas ("Quanto investimos no mês passado?", "Qual campanha teve o menor custo por conversa?", "Qual anúncio gerou mais cadastros?") é respondida corretamente em até 2 min. | Objetivo central |

### 6.2 Desempenho

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RNF-05 | As páginas do painel carregam rápido no celular. | Must | Lighthouse (modo mobile) com LCP ≤ 3 s nas páginas Geral e campanha, para a empresa de referência com 37 meses de dados. | Objetivo central |
| RNF-06 | As consultas do painel respondem rápido. | Must | Cada função de `analitico` executa em ≤ 500 ms (p95 de 20 execuções) com os dados da empresa de referência. | Objetivo central |
| RNF-07 | As execuções da ETL cabem nos limites do GitHub Actions. | Must | A execução horária leva ≤ 10 min no total, e a diária leva ≤ 60 min por empresa. Cada execução histórica leva ≤ 5 h, abaixo do limite de 6 h por job. | R-07 |
| RNF-08 | Os dados ficam atualizados. | Must | Em 95% das horas do mês, a defasagem entre o horário atual e a última carga bem-sucedida de cada empresa ativa é ≤ 2 h, medida pela tabela de controle. | Decisão de produto; R-08 |

### 6.3 Confiabilidade e integridade

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RNF-09 | O painel nunca exibe carga parcial. | Must | Uma consulta concorrente durante uma carga com falha injetada retorna 0 linhas da execução que falhou. | CLAUDE.md §6 |
| RNF-10 | Os números batem com a Meta. | Must | Para dias fechados há mais de 28 dias, o investimento por conta e por dia difere em no máximo R$ 0,01 da API, conferido por amostragem mensal de 10 dias. | Objetivo central |
| RNF-11 | As execuções são confiáveis. | Should | ≥ 95% das execuções do mês terminam com sucesso, sem contar as indisponibilidades da Meta registradas como tal. | Decisão de produto |
| RNF-12 | O banco é recuperável. | Must | Em caso de perda, o banco é restaurado em ≤ 24 h a partir do backup diário automático. A perda máxima é de 24 h para os dados operacionais e de 0 dias para as métricas dentro de 37 meses, recuperáveis por reextração. | R-01; ADR-0005 |
| RNF-13 | Uma carga parada é detectada. | Must | Se uma empresa ativa passar 24 h sem execução bem-sucedida, a área do operador a destaca como parada, mesmo que o workflow agendado não tenha sido executado. | R-08 |

### 6.4 Segurança e isolamento entre empresas

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RNF-14 | Um acesso só enxerga dados da empresa da credencial usada. | Must | Em teste pgTAP, cada função de `analitico` chamada com a credencial da empresa A retorna 0 linhas da empresa B. | ADR-0002 |
| RNF-15 | Credenciais de acesso ao painel são fortes e não ficam em texto puro. | Must | Tokens com ≥ 128 bits de entropia; o banco guarda só o hash SHA-256 (0 tokens em texto puro, verificado por teste); a comparação no servidor é feita em tempo constante. | ADR-0004 |
| RNF-16 | Nenhum segredo fica no repositório nem no navegador. | Must | Varredura de segredos com 0 achados em todo PR. Uma busca no build do cliente encontra 0 ocorrências de token da Meta, chave `service_role` ou string de conexão. | CLAUDE.md §12 |
| RNF-17 | Logs públicos não expõem dados de empresas. | Must | O logger aceita só campos de uma lista permitida. Um teste falha se algum log contiver nome de empresa, ID da Meta, nome de campanha ou anúncio, valor monetário ou token. | ADR-0008 |
| RNF-18 | O link secreto não vaza por cabeçalho nem por indexação. | Must | 100% das respostas do painel (páginas, rotas de API e redirecionamentos) têm `Referrer-Policy: no-referrer` e `X-Robots-Tag: noindex, nofollow`, verificado por teste de integração. | ADR-0004 |

### 6.5 Manutenibilidade

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RNF-19 | A lógica de transformação é testada. | Must | Cobertura de linhas ≥ 80% nos módulos de transformação da ETL e nas funções de formatação do painel. | CLAUDE.md §9 |
| RNF-20 | O código segue lint e formatação. | Must | A CI registra 0 erros de lint e de formatação em todo PR. | CLAUDE.md §9 |
| RNF-21 | Funções são pequenas e simples. | Should | Nenhuma função com complexidade ciclomática > 10, verificado pelo linter na CI. | CLAUDE.md §8 |
| RNF-22 | Cadastrar uma empresa nova não exige mudar código. | Must | Seguindo o runbook, o cadastro altera 0 arquivos do repositório e leva ≤ 30 min de trabalho do operador, sem contar a carga histórica. | Objetivo central |

### 6.6 Custo

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RNF-23 | O custo de infraestrutura é previsível. | Must | Vercel (Hobby) e GitHub Actions (repositório público) sem custo, e nenhuma cobrança de excedente no Supabase sem o alerta prévio do RF-52. | Decisão de produto |

### 6.7 Conformidade com a LGPD

| ID | Descrição | Prioridade | Critério de aceite | Origem |
|---|---|---|---|---|
| RNF-24 | O sistema não armazena dados pessoais. | Must | Na revisão do schema, 0 colunas com nome, e-mail, telefone ou identificador de pessoa física. A ETL não chama endpoints de leads, o que é verificado por teste da lista de endpoints usados. Quebras de idade, gênero e região são agregados da Meta. | LGPD |
| RNF-25 | Os dados de uma empresa podem ser excluídos a pedido. | Should | Uma função de exclusão em cascata remove todas as linhas da empresa. Um teste confirma 0 linhas remanescentes com o `empresa_id` dela. | LGPD |

---

## 7. Catálogo de métricas por objetivo

Conteúdo inicial do catálogo, carregado por migration (ADR-0007). Os itens *a confirmar* dependem da Q-10.

### 7.1 Métricas

| Código | Rótulo no painel | Explicação curta | Fórmula | Origem na API | Aditiva |
|---|---|---|---|---|---|
| `investimento` | Investimento | Quanto foi gasto em anúncios no período. | soma do investimento | `spend` | Sim |
| `impressoes` | Impressões | Quantas vezes os anúncios apareceram na tela das pessoas. | soma das impressões | `impressions` | Sim |
| `alcance` | Pessoas alcançadas | Quantas pessoas diferentes viram os anúncios pelo menos uma vez. Não pode ser somado entre dias. | valor extraído por período | `reach` | Não |
| `frequencia` | Frequência | Em média, quantas vezes cada pessoa alcançada viu os anúncios. | impressões ÷ alcance, do mesmo período | `impressions`, `reach` | Não |
| `cliques_link` | Cliques no link | Cliques que levaram a pessoa para fora do anúncio: site, WhatsApp, formulário ou loja. | soma | `actions` → `link_click` | Sim |
| `ctr` | Taxa de cliques | De cada 100 vezes que o anúncio apareceu, quantas viraram clique no link. | cliques no link ÷ impressões × 100 | derivada | Não |
| `cpc` | Custo por clique | Quanto custou, em média, cada clique no link. | investimento ÷ cliques no link | derivada | Não |
| `cpm` | Custo por mil impressões | Quanto custou fazer os anúncios aparecerem mil vezes. | investimento ÷ impressões × 1000 | derivada | Não |
| `custo_mil_alcance` | Custo por mil pessoas alcançadas | Quanto custou alcançar mil pessoas diferentes no período. | investimento ÷ alcance × 1000, do mesmo período | derivada | Não |
| `visualizacoes_pagina_destino` | Visitas ao site | Quantas vezes alguém clicou e o site carregou de fato. | soma | `actions` → `landing_page_view` | Sim |
| `custo_visualizacao_pagina` | Custo por visita ao site | Quanto custou, em média, cada visita ao site. | investimento ÷ visualizações da página de destino | derivada | Não |
| `conversas_iniciadas` | Conversas iniciadas | Quantas conversas começaram no WhatsApp, Messenger ou Direct a partir do anúncio. | soma | `actions` → `onsite_conversion.messaging_conversation_started_7d` | Sim |
| `custo_conversa` | Custo por conversa | Quanto custou, em média, cada conversa iniciada. | investimento ÷ conversas iniciadas | derivada | Não |
| `cadastros` | Cadastros | Quantas pessoas deixaram seus dados num formulário do anúncio ou no site. | soma | `actions` → `lead` | Sim |
| `custo_cadastro` | Custo por cadastro | Quanto custou, em média, cada cadastro. | investimento ÷ cadastros | derivada | Não |
| `compras` | Compras | Quantas compras foram registradas e atribuídas aos anúncios. | soma | `actions` → `omni_purchase` | Sim |
| `valor_compras` | Valor das compras | Soma do valor das compras atribuídas aos anúncios. | soma | `action_values` → `omni_purchase` | Sim |
| `custo_compra` | Custo por compra | Quanto custou, em média, cada compra. | investimento ÷ compras | derivada | Não |
| `roas` | Retorno sobre o investimento | Quantos reais em vendas voltaram para cada real investido. | valor das compras ÷ investimento | derivada | Não |
| `interacoes_publicacao` | Interações com a publicação | Curtidas, comentários, compartilhamentos e cliques na publicação. | soma | `actions` → `post_engagement` (*a confirmar*) | Sim |
| `custo_interacao` | Custo por interação | Quanto custou, em média, cada interação. | investimento ÷ interações | derivada | Não |

Regras de agregação:
- Métricas aditivas somam entre dias e entre entidades.
- Razões são sempre recalculadas a partir das somas do recorte exibido.
- Alcance e frequência seguem a §3.3.
- Derivadas com denominador zero ou `NULL` são exibidas como "—", nunca como 0 ou infinito.

### 7.2 Resultado principal por objetivo

O resultado principal de cada campanha é resolvido pela precedência do ADR-0007.

| Objetivo na API | Legados equivalentes (*a confirmar*) | Nome no painel | Meta de otimização do conjunto (*a confirmar*) | Resultado principal | KPI principal | Métricas de apoio |
|---|---|---|---|---|---|---|
| `OUTCOME_AWARENESS` | `BRAND_AWARENESS`, `REACH` | Reconhecimento | qualquer | `alcance` | `custo_mil_alcance` | `frequencia`, `impressoes`, `cpm` |
| `OUTCOME_TRAFFIC` | `LINK_CLICKS` | Tráfego | `LANDING_PAGE_VIEWS` | `visualizacoes_pagina_destino` | `custo_visualizacao_pagina` | `cliques_link`, `ctr`, `cpc` |
| `OUTCOME_TRAFFIC` | `LINK_CLICKS` | Tráfego | qualquer outra | `cliques_link` | `cpc` | `ctr`, `cpm`, `visualizacoes_pagina_destino` |
| `OUTCOME_ENGAGEMENT` | `MESSAGES` | Conversas | `CONVERSATIONS` | `conversas_iniciadas` | `custo_conversa` | `cliques_link`, `ctr`, `cpm` |
| `OUTCOME_ENGAGEMENT` | `POST_ENGAGEMENT` | Engajamento | qualquer outra | `interacoes_publicacao` | `custo_interacao` | `alcance`, `ctr`, `cpm` |
| `OUTCOME_LEADS` | `LEAD_GENERATION` | Cadastros | qualquer, exceto `CONVERSATIONS` | `cadastros` | `custo_cadastro` | `cliques_link`, `ctr`, `cpm` |
| `OUTCOME_LEADS` | — | Cadastros por conversa | `CONVERSATIONS` | `conversas_iniciadas` | `custo_conversa` | `cadastros`, `ctr` |
| `OUTCOME_SALES` | `CONVERSIONS` | Vendas | qualquer, exceto `CONVERSATIONS` | `compras` | `custo_compra` | `valor_compras`, `roas`, `cliques_link` |
| `OUTCOME_SALES` | — | Vendas por conversa | `CONVERSATIONS` | `conversas_iniciadas` | `custo_conversa` | `compras`, `valor_compras` |
| `OUTCOME_APP_PROMOTION` | `APP_INSTALLS` | Promoção de app | qualquer | *a confirmar* | — | `investimento`, `cliques_link` |
| fora do catálogo | — | Não classificado | — | nenhum; exibe só as métricas-base | — | `investimento`, `impressoes`, `cliques_link` |

---

## 8. Questões em aberto

| ID | Questão | Impacto de deixar em aberto |
|---|---|---|
| Q-01 | O uso do Vercel Hobby continua permitido? Os termos (R-04) proíbem uso comercial, incluindo ganho de quem desenvolve ou opera o projeto. | Suspensão do painel. A migração para o Pro (US$ 20/mês) passa a ser obrigatória (ADR-0001). |
| Q-02 | O app em nível Limited, sem publicação, consegue ler em produção as contas compartilhadas com a BM do operador? A Meta descreve o Limited como "só para desenvolvimento" e exige acesso avançado para contas "de outras pessoas" (R-13, R-14). | Extração bloqueada ou limitada a 60 pontos por conta. O histórico de 37 meses pode levar dias. |
| Q-03 | Com `time_increment` de N dias, os períodos começam no `since`? O alcance vem deduplicado por período (R-20)? | Alcance semanal errado. Enquanto não houver resposta, cada semana é extraída com `time_range` próprio (ADR-0006). |
| Q-04 | Quais janelas de atribuição estão de fato disponíveis (R-22)? | Números diferentes do Gerenciador de Anúncios. |
| Q-05 | Qual é o formato de `results`/`AdsInsightsResult` e ele reproduz a coluna "Resultados" do Gerenciador (R-24)? | RF-16 fica sem implementação; o catálogo continua sendo a fonte do resultado principal. |
| Q-06 | O System User com `ads_read` lê o `permalink_url` do post e o `permalink` da mídia do Instagram, ou são necessárias permissões de Página e de Instagram (R-27)? | O link "ver publicação" (RF-39) fica indisponível. |
| Q-07 | O `thumbnail_url` expira (R-26)? | Nenhum: RF-38 copia a imagem de qualquer forma. Só muda a urgência da cópia. |
| Q-08 | Quando os conjuntos de uma campanha têm metas de otimização diferentes, o critério do maior investimento (ADR-0007) atende ao negócio? | Resultado principal pouco representativo nessas campanhas. A sobrescrita por campanha resolve caso a caso. |
| Q-09 | O volume real por empresa confirma a estimativa da §4.2? | Custo de armazenamento acima do previsto e consultas mais lentas. |
| Q-10 | Quais são os valores exatos dos enums de objetivos legados e de metas de otimização (§7.2)? | Campanhas mal classificadas. |
| Q-11 | O GitHub avisa antes de desativar o workflow agendado por 60 dias sem atividade (R-08)? | Carga parada sem aviso, visível só pelo RF-28 e pelo RNF-13. |

---

## 9. Referências consultadas

Todas consultadas em 29/10/2026.

**Meta**
- [M1] Marketing API changelog: https://developers.facebook.com/docs/marketing-api/marketing-api-changelog
- [M2] Marketing API access: https://developers.facebook.com/docs/marketing-api/access
- [M3] Permissão `ads_read`: https://developers.facebook.com/docs/permissions/reference/ads_read
- [M4] Rate limiting: https://developers.facebook.com/docs/marketing-api/overview/rate-limiting
- [M5] System users, apps e tokens: https://developers.facebook.com/docs/marketing-api/businessmanager/systemuser/install-apps-and-generate-tokens
- [M6] Insights best practices: https://developers.facebook.com/docs/marketing-api/insights/best-practices
- [M7] Ad Account Insights (referência): https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights/
- [M8] Ads Action Stats: https://developers.facebook.com/docs/marketing-api/reference/ads-action-stats
- [M9] Insights breakdowns: https://developers.facebook.com/documentation/ads-commerce/marketing-api/insights/breakdowns.md
- [M10] Ad previews: https://developers.facebook.com/docs/marketing-api/generatepreview
- [M11] Ad previews (referência): https://developers.facebook.com/docs/marketing-api/reference/adgroup/previews/
- [M12] Ad Creative: https://developers.facebook.com/docs/marketing-api/reference/ad-creative/
- [M13] Page Post: https://developers.facebook.com/docs/graph-api/reference/page-post/
- [M14] Instagram Media: https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/
- [M15] Facebook Login for Business: https://developers.facebook.com/docs/facebook-login/facebook-login-for-business

**Supabase**
- [S1] Pricing: https://supabase.com/pricing
- [S2] Backups: https://supabase.com/docs/guides/platform/backups
- [S3] Connecting to Postgres: https://supabase.com/docs/guides/database/connecting-to-postgres
- [S4] Edge Functions limits: https://supabase.com/docs/guides/functions/limits
- [S5] Testing (pgTAP, `supabase test db`): https://supabase.com/docs/guides/local-development/testing/overview
- [S6] Database migrations: https://supabase.com/docs/guides/deployment/database-migrations

**Vercel**
- [VC1] Fair use guidelines: https://vercel.com/docs/limits/fair-use-guidelines
- [VC2] Hobby plan: https://vercel.com/docs/plans/hobby
- [VC3] Pricing: https://vercel.com/pricing
- [VC4] Deployment protection: https://vercel.com/docs/deployment-protection
- [VC5] Cron jobs, uso e preços: https://vercel.com/docs/cron-jobs/usage-and-pricing
- [VC6] Functions limitations: https://vercel.com/docs/functions/limitations

**GitHub**
- [G1] Billing for GitHub Actions: https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions
- [G2] Actions limits: https://docs.github.com/en/actions/reference/limits
- [G3] Events that trigger workflows (`schedule`): https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows
- [G4] Workflow run logs: https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/monitoring-workflows/using-workflow-run-logs
- [G5] Download workflow artifacts: https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts
- [G6] Retenção de artefatos e logs: https://docs.github.com/en/organizations/managing-organization-settings/configuring-the-retention-period-for-github-actions-artifacts-and-logs-in-your-organization
- [G7] Using secrets in GitHub Actions: https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions
- [G8] Security hardening for GitHub Actions: https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions
- [G9] About secret scanning: https://docs.github.com/en/code-security/secret-scanning/introduction/about-secret-scanning
- [G10] About push protection: https://docs.github.com/en/code-security/secret-scanning/introduction/about-push-protection
- [G11] Protected branches: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
