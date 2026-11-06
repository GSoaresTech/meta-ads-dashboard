# ADR-0009: Modelo de dados

- Status: Aceito
- Data: 03/11/2026
- Atualizado em: 05/11/2026, com o ponto "Ações das quebras" da §2 substituído pelo ADR-0011, a rotina diária na §5, as regras das credenciais e o retorno de `obter_desempenho` na §4 e os operandos das métricas derivadas na §2; e em 06/11/2026, com a `obter_trilha`, o retorno de `listar_entidades` e de `listar_metricas` e a `listar_resultados` na §4, a carga histórica na §5 e a carga dos rótulos de status na §2, e com os índices da resolução do resultado na §4

## Contexto

O `CLAUDE.md` (§3 a §6) e os ADRs 0002, 0004, 0005, 0006 e 0007 fixam as regras de modelagem: três camadas, `empresa_id` em toda tabela de negócio, 3FN em `normalizado`, tabela longa de ações, catálogo como dado, alcance por período e acesso do painel só por funções que recebem a credencial. Falta o desenho concreto que as migrations vão criar. Pontos decididos neste ADR:

- As tabelas de cada esquema, com grão, chaves e restrições;
- Como as chaves impedem que uma linha aponte para dado de outra empresa;
- Os papéis de banco e o que cada um pode fazer;
- A assinatura das funções de `analitico` que recebem a credencial;
- A substituição da janela reprocessada;
- A revisão de dados pessoais exigida pelo RNF-24.

As restrições de plataforma que pesam aqui estão no `docs/REQUIREMENTS.md`, de R-29 a R-36. Em resumo:
- Esquemas próprios ficam fora da Data API e não recebem privilégios padrão (R-29).
- `postgres` e `service_role` ignoram o RLS, e um papel próprio fica sujeito a ele (R-30).
- Toda função nasce executável por `PUBLIC` (R-31).
- Um papel próprio conecta pelo pooler como `[ROLE].[PROJECT-REF]` (R-32).
- Uma senha definida por SQL pode ir para logs (R-33).
- O `postgres` não consegue `SET ROLE` para o papel que cria (R-34).
- O `supabase db push` aplica as migrations com o `postgres` como papel efetivo (R-36).

## Opções consideradas

### Isolamento entre empresas nas chaves

| Opção | Prós | Contras |
|---|---|---|
| **(a) `empresa_id` em toda tabela de negócio e FK composta `(empresa_id, <pai>_id)` → `<pai> (empresa_id, id)`** | O banco recusa um filho que aponte para um pai de outra empresa. Todo índice de consulta começa por `empresa_id` | `empresa_id` se repete em tabelas onde seria derivável pelo pai, o que foge da 3FN estrita |
| (b) `empresa_id` em toda tabela, com FK simples para o pai | Mesma coluna, FK mais curta | Nada impede que o `empresa_id` do filho divirja do pai. O isolamento passa a depender da ETL |
| (c) `empresa_id` só em `empresa` e `conta_anuncio`, derivado por junção nas demais | 3FN estrita | Contraria o `CLAUDE.md` §4. Toda consulta e todo teste de isolamento exigem a junção até a conta |

### Leitura do painel

| Opção | Prós | Contras |
|---|---|---|
| **(a) Funções `SECURITY DEFINER` em `analitico`, donas do `postgres`, com o `painel_leitor` só com `EXECUTE`** | A credencial é resolvida no banco em toda chamada (ADR-0004). O painel não tem `SELECT` em nada. Cada função tem teste de isolamento (RNF-14) | Cada função precisa de `search_path` fixo, `REVOKE` de `PUBLIC` e filtro próprio por empresa (R-31) |
| (b) `SELECT` em views, com políticas RLS para o `painel_leitor` que leem a empresa de uma variável de sessão | As políticas valem para qualquer consulta | O próprio cliente define a variável de sessão, então quem conecta escolhe a empresa. A credencial deixaria de ser verificada a cada chamada |
| (c) Painel conectado como `postgres` | Simples | Acesso total ao banco, contra o ADR-0004 e o ADR-0010 |

### Escrita da ETL com RLS habilitado

| Opção | Prós | Contras |
|---|---|---|
| **(a) Grants por tabela e uma política `TO etl_carga` com `USING (true)` em cada tabela que ela usa** | O que a ETL pode fazer fica explícito por tabela e comando. O RLS continua negando todos os outros papéis | Uma política a mais por tabela |
| (b) `etl_carga` com `bypassrls` | Nenhuma política | O atributo ignora qualquer política futura, e a documentação pede para nunca distribuir a senha de um papel com ele (R-30). A senha fica num secret de repositório público (ADR-0008) |
| (c) ETL conectada como `postgres` | Simples | A credencial da ETL poderia alterar o schema e ler as credenciais de acesso |

### Substituição da janela reprocessada

| Opção | Prós | Contras |
|---|---|---|
| **(a) Apagar o escopo e inserir o conjunto completo, na mesma transação** | Uma regra só para todos os fatos. Tipos de ação que somem na revisão da Meta deixam de existir sem lógica extra (RF-17) | Reescreve linhas que não mudaram, o que gera tuplas mortas para o autovacuum. O volume é pequeno (`docs/REQUIREMENTS.md` §4.2) |
| (b) Upsert linha a linha e exclusão dos órfãos por anti-junção | Só toca as linhas que mudaram | Duas operações por tabela, e um erro na anti-junção deixa órfãos |
| (c) Partição por mês, com troca da partição | Troca barata em volume grande | Não serve às janelas de 2 e 28 dias, e o volume não justifica a complexidade |

## Decisão

### 1. Convenções

- **Chave interna**: `id uuid DEFAULT gen_random_uuid()` em toda tabela com chave substituta, salvo as de alto volume sem referência externa, que usam `id bigint` identity (`quebra_diaria_campanha`, `aviso_execucao`, `bruto.resposta_api`).
  - **Fatos**: não têm chave substituta, e a PK é o próprio grão. As exceções são `quebra_diaria_campanha` e `alcance_periodo`, que têm coluna anulável no grão e por isso usam `UNIQUE NULLS NOT DISTINCT`, explicado adiante.
  - **Catálogos**: usam o código como PK, salvo `resultado_objetivo`, que também tem coluna anulável na chave natural.
- **Chave natural da Meta**: `id_meta text NOT NULL UNIQUE`, com `CHECK (id_meta ~ '^[0-9]+$')`, porque a Meta declara esses IDs como "numeric string" (R-35). A conta guarda o `account_id`, sem o prefixo `act_`. O `UNIQUE` é global e não começa por `empresa_id`, porque os IDs da Meta são únicos na plataforma, cada entidade pertence a uma única conta, e só a ETL os consulta. A exceção é `pagina`: uma Página não pertence a uma conta de anúncios e pode aparecer em criativos de empresas diferentes, então o `UNIQUE` dela é `(empresa_id, id_meta)`, e cada empresa guarda a própria cópia.
- **Isolamento**: toda tabela de negócio tem `empresa_id uuid NOT NULL`. Toda tabela que é pai de outra tem `UNIQUE (empresa_id, id)`. Toda FK entre tabelas de negócio é composta, `(empresa_id, <pai>_id) REFERENCES <pai> (empresa_id, id)`, então nenhuma linha aponta para outra empresa. A repetição de `empresa_id` é uma exceção deliberada à 3FN: a FK composta obriga o valor a ser igual ao do pai, o que elimina a anomalia de atualização.
- **Exclusão**: as FKs são `NO ACTION`, salvo as das tabelas de ações para o fato a que pertencem, que usam `ON DELETE CASCADE`. Uma exclusão acidental de empresa ou entidade falha em vez de apagar em cascata. A exclusão a pedido (RNF-25) é uma função que apaga de baixo para cima, numa só transação.
- **Tipos**:
  - dinheiro: `numeric`, sem escala fixa, com `CHECK (>= 0)`;
  - contagens: `bigint`, com `CHECK (>= 0)`;
  - instantes: `timestamptz`, em colunas `*_em`;
  - datas de métrica: `date`, no fuso da conta.

  Métrica-base ausente é `NULL` (`CLAUDE.md` §5).
- **Obrigatoriedade**: toda coluna é `NOT NULL`, salvo as que este ADR descreve como anuláveis: medidas dos fatos, campos da Meta que podem faltar (nome, textos e links do criativo, meta de otimização) e colunas com significado próprio para `NULL`. Isso vale em especial para as colunas de domínio (`status`, `tipo`, `escopo`, `situacao`, `sentido`, `tipo_periodo`, `tipo_quebra`, `categoria`), porque um `CHECK` avaliado como `NULL` passa.
- **Texto**: toda coluna de texto livre tem `CHECK (col = btrim(col) AND col <> '')`. Assim o banco recusa texto não aparado e string vazia, que a ETL converte em `NULL` (RF-13).
- **Enums da API**:
  - **Domínio fechado**, como o `status` das entidades (R-35): `CHECK` com a lista de valores. Um valor novo da Meta faz a carga falhar e exige migration.
  - **Domínio aberto**: objetivo, meta de otimização, chamada para ação, tipo de ação, tipo de evento de atribuição e categorias de quebra. Ficam em `text` com `CHECK` de formato, sem lista. Um objetivo desconhecido não pode quebrar a carga (RF-15), e tipos de ação personalizados não têm lista fechada (R-21).
  - Os rótulos de negócio vêm sempre do catálogo, nunca do código (ADR-0007):
    - o objetivo, de `resultado_objetivo.nome_objetivo`;
    - os tipos de ação, pelas métricas de `metrica`;
    - os demais valores exibidos, de `rotulo_valor_api`.

    A meta de otimização e o tipo de evento de atribuição não aparecem na tela.
- **Datas de fatos**: toda coluna `data` de fato tem FK para `calendario (data)`. Uma data fora do calendário falha na carga, em vez de sumir em silêncio de um agrupamento.
- **Rastreio**: fatos, entidades e `conta_anuncio` guardam `execucao_id`, a última execução que gravou a linha, com FK composta para `execucao_carga`. Assim cada linha chega à resposta bruta da mesma execução (RF-09).

### 2. Tabelas

O grão é "uma linha por". Colunas de auditoria (`criado_em`, `atualizado_em`) e `execucao_id` estão omitidas onde não há o que dizer.

#### `normalizado`: empresas, contas e acesso

- **`empresa`**: uma linha por empresa atendida.
  - PK `id`. Colunas `nome`, `situacao` (`ativa`, `inativa`), `criado_em`, `atualizado_em`.
  - Não tem `empresa_id`: é a raiz.
- **`conta_anuncio`**: uma linha por conta de anúncios da Meta.
  - PK `id`. `UNIQUE (id_meta)` e `UNIQUE (empresa_id, id)`. FK `empresa_id` → `empresa`.
  - Colunas `nome`, `fuso_horario`, `moeda`, `situacao` (`ativa`, `inativa`) e `execucao_id` (nulo até a primeira extração).
  - `moeda` tem `CHECK (moeda ~ '^[A-Z]{3}$')`, o formato da ISO 4217. `fuso_horario` tem `CHECK` de formato (letras, dígitos, `_`, `-`, `+` e `/`) e um trigger, `normalizado.validar_fuso_horario()`, que na inclusão e na alteração do fuso confere o nome em `pg_timezone_names` e recusa com `23514` o que não está na base IANA. O `AT TIME ZONE` não serve para essa conferência, porque aceita especificações POSIX, como `XYZ+3`, que não são nomes IANA. Um `CHECK` com função também não, porque o `pg_dump` põe o `CHECK` no `CREATE TABLE`, antes dos dados: um nome retirado do tzdata de um Postgres mais novo impediria a restauração. Já o trigger é criado depois dos dados e vale só para a escrita.
  - `nome`, `fuso_horario` e `moeda` ficam `NULL` entre o cadastro, que informa só o ID (RF-43), e a primeira extração. Um `CHECK` exige `fuso_horario` e `moeda` juntos.
- **`credencial_acesso`**: uma linha por link de empresa ou credencial de operador (ADR-0004).
  - PK `id`. `UNIQUE (hash)`, com `hash bytea` e `CHECK (octet_length(hash) = 32)`, o tamanho do SHA-256. O token em texto puro não cabe em nenhuma coluna (RNF-15).
  - Colunas `escopo` (`empresa`, `operador`), `empresa_id`, `criado_em`, `revogado_em`.
  - `CHECK ((escopo = 'empresa') = (empresa_id IS NOT NULL))` e `CHECK (revogado_em >= criado_em)`.
  - É a única tabela de negócio com `empresa_id` anulável, porque a credencial do operador não pertence a uma empresa. Não há coluna que identifique a pessoa que recebeu o link (§6).

#### `normalizado`: entidades da Meta

Todas têm `UNIQUE (id_meta)` (ou `UNIQUE (empresa_id, id_meta)`, em `pagina`), `UNIQUE (empresa_id, id)`, `status` com `CHECK (status IN ('ACTIVE', 'PAUSED', 'DELETED', 'ARCHIVED'))` (R-35), quando a entidade tem status, e FK composta para o pai. A ETL não apaga entidades: uma entidade excluída na Meta fica com `status = 'DELETED'`, e só o estado atual é guardado (`docs/REQUIREMENTS.md` §1.2).

- **`pagina`**: uma linha por Página do Facebook usada em criativos. Colunas `id_meta`, `nome`, para a prévia (RF-40). O ID da Página também é "numeric string" (R-35) e tem o mesmo `CHECK` numérico.
- **`campanha`**: uma linha por campanha. Pai: `conta_anuncio`. Colunas `nome`, `objetivo` (`NOT NULL`, domínio aberto), `status`.
- **`conjunto_anuncio`**: uma linha por conjunto de anúncios. Pai: `campanha`. Colunas `nome`, `meta_otimizacao` (domínio aberto), `status`.
- **`janela_atribuicao_conjunto`**: uma linha por conjunto × tipo de evento. A tabela longa de `attribution_spec` (R-35).
  - PK `(empresa_id, conjunto_anuncio_id, tipo_evento)`. Coluna `janela_dias integer`, com `CHECK (janela_dias > 0)`.
  - A ETL substitui as linhas do conjunto a cada atualização dele.
- **`criativo`**: uma linha por criativo, reutilizável por vários anúncios (N:1). Pais: `conta_anuncio` e, opcionalmente, `pagina`, identificada pelo `actor_id` do criativo (R-35).
  - Colunas `titulo`, `texto`, `chamada_acao` (domínio aberto), `id_publicacao_facebook`, `link_publicacao_facebook`, `id_midia_instagram`, `link_publicacao_instagram`, `caminho_miniatura`.
  - `id_publicacao_facebook` é texto sem `CHECK` numérico, porque a Meta o declara como token "Post ID" (R-35).
  - Origem (R-27): `id_publicacao_facebook` vem de `effective_object_story_id`; `link_publicacao_facebook`, do `permalink_url` do post, que não é lido sem a Página atribuída ao System User (ADR-0003; Q-06); `id_midia_instagram`, de `effective_instagram_media_id`; e `link_publicacao_instagram`, do `instagram_permalink_url` do criativo.
  - `caminho_miniatura` é o caminho no Storage, derivado do `id` interno e nunca do ID da Meta (RF-38).
- **`anuncio`**: uma linha por anúncio. Pais: `conjunto_anuncio` e `criativo`, ambos `NOT NULL` (RF-01). Colunas `nome`, `status`.

O anúncio não guarda `campanha_id` nem `conta_anuncio_id`, que são deriváveis pelo conjunto. A junção até a conta tem três passos.

#### `normalizado`: fatos

| Tabela | Grão | PK ou `UNIQUE` | Colunas de medida | Restrições |
|---|---|---|---|---|
| `metrica_diaria_anuncio` | anúncio × dia | PK `(empresa_id, anuncio_id, data)` | `investimento`, `impressoes`, `alcance` (alcance do dia, nunca somado entre dias) | medidas anuláveis e `>= 0`; FK composta para `anuncio`; FK de `data` para `calendario` |
| `acao_diaria_anuncio` | anúncio × dia × tipo de ação | PK `(empresa_id, anuncio_id, data, tipo_acao)` | `quantidade` (de `actions`), `valor` (de `action_values`) | `>= 0`; `CHECK (quantidade IS NOT NULL OR valor IS NOT NULL)`; FK `(empresa_id, anuncio_id, data)` → `metrica_diaria_anuncio` com `ON DELETE CASCADE` |
| `quebra_diaria_campanha` | campanha × dia × tipo de quebra × categoria | PK `id bigint` identity; `UNIQUE NULLS NOT DISTINCT (empresa_id, campanha_id, data, tipo_quebra, categoria, subcategoria)` | `investimento`, `impressoes`, `alcance` | `tipo_quebra IN ('idade_genero', 'plataforma_posicionamento', 'regiao')`; `CHECK ((tipo_quebra = 'regiao') = (subcategoria IS NULL))` |
| `acao_quebra_diaria_campanha` | linha de quebra × tipo de ação | PK `(empresa_id, quebra_diaria_campanha_id, tipo_acao)` | `quantidade`, `valor` | como em `acao_diaria_anuncio`; FK composta para a quebra com `ON DELETE CASCADE` |
| `alcance_periodo` | entidade × tipo de período × início do período | `UNIQUE NULLS NOT DISTINCT (empresa_id, conta_anuncio_id, campanha_id, anuncio_id, tipo_periodo, inicio_periodo)` | `alcance`, `impressoes` | `CHECK (num_nonnulls(conta_anuncio_id, campanha_id, anuncio_id) = 1)`; `tipo_periodo IN ('semana', 'mes', 'ano')`; FKs de `inicio_periodo` e `fim_periodo` para `calendario`; alinhamento dos dois |

Detalhes que a tabela não comporta:
- **Fatos sem `conta_anuncio_id` e ações sem coluna por tipo**: nenhum fato guarda a conta, que é derivável pelo anúncio ou pela campanha. As ações seguem a tabela longa do `CLAUDE.md` §5, e a ausência de linha significa zero.
- **Fatos sem colunas de auditoria**: a carga substitui as linhas a cada execução (§5), então `criado_em` repetiria o instante da execução, que já vem por `execucao_id`.
- **Formato do tipo de ação**: segmentos de letras minúsculas, dígitos e `_`, separados por ponto, o primeiro começando por letra. Cobre os tipos do R-21 e as conversões personalizadas, que a Meta devolve como `offsite_conversion.custom.<id>`. Um tipo fora desse formato faz a carga falhar com `23514` até uma migration ampliar o `CHECK`.
- **Quebras**: idade+gênero e plataforma+posicionamento têm duas dimensões (`categoria` e `subcategoria`), e região tem uma. Como `subcategoria` é anulável, ela não pode entrar numa PK. Por isso a quebra usa chave substituta, e o grão é garantido pelo `UNIQUE NULLS NOT DISTINCT`, que trata dois `NULL` como iguais. O valor da categoria é o da API; o rótulo vem do catálogo. Como a região chega em texto livre, com espaços e acentos, o formato de `categoria` e `subcategoria` é só o do texto aparado e não vazio (§1).
- **Ações das quebras**: substituído pelo ADR-0011, que grava só o tipo de ação do resultado principal de cada campanha. O resultado principal não é coluna, porque depende do catálogo e da sobrescrita, e por isso é derivado em `analitico`.
- **Alcance por período**:
  - **Entidade**: o `CHECK` de `num_nonnulls` exige exatamente uma entidade por linha, cada uma com sua FK composta. As FKs são `MATCH SIMPLE`, então só a da entidade preenchida é conferida. Como duas das três colunas ficam sempre nulas, a tabela não tem PK, e o grão fica só no `UNIQUE NULLS NOT DISTINCT`.
  - **Fim do período**: `fim_periodo` é guardado porque não é derivável no período corrente. A semana, o mês e o ano em andamento são extraídos só até o dia da extração (ADR-0006).
  - **Alinhamento**: `CHECK`s exigem que o fim não venha antes do início, que a semana comece numa segunda-feira e dure até 7 dias, que o mês comece no dia 1 e termine no mesmo mês, e que o ano comece em 1º de janeiro e termine no mesmo ano. Esses `CHECK`s usam `extract` só para validar a linha. O agrupamento por semana, mês e ano continua vindo apenas de `calendario` (`CLAUDE.md` §5).

Índices de consulta, além das PKs: `(empresa_id, data)` em cada fato diário, para os intervalos do painel e para a substituição da janela.

#### `normalizado`: calendário e catálogo

Estas tabelas são globais, não pertencem a uma empresa e por isso não têm `empresa_id`.

- **`calendario`**: uma linha por data.
  - PK `data`. Colunas `dia_semana_iso`, `semana_iso`, `ano_iso`, `inicio_semana`, `mes`, `ano`, `inicio_mes` e `nome_mes` (pt-BR).
  - Um `CHECK` em cada coluna a amarra à `data`, com `extract` e `make_date`. Assim, uma linha incoerente é recusada mesmo numa migration que estenda o intervalo. `nome_mes` é coluna gerada a partir de `mes`, por mapeamento fixo, sem depender do locale do servidor.
  - O intervalo vai de 01/01/2023 a 31/12/2035 e é gerado pela própria migration. Ele cobre os 37 meses de histórico (R-19) de qualquer conta cadastrada até o fim do intervalo.
- **`metrica`**: uma linha por métrica do catálogo (`docs/REQUIREMENTS.md` §7.1).
  - PK `codigo`. `UNIQUE (codigo, unidade)`, alvo da FK composta de `meta_desempenho`.
  - Colunas `rotulo`, `explicacao` (`CHECK (char_length(explicacao) <= 200)`, RNF-01), `formula`, `unidade` (`moeda`, `quantidade`, `percentual`, `razao`), `aditiva`, `tipo` (`base`, `acao`, `derivada`), `campo_base`, `tipo_acao`, `medida_acao` (`quantidade`, `valor`), `numerador`, `denominador` e `fator`.
  - `CHECK`s amarram o tipo à origem: `base` exige `campo_base`; `acao` exige `tipo_acao` e `medida_acao`; `derivada` exige `numerador`, `denominador` e `fator` (`> 0`), e só ela os tem.
  - A derivada vale `numerador ÷ denominador × fator`. `numerador` e `denominador` têm FK para `metrica`, e um teste pgTAP confere que nenhum deles é outra derivada. Assim, as funções de `analitico` calculam a razão a partir das somas do recorte sem repetir a fórmula no código, e a `formula` continua sendo o texto que explica a conta na tela. O percentual é guardado como fração, que a formatação pt-BR exibe multiplicada por 100 (RF-35): o fator do CTR é 1, e o "× 100" da fórmula descreve a exibição.
  - `campo_base` guarda o nome da coluna de `metrica_diaria_anuncio` já em português (`investimento`), e não o campo da API (`spend`). A tradução fica só no mapa de campos da ETL, e um teste pgTAP confere que a coluna existe. `tipo_acao` guarda o tipo de ação como a API o entrega, que é o valor gravado na tabela longa de ações.
- **`resultado_objetivo`**: uma linha por objetivo × meta de otimização (`docs/REQUIREMENTS.md` §7.2).
  - PK `id`. `UNIQUE NULLS NOT DISTINCT (objetivo, meta_otimizacao)`.
  - Colunas `nome_objetivo`, `metrica_resultado` e `metrica_kpi`, estas duas com FK para `metrica` e anuláveis: "Não classificado" não tem resultado, e o resultado de `OUTCOME_APP_PROMOTION` é *a confirmar* (`docs/REQUIREMENTS.md` §7.2).
  - `meta_otimizacao` nula significa "qualquer". `objetivo` nulo é a linha única de "Não classificado", que guarda o rótulo e as métricas de apoio do caso sem catálogo. Um `CHECK` impede objetivo nulo com meta preenchida.
  - A precedência do ADR-0007 resolve "qualquer, exceto `CONVERSATIONS`": a linha específica vence a genérica.
- **`metrica_apoio_resultado`**: uma linha por resultado × métrica de apoio. PK `(resultado_objetivo_id, metrica)`. `UNIQUE (resultado_objetivo_id, ordem)`.
- **`objetivo_equivalente`**: uma linha por objetivo legado. PK `objetivo_legado`. Coluna `objetivo`, o objetivo atual equivalente, pela tabela oficial resumida no `docs/REQUIREMENTS.md` §7.2. Os legados com mais de um equivalente (`CONVERSIONS`, `VIDEO_VIEWS`) seguem *a confirmar*, e os sem equivalente oficial (`LOCAL_AWARENESS`, `OFFER_CLAIMS`) não têm o que gravar até a Q-10 ser resolvida.
- **`rotulo_valor_api`**: uma linha por domínio × valor de enum da API. PK `(dominio, valor)`. Coluna `rotulo`.
  - Domínios: `status`, `chamada_acao`, `genero`, `plataforma` e `posicionamento`. Cada domínio ganha as linhas com a visão que o exibe.
  - O `status` é domínio fechado, e todo valor do `CHECK` das entidades tem rótulo: o teste pgTAP lê o `CHECK` e falha se um valor novo vier sem ele. Os rótulos estão no feminino, porque a campanha é a entidade cujo status a tela mostra (RF-37).
  - Nos domínios abertos, um valor sem rótulo aparece no painel como "Não identificado", e o rótulo dessa situação também mora no catálogo.

#### `normalizado`: dados operacionais por empresa

- **`sobrescrita_resultado_campanha`**: uma linha por campanha com resultado definido pelo operador (RF-49).
  - PK `(empresa_id, campanha_id)`, com FK composta para `campanha`.
  - Colunas `metrica_resultado` e `metrica_kpi`, com FK para `metrica`.
- **`meta_desempenho`**: uma linha por meta cadastrada (RF-41).
  - PK `id`. Colunas `empresa_id`, `campanha_id` (nula na meta da empresa, com FK composta para `campanha`), `metrica`, `unidade`, `valor_alvo` (`>= 0`), `sentido` (`no_maximo`, `no_minimo`), `moeda`, `inicio_vigencia`, `fim_vigencia` (nula numa meta de campanha sem prazo) e `encerrado_em`.
  - **Unidade e moeda**: `(metrica, unidade)` referencia `metrica (codigo, unidade)`, o que deixa o `CHECK ((unidade = 'moeda') = (moeda IS NOT NULL))` dentro de uma única linha. Uma meta em dinheiro sempre diz a moeda, e valores de moedas diferentes nunca se comparam (RF-34).
  - **Vigência**: a meta da empresa vale por mês. Um `CHECK` exige início no dia 1 e fim no último dia do mesmo mês.
  - **Uma meta vigente por escopo e métrica**: duas restrições `EXCLUDE USING gist`, uma para metas da empresa e outra para metas de campanha, recusam vigências sobrepostas (`daterange(inicio_vigencia, fim_vigencia, '[]') WITH &&`) entre metas não encerradas da mesma empresa ou campanha e métrica. Assim, a "meta vigente" do RF-42 é sempre uma só. A restrição exige a extensão `btree_gist`, disponível na imagem do banco local.

#### `normalizado`: controle de execuções

- **`execucao_carga`**: uma linha por execução × empresa (RF-20).
  - PK `id`, que é o `execucao_id` dos logs. `UNIQUE (empresa_id, id)`.
  - Colunas `tipo` (`horaria`, `diaria`, `historica`), `status` (`em_andamento`, `sucesso`, `falha`, `ignorada`), `iniciado_em`, `terminado_em` e `erro`.
  - `CHECK ((status = 'em_andamento') = (terminado_em IS NULL))`, `CHECK (terminado_em >= iniciado_em)` e `CHECK (status <> 'falha' OR erro IS NOT NULL)`, com o `CHECK` de texto que proíbe erro vazio.
  - Índice `(empresa_id, iniciado_em)` para a área do operador (RF-51) e para a detecção de carga parada (RNF-13).
- **`contagem_linhas_execucao`**: uma linha por execução × tabela. PK `(empresa_id, execucao_id, tabela)`, com FK composta para `execucao_carga`. Coluna `linhas bigint`, com `CHECK (linhas >= 0)`.
- **`aviso_execucao`**: uma linha por aviso. PK `id bigint` identity, com FKs compostas para `execucao_carga` e, quando houver, para `campanha`. Colunas `tipo` (`objetivo_nao_classificado`, `divergencia_resultado`), `campanha_id` (opcional) e `criado_em`. Recebe os avisos do RF-15 e do RF-16.
- **`fatia_historica`**: uma linha por conta × mês da carga histórica (RF-07).
  - PK `(empresa_id, conta_anuncio_id, mes_referencia)`. `CHECK` de que `mes_referencia` é dia 1.
  - Colunas `status` (`pendente`, `concluida`, `falha`) e `execucao_id`, com FKs compostas para `conta_anuncio` e `execucao_carga`.
- **`uso_cota`**: uma linha por dia × recurso do plano (RF-52).
  - PK `(data, recurso)`. `recurso IN ('disco_projeto', 'storage_organizacao', 'egress_organizacao', 'egress_cache_organizacao')`.
  - Colunas `uso_gb`, `cota_gb`, `parcela` (`CHECK (parcela > 0 AND parcela <= 1)`) e `limite_alerta` (`CHECK (limite_alerta > 0 AND limite_alerta <= 1)`, hoje 0,7).
  - A ETL grava a parcela e o limite a partir das constantes de configuração. O aviso do RF-52 é derivado em `analitico` quando `uso_gb > cota_gb × parcela × limite_alerta`, sem tabela de avisos própria. Cada linha guarda os valores que valiam no dia, para que mudar uma constante não reescreva o passado.
  - É global e não tem `empresa_id`, porque mede o projeto (ADR-0010).

#### `bruto`

- **`resposta_api`**: uma linha por resposta (página) recebida da Meta (ADR-0005).
  - PK `id bigint` identity. FKs compostas para `execucao_carga` e `conta_anuncio`.
  - Colunas `endpoint`, `parametros jsonb`, `data_referencia`, `resposta jsonb` e `recebido_em`.
  - `data_referencia` é a última data coberta por uma consulta de insights. Nas consultas de cadastro, que não têm intervalo, é a data da extração no fuso da conta. Assim, a retenção do RF-21 alcança toda linha.
  - `CHECK (NOT parametros ? 'access_token')`: o token vai no cabeçalho de autorização e nunca é gravado. O operador `?` só compara a chave inteira, no primeiro nível, então `CHECK (jsonb_typeof(parametros) = 'object')` recusa parâmetros em texto ou lista, em que um `access_token=...` escaparia da conferência. Os links de paginação (`paging.next` e `paging.previous`) são retirados da resposta antes da gravação, e um teste da ETL prova que nenhuma resposta gravada contém `access_token`.
  - Índice `(data_referencia)`, para a retenção.
  - Não segue a 3FN, porque é a resposta como recebida.

#### `analitico`

Não guarda tabelas. Tem só funções (§4) e, quando ajudarem a escrevê-las, views com `security_invoker = true`. Por padrão, uma view criada pelo `postgres` ignora o RLS (R-30). Nenhuma view é concedida ao `painel_leitor`, porque uma view não recebe a credencial e não tem como filtrar por empresa.

### 3. Papéis e privilégios

| Papel | Quem usa | Login | Pode | Não pode |
|---|---|---|---|---|
| `postgres` | Migrations e operações do runbook | Sim (senha do projeto) | Tudo; é dono de todos os objetos e das funções `SECURITY DEFINER`. Tem `bypassrls` (R-30) | — |
| `etl_carga` | ETL no GitHub Actions, pelo pooler de sessão, com o usuário `etl_carga.<ref-do-projeto>` (R-32) | Sim | `USAGE` em `bruto` e `normalizado` e o que a tabela abaixo concede; `EXECUTE` em `normalizado.resolver_resultado_campanha`; `pg_try_advisory_xact_lock` | DDL, `TRUNCATE`, `analitico`, credenciais, metas e escrita de sobrescritas |
| `painel_leitor` | Servidor do painel na Vercel, pelo pooler, com `painel_leitor.<ref-do-projeto>` | Sim | `USAGE` em `analitico` e `EXECUTE` em cada função pública de `analitico`, concedido função a função | `SELECT`, `INSERT`, `UPDATE` ou `DELETE` em qualquer tabela ou view; `USAGE` em `bruto` e `normalizado` |
| `anon`, `authenticated` | Data API (PostgREST) | — | Nada nos nossos esquemas | Ler ou escrever qualquer tabela; executar qualquer função nossa |
| `service_role` | Data API com a chave secreta | — | Nada nos nossos esquemas; o `bypassrls` dele (R-30) não vale sem grant | O mesmo que `anon` |

Privilégios da `etl_carga`:

| Objeto | Privilégios |
|---|---|
| `bruto.resposta_api` | `SELECT`, `INSERT`, `DELETE` (retenção) |
| `empresa` | `SELECT` |
| `conta_anuncio` | `SELECT`; `UPDATE` só em `nome`, `fuso_horario`, `moeda`, `execucao_id`, `atualizado_em` |
| `pagina`, `campanha`, `conjunto_anuncio`, `anuncio`, `criativo` | `SELECT`, `INSERT`, `UPDATE` |
| `janela_atribuicao_conjunto` e os cinco fatos | `SELECT`, `INSERT`, `DELETE` |
| `execucao_carga`, `fatia_historica`, `uso_cota` | `SELECT`, `INSERT`, `UPDATE` |
| `contagem_linhas_execucao`, `aviso_execucao` | `SELECT`, `INSERT` |
| `calendario`, as tabelas de catálogo e `sobrescrita_resultado_campanha` | `SELECT` |
| `credencial_acesso`, `meta_desempenho` | nenhum |

Regras:
- **Esquemas fora da Data API**: `bruto`, `normalizado` e `analitico` não entram em "Exposed schemas" (o `[api] schemas` do `supabase/config.toml` continua só com `public` e `graphql_public`). Nenhum grant vai para `anon`, `authenticated` ou `service_role` (R-29).
- **RLS**: habilitado em toda tabela, inclusive nas globais. Sem `FORCE`, que não teria efeito: o dono (`postgres`) tem `bypassrls`, que ignora também o `FORCE` (R-30). A única política é `FOR ALL TO etl_carga USING (true) WITH CHECK (true)`, nas tabelas que a ETL usa; os grants acima limitam os comandos. Não existe política para nenhum outro papel.
- **Funções**:
  - **Atributos**: toda função dos nossos esquemas é criada com `SET search_path = ''` e nomes qualificados pelo esquema.
  - **Revogação de `PUBLIC`**: na mesma migration, cada função recebe `REVOKE ALL ON FUNCTION ... FROM PUBLIC`, e só então os grants explícitos. Não usamos `ALTER DEFAULT PRIVILEGES`: a revogação global do padrão de `PUBLIC` atingiria funções de outros esquemas (R-31), e o grant função a função deixa cada permissão visível na migration que a cria.
- **Associação ao `postgres`**: `etl_carga` e `painel_leitor` não são membros de nenhum papel. O `postgres` recebe `GRANT etl_carga, painel_leitor TO postgres WITH INHERIT FALSE, SET TRUE`, para que os testes pgTAP possam fazer `SET ROLE` sem que o `postgres` herde nada deles (R-34).
- **`pg_net`**: não usamos o `pg_net`. Com ele instalado, nossos papéis leem a fila de requisições pelo que `PUBLIC` recebe, e o Supabase não permite mudar os grants dessa fila (R-30). A migration dos papéis remove a extensão com `DROP EXTENSION IF EXISTS pg_net` e `DROP SCHEMA IF EXISTS net`, como a documentação indica. Um teste pgTAP prova que `etl_carga` e `painel_leitor` não têm `USAGE` no esquema `net`.
  - **Estado de produção**: o desenho não depende dele. Os dois comandos não fazem nada se a extensão não existir, e uma recusa da remoção interrompe o `db push` antes de qualquer outro objeto ser criado.
  - **Verificação local**: no banco local, a extensão vem instalada, o `postgres` consegue removê-la, e a remoção leva o esquema `net` junto.
- **Criação idempotente**: papéis são do cluster, não do banco, e por isso a migration os cria dentro de um bloco que confere `pg_roles` antes do `CREATE ROLE`.

**Senhas**: a migration cria os papéis com `LOGIN` e sem senha. Senha nula nunca autentica (R-33), então um papel recém-criado não abre conexão até alguém definir a senha. A senha nunca entra em migration, seed, `.env.example`, log ou histórico do shell. Em produção, depois do `supabase db push --linked` (ADR-0010):
1. Geramos a senha no gerenciador de senhas, onde ela fica guardada.
2. Conectamos como `postgres` com o `psql` e rodamos `\password etl_carga` e `\password painel_leitor`. O `psql` calcula o hash no cliente e envia um `ALTER ROLE` entre aspas simples, que o Supabase mascara no log (R-33). Nunca usamos `ALTER ROLE ... PASSWORD` com a senha entre cifrões, que vai para o log em texto puro.
3. Gravamos a string de conexão da ETL no secret `URL_BANCO` do Actions e a do painel numa variável de servidor do tipo Secret na Vercel, sem `NEXT_PUBLIC_` (ADR-0010; `CLAUDE.md` §12).

A rotação repete os passos 1 a 3, e o procedimento entra no runbook (RF-53). No banco local, os testes usam `SET ROLE` e não precisam de senha. Se o painel local precisar conectar, a senha local também é definida com `\password`.

### 4. Funções de `analitico`

Convenções de toda função que o painel chama:
- **Atributos**: `SECURITY DEFINER`, dona do `postgres`, com `SET search_path = ''`. As de leitura são `STABLE`; as de escrita, `VOLATILE`.
- **Parâmetros**:
  - **Credencial**: o primeiro parâmetro é sempre `p_credencial text`, o token do cookie como chegou. O banco calcula `sha256(convert_to(p_credencial, 'UTF8'))` e procura o hash; o painel nunca envia o hash (ADR-0004).
  - **Empresa**: o segundo, quando a função atua sobre uma empresa, é `p_empresa_id uuid`.
  - **Entidades**: são sempre identificadas pelo `id` interno, nunca pelo ID da Meta.
  - **Prefixo**: o `p_` evita ambiguidade entre parâmetro e coluna no corpo da função.
- **Resolução**: uma função interna, `normalizado.resolver_credencial(p_credencial text) RETURNS TABLE (escopo text, empresa_id uuid)`, devolve o escopo de uma credencial existente, não revogada e, no escopo de empresa, de empresa ativa. Ela é `SECURITY INVOKER` e não é concedida ao `painel_leitor`; só as funções de `analitico` a chamam.
- **Acesso negado em leitura**: quando a credencial é inválida, está revogada ou é de outra empresa, a função de leitura devolve zero linhas, sem erro. O painel responde 404 sem revelar se a empresa existe (RF-46).
- **Acesso negado em escrita**: as funções de escrita da área do operador exigem escopo `operador` e, sem ele, levantam o SQLSTATE `42501` com mensagem genérica.
- **Retorno**: `RETURNS TABLE` com colunas em português. Todo valor monetário sai acompanhado da `moeda` da conta, e totais nunca somam moedas diferentes (RF-34).
- **Testes**: cada função tem o teste pgTAP de isolamento do RNF-14. Um teste geral falha se alguma função de `bruto`, `normalizado` ou `analitico` for executável por `PUBLIC`, `anon`, `authenticated` ou `service_role`, ou se o `painel_leitor` puder executar alguma função de `bruto` ou `normalizado`.

Assinaturas, com os parâmetros que vêm depois de `p_credencial`. As colunas de retorno são definidas com cada função, dentro destas regras.

| Função | Parâmetros depois de `p_credencial` | Retorno | Requisito |
|---|---|---|---|
| `resolver_acesso` | — | `TABLE (escopo text, empresa_id uuid)`; zero linhas se inválida | RF-45, RF-46, RF-47 |
| `listar_empresas` | — | empresas visíveis à credencial | RF-47 |
| `obter_desempenho` | `p_empresa_id uuid, p_nivel text, p_entidade_id uuid, p_inicio date, p_fim date, p_granularidade text` | uma linha por entidade × período × moeda × métrica, da entidade em foco e de cada filha, com as aditivas somadas e as derivadas recalculadas das somas | RF-23, RF-25, RF-32, RF-33, RF-34 |
| `obter_alcance` | `p_empresa_id uuid, p_nivel text, p_entidade_id uuid, p_inicio date, p_fim date` | alcance e frequência, ou o motivo de indisponibilidade | §3.3 do `docs/REQUIREMENTS.md`, ADR-0006 |
| `obter_quebra` | `p_empresa_id uuid, p_nivel text, p_entidade_id uuid, p_tipo_quebra text, p_inicio date, p_fim date` | uma linha por categoria | RF-36 |
| `listar_metricas` | — | `TABLE (codigo text, rotulo text, explicacao text, unidade text)`: o catálogo de métricas, em ordem de rótulo. Cada coluna entra com a visão que a exibe | RF-30 |
| `listar_resultados` | `p_empresa_id uuid, p_inicio date, p_fim date` | `TABLE (moeda text, metrica text)`: uma linha por moeda e tipo de resultado das campanhas com entrega no intervalo, em ordem de moeda e de código (ADR-0013) | §3.1 do `docs/REQUIREMENTS.md`, RF-34 |
| `obter_situacao_carga` | `p_empresa_id uuid` | instante da última carga bem-sucedida | RF-28 |
| `obter_trilha` | `p_empresa_id uuid, p_nivel text, p_entidade_id uuid` | `TABLE (nivel text, entidade_id uuid, nome text, fusos_horarios text[])`: uma linha por nível, do geral até a entidade em foco, com o nome e os fusos das contas que o nível abrange; zero linhas se a entidade não é da empresa ou do nível pedido | RF-23, RF-26 |
| `listar_entidades` | `p_empresa_id uuid, p_nivel text, p_entidade_pai_id uuid` | `TABLE (nivel text, entidade_id uuid, nome text, objetivo text, status text, metrica_resultado text, metrica_kpi text)`: contas, campanhas ou anúncios filhos, em ordem de nome, com ou sem entrega. As quatro últimas colunas valem só para as campanhas e ficam nulas nas outras filhas até a visão que as exibir: objetivo e status em rótulo de negócio, e resultado principal e KPI pelo código do catálogo, com a sobrescrita aplicada (ADR-0014) | RF-23, RF-31, RF-37 |
| `obter_anuncio` | `p_empresa_id uuid, p_anuncio_id uuid` | dados da prévia: caminho da miniatura, links da publicação, nome da página, título, texto e chamada para ação | RF-38, RF-39, RF-40 |
| `listar_metas` | `p_empresa_id uuid, p_inicio date, p_fim date` | metas vigentes no intervalo, com valor medido e status | RF-42 |

- `p_nivel` aceita `geral`, `conta`, `campanha` e `anuncio`; `p_entidade_id` é nulo só em `geral`.
- `p_granularidade` aceita `dia`, `semana`, `mes`, `ano` e `periodo` (total do intervalo).
- Valor fora do domínio levanta `22023` (`invalid_parameter_value`).
- `obter_desempenho` devolve `TABLE (nivel text, entidade_id uuid, inicio_periodo date, fim_periodo date, moeda text, metrica text, valor numeric)`:
  - **Entidades**: as linhas da entidade em foco repetem `p_nivel` e `p_entidade_id`, e as demais são das filhas: as contas no geral, as campanhas na conta e os anúncios na campanha. O anúncio não tem filhas. Assim, uma chamada traz o total da entidade e a lista do nível abaixo, e o total de uma filha é igual ao da chamada com foco nela (RF-32).
  - **Métricas**: uma linha por métrica, pelo código do catálogo. O formato longo deixa o catálogo escolher as métricas aditivas e as derivadas de operandos aditivos (§2), e uma métrica nova não muda a assinatura. Alcance, frequência e as derivadas que dependem deles ficam com `obter_alcance` (ADR-0006).
  - **Períodos**: o dia, a semana ISO, o mês, o ano ou o intervalo inteiro, pelo `calendario` e cortados no intervalo pedido. A entidade em foco tem todo período do intervalo, em cada moeda com dados nele: sem entrega, as aditivas são zero e as razões ficam nulas. Assim a série tem um ponto por período (RF-25) sem que o painel leia o calendário. As filhas aparecem só nos períodos com dados, e o intervalo sem nenhum dado devolve zero linhas.
  - **Moeda**: no geral, a empresa tem um total por moeda, inclusive nas métricas sem dinheiro, para que cada razão use só contas da mesma moeda (RF-34).
  - **Agregação**: fica numa função interna, `normalizado.agregar_desempenho`, sem credencial e sem grant, chamada depois da validação e da resolução da credencial.
  - **Desempenho**: a função interna é planejada a cada chamada com os valores dos parâmetros (`plan_cache_mode = force_custom_plan`), com `work_mem` próprio e com `enable_nestloop` e `enable_mergejoin` desligados nela, para que o planejador prefira as junções por hash. O `enable_nestloop` desligado só desencoraja o laço aninhado, que continua nas junções sem condição, como a do recorte com o catálogo. Com a massa fictícia da empresa de referência (`supabase/scripts/`), o plano genérico e as estimativas sobre as CTEs levavam os recortes longos acima do RNF-06, e esses atributos bastaram, sem índice nem view materializada (Consequências).

As funções da área do operador exigem escopo `operador` e seguem o mesmo padrão:
- empresas e contas (RF-43, RF-48, RF-22):
  - `cadastrar_empresa(p_credencial, p_nome text, p_ids_contas text[]) RETURNS uuid`;
  - `cadastrar_conta(p_credencial, p_empresa_id, p_id_meta text) RETURNS uuid`;
  - `desativar_empresa(p_credencial, p_empresa_id)`;
- links (RF-44, RF-45):
  - `gerar_credencial_empresa(p_credencial, p_empresa_id) RETURNS text`, que devolve o token uma única vez;
  - `listar_credenciais(p_credencial, p_empresa_id)`, sem tokens nem hashes;
  - `revogar_credencial(p_credencial, p_credencial_id uuid)`;
- metas (RF-41):
  - `registrar_meta(p_credencial, p_empresa_id, p_campanha_id uuid, p_metrica text, p_valor_alvo numeric, p_sentido text, p_moeda text, p_inicio_vigencia date, p_fim_vigencia date) RETURNS uuid`;
  - `alterar_meta(p_credencial, p_empresa_id, p_meta_id uuid, p_valor_alvo numeric, p_fim_vigencia date)`;
  - `encerrar_meta(p_credencial, p_empresa_id, p_meta_id uuid)`;
- sobrescritas (RF-49):
  - `registrar_sobrescrita(p_credencial, p_empresa_id, p_campanha_id uuid, p_metrica_resultado text, p_metrica_kpi text)`;
  - `remover_sobrescrita(p_credencial, p_empresa_id, p_campanha_id uuid)`;
- execuções e cotas:
  - `listar_execucoes(p_credencial, p_empresa_id, p_inicio timestamptz)`, para RF-51, com `p_empresa_id` nulo para todas as empresas;
  - `listar_cargas_paradas(p_credencial)`, para RNF-13;
  - `obter_uso_cotas(p_credencial)`, para RF-52;
- `excluir_empresa(p_credencial, p_empresa_id, p_confirmacao text)`, para RNF-25. A função apaga as linhas do banco, e as miniaturas no Storage são apagadas pelo servidor do painel pela API do Storage, porque uma função SQL não remove objetos do Storage.

A primeira credencial de operador é criada por uma função de `normalizado` executável só pelo `postgres`, pelo runbook.

As credenciais seguem estas regras:
- **Geração**: o token nasce no banco, numa só função interna, `normalizado.gerar_credencial(p_escopo text, p_empresa_id uuid) RETURNS text`.
  - A função sorteia 32 bytes com o `gen_random_bytes` do pgcrypto, codifica em base64url sem preenchimento (43 caracteres), grava `sha256(convert_to(token, 'UTF8'))` e devolve o token. O PostgreSQL 17 não tem `base64url` no `encode`, então ela troca o `+` e a `/` do base64 por `-` e `_` e retira o `=`.
  - É `SECURITY INVOKER` e executável só pelo `postgres`. A `gerar_credencial_empresa` a chama depois de exigir o operador, e o runbook cria a primeira credencial do operador com `SELECT normalizado.gerar_credencial('operador', NULL)`.
  - O link de empresa exige empresa ativa, e a função levanta o `P0002` (`no_data_found`) para empresa inexistente, inativa ou nula. Um link de empresa inativa nunca abriria o painel (RF-44, RF-48) e passaria a valer sozinho se a empresa voltasse a ser ativa.
  - Como o token nasce no banco, ele não aparece no texto de nenhum comando de geração, e assim não vai ao histórico do `psql` nem ao log do banco.
  - Cada geração cria uma credencial nova, sem revogar as anteriores da empresa.
- **Exigência do operador**: fica em `normalizado.exigir_operador(p_credencial text)`, também interna, que levanta o `42501` com a mensagem `acesso negado` quando a credencial não resolve para o escopo `operador`.
- **Revogação**: a `revogar_credencial` grava `revogado_em` e mantém a linha, e a resolução deixa de achar a credencial já na chamada seguinte (RF-45).
  - Revogar de novo mantém a data da primeira revogação.
  - A data é o `now()` da transação que revoga ou, se a credencial foi criada depois do início dela, o `criado_em`. Assim, o `CHECK (revogado_em >= criado_em)` nunca recusa a revogação, o que levaria a linha, com o hash, à mensagem de erro e ao log.
  - Um ID que não é de nenhuma credencial levanta o `P0002` (`no_data_found`), para que um engano não passe por revogação feita.
  - O operador também revoga credenciais de operador, inclusive a própria.

A resolução do resultado principal de cada campanha, com a precedência do ADR-0007, é uma função interna, `normalizado.resolver_resultado_campanha(p_empresa_id uuid)`, sem credencial. As funções de `analitico` a usam, e a `etl_carga` a executa para os avisos do RF-15 e a comparação do RF-16, para que a regra exista num só lugar. Ela é `SECURITY INVOKER` e devolve uma linha por campanha da empresa, com `campanha_id`; `resultado_objetivo_id`, a regra do catálogo, de onde vêm o nome do objetivo e as métricas de apoio mesmo com sobrescrita; `metrica_resultado` e `metrica_kpi`, já com a sobrescrita aplicada; e `sobrescrita`, que diz se o par veio dela. A campanha "Não classificado" é a que resolve para a regra sem objetivo. Ela percorre todas as campanhas da empresa, inclusive as antigas, e por isso depende de dois índices, `anuncio (empresa_id, conjunto_anuncio_id)` e `conjunto_anuncio (empresa_id, campanha_id)`: sem eles, o tempo cresce com conjuntos × anúncios, e não com o período exibido.

### 5. Carga e substituição da janela

- **Ordem**: a extração faz todo o I/O de rede fora de transação (`CLAUDE.md` §3). Depois abre uma transação por empresa ou por fatia, com estes passos:
  1. adquire o `pg_try_advisory_xact_lock`, com chave de 64 bits derivada do UUID da empresa (RF-19), o que põe em série as execuções horária, diária e histórica da mesma empresa;
  2. grava as respostas em `bruto`;
  3. transforma, com as funções puras;
  4. carrega `normalizado`.

  A transformação continua pura e só roda em memória entre as gravações. Assim, a resposta bruta é gravada antes de ser transformada (RF-09), e uma falha em qualquer passo não deixa linha nenhuma da execução, nem bruta (RF-18; `CLAUDE.md` §9). Quando a falha é da transformação, a resposta se recupera pela reextração.

  Depois do passo 4, ainda na transação, a execução conta as respostas brutas do seu `execucao_id`. Se a carga gravou linhas em `normalizado` sem nenhuma resposta bruta, a execução falha e a carga é desfeita, para que nenhuma linha fique sem rastro até a API (RF-09). A contagem entra nas linhas por tabela do registro de fim, como `resposta_api`.
- **Entidades em toda execução**: um fato só entra se o anúncio e a campanha a que aponta existem, pela FK. Por isso toda execução, horária, diária ou histórica, extrai e carrega primeiro, na mesma transação, as entidades e os criativos referenciados pelos insights que vai gravar e ainda ausentes do banco. A extração inclui os status `DELETED` e `ARCHIVED`, que aparecem na carga histórica. As arestas de entidades da Meta só devolvem os `ARCHIVED` com filtro por `effective_status` (R-38). A execução diária continua atualizando o cadastro completo (ADR-0005).
- **Entidades**: upsert por `id_meta`, com `ON CONFLICT (id_meta) DO UPDATE ... WHERE <tabela>.empresa_id = EXCLUDED.empresa_id`. Se o `id_meta` já pertence a outra empresa, nenhuma linha é atualizada. A ETL confere a contagem de linhas afetadas e falha a empresa, em vez de mover a entidade de dono em silêncio.
- **Fatos**: na mesma transação, a ETL apaga o escopo e insere o conjunto completo devolvido pela API. O escopo é sempre conta × intervalo de datas, cada conta com o próprio fuso. O `DELETE` chega à conta pela junção com anúncio, conjunto e campanha, porque os fatos não guardam a conta. As ações saem junto com o fato pai, pelo `ON DELETE CASCADE`.

  | Execução | Escopo substituído |
  |---|---|
  | Horária | ontem e hoje de cada conta: métricas, ações e quebras |
  | Diária | os 28 dias anteriores de cada conta (RF-05): métricas, ações e quebras; em `alcance_periodo`, as semanas, os meses e o ano que tocam a janela (ADR-0006) |
  | Histórica | o mês da fatia, para a conta da fatia, cortado no limite de 37 meses (R-19) e em ontem: métricas, ações e quebras; em `alcance_periodo`, os períodos que começam na fatia: as semanas ISO, o mês, quando a fatia começa no dia 1, e o ano, quando começa em 1º de janeiro |

- **Rotina diária**: é uma execução por empresa, com uma só transação para todas as contas dela (RF-18). Uma falha em qualquer etapa desfaz a empresa inteira, e a execução seguinte recarrega a janela.
  - A extração de cada conta começa pelo cadastro. O dia lido nele, no fuso da conta, dá a janela: os 28 dias anteriores, sem hoje, que é da execução horária. Assim, cada conta tem a própria janela, mesmo que as contas da empresa estejam em fusos diferentes, e a conta sem fuso já a tem na primeira execução.
  - O cadastro lido ainda não foi carregado quando as outras consultas terminam. Por isso, a leitura pelo ID deixa de fora, além do que está no banco, o que o cadastro da mesma execução trouxe. Sem isso, a primeira execução de uma conta leria pelo ID cada anúncio com entrega no ano.
  - A carga de cada conta segue a ordem cadastro, insights, quebras e alcance. As entidades vêm antes dos fatos, pela FK, e os insights antes das quebras (ADR-0011).
- **Carga histórica**: é uma execução por empresa, com uma transação por fatia (RF-18). Roda depois da rotina diária, no mesmo workflow, e por disparo manual (ADR-0005).
  - A conta ativa sem nenhuma fatia em `fatia_historica` é nova, seja qual for a data do cadastro (RF-22). No início, a execução planeja as fatias de todas as contas novas da empresa: uma pendente por mês do calendário, do limite de 37 meses até ontem, no fuso da conta. A conta sem fuso, que ainda não teve a primeira extração, espera a execução seguinte.
  - O limite é hoje menos 37 meses, no mesmo dia do mês (R-19). Não verificamos em que fuso a Meta conta o hoje, e às 06:43 UTC uma conta de Los Angeles ainda está na véspera. Também não verificamos o que ela faz com o dia que não existe no mês do limite. Por isso vale o mais tardio entre o limite de hoje e o de amanhã, com o dia contado a partir do dia 1 do mês do limite, o que leva o dia inexistente para o mês seguinte. O `since` nunca fica antes do aceito, ao custo de até três dias do mês mais antigo.
  - As fatias não concluídas de cada conta são carregadas em ordem, da mais antiga para a mais recente. A extração corta o mês da fatia no limite e em ontem calculados na hora, porque a retomada pode vir dias depois do planejamento, e conclui sem dados o mês que saiu inteiro do limite. A execução não lê o cadastro, e a leitura pelo ID inclui tudo o que o banco não tem.
  - A fatia que falha é marcada como `falha`, numa transação própria, e encerra só a conta dela, para que um erro que se repete a cada execução não segure as outras contas. A execução segue para a próxima conta e, no fim, fica como falha, com o primeiro erro e as linhas das fatias já confirmadas no registro de fim. A fatia que não obtém o lock fica pendente, e a execução termina como `ignorada` (RF-19).
  - Nenhuma fatia nova começa depois de 3 h de execução, e a execução seguinte continua da primeira não concluída (RNF-07). Se o Actions cancelar o job no limite de tempo, a interrupção fecha o registro como falha antes de sair, e a fatia em andamento é desfeita e fica pendente. Uma empresa sem fatia a carregar não gera execução.
  - O alcance de uma fatia pode ir além dela, na semana que termina no mês seguinte e no ano da fatia de janeiro. A data de referência das respostas dele em `bruto` é o último dia consultado, para que a retenção não as apague antes do tempo.
- **Idempotência**: o "estado idêntico" do RF-17 compara as colunas de negócio, que são o grão e as medidas. Ficam de fora `execucao_id`, as colunas `*_em` e as chaves substitutas (`quebra_diaria_campanha.id`), que mudam a cada execução por definição.
- **Fatia histórica**: a marca `concluida` em `fatia_historica` é gravada na mesma transação dos dados da fatia. Uma fatia interrompida nunca aparece como concluída, e a retomada começa pela primeira fatia não concluída (RF-07).
- **Controle**:
  - O registro de início e o de fim de `execucao_carga` usam transações próprias, antes e depois da carga. O rollback da carga não apaga o registro, e a falha fica gravada (RF-20).
  - `contagem_linhas_execucao` é gravada com o registro de fim.
  - `aviso_execucao` entra na transação da carga, porque o aviso de uma carga desfeita não vale.
- **Retenção**: a execução diária apaga de `bruto.resposta_api` as linhas com `data_referencia` anterior a hoje menos `RETENCAO_BRUTO_DIAS` (RF-21).
  - Roda por empresa, na transação da carga diária dela, com o lock, antes da carga: uma resposta gravada pela própria execução nunca sai nela. Uma falha na retenção desfaz também a carga, e a execução fica como falha.
  - Uma execução diária que falha ou fica `ignorada` não apaga nada, e o bruto da empresa espera a próxima diária bem-sucedida. A falha repetida já aparece como carga parada (RNF-13).
  - O hoje é o do fuso de cada conta, o mesmo da `data_referencia`. A conta sem fuso, que ainda não teve a primeira extração, usa o dia em UTC.
  - A data de gravação não conta: a resposta da carga histórica, com a data de um mês antigo, sai na execução diária seguinte.
  - O log registra só quantas linhas saíram, na etapa `reter` (RNF-17). As linhas apagadas não entram em `contagem_linhas_execucao`, cuja linha `resposta_api` conta as respostas gravadas pela execução.
  - A empresa inativa não entra nas execuções (RF-48), e o bruto dela fica até ela voltar a ser carregada ou ser excluída (RNF-25).
- **Leitura concorrente**: o painel lê pelo MVCC do Postgres e vê o estado anterior ou o posterior à transação da carga, nunca uma carga parcial (RNF-09).

### 6. Revisão de dados pessoais (RNF-24)

Revisamos todas as colunas da §2 desta decisão em 03/11/2026, buscando nome, e-mail, telefone ou identificador de pessoa física, tanto do público dos anúncios quanto de qualquer outra pessoa.

| Onde | O que guarda | Avaliação |
|---|---|---|
| `nome` em empresa, conta, página, campanha, conjunto e anúncio | Nomes dados pelo anunciante às próprias entidades | Dado do cliente, não do público. Quando o anunciante é pessoa física, como um profissional liberal, o nome da página pode identificá-lo; isso fica coberto pela exclusão a pedido (RNF-25) |
| `titulo`, `texto` e links do criativo | Peça publicitária publicada pelo anunciante | Conteúdo público do anúncio, sem coluna própria para dado pessoal. Um texto livre pode trazer o contato do próprio anunciante; ele sai com a exclusão da empresa (RNF-25) |
| `caminho_miniatura` e a imagem no Storage | Cópia da miniatura do anúncio (RF-38) | A imagem pode mostrar pessoas, como modelos ou o próprio anunciante. É a peça que o anunciante publicou, e a cópia existe só para exibi-la a quem a empresa autorizou. A exclusão a pedido apaga também as imagens no Storage |
| Quebras por idade, gênero e região | Agregados da Meta por categoria | Nenhum indivíduo. A Meta só devolve totais por faixa |
| `tipo_acao`, `quantidade`, `valor` | Contagens e valores agregados por anúncio e dia | Nenhum lead individual. A ETL não chama endpoints de leads, o que um teste da lista de endpoints verifica (RNF-24) |
| `credencial_acesso` | Hash, escopo e datas | Decidimos não guardar quem recebeu o link (nome ou e-mail), para não criar dado pessoal |
| `execucao_carga.erro`, `aviso_execucao` | Mensagem de erro e tipo de aviso | Mensagens técnicas da API e do banco; o aviso aponta para a campanha pelo `id` interno |
| `bruto.resposta_api` | Respostas dos endpoints de entidades e de insights | Só os campos que a ETL pede, sem endpoints de leads, por no máximo 35 dias (ADR-0005) |

Resultado: nenhuma coluna tem nome, e-mail, telefone ou identificador de pessoa física como conteúdo previsto, o que atende ao RNF-24. Os pontos onde um dado pessoal pode aparecer são os listados acima: nomes e peças do próprio anunciante, quando ele é pessoa física, e imagens dos anúncios. Todos saem com a exclusão da empresa (RNF-25). O banco também não guarda IP, agente de navegador ou registro de acesso de quem abre o painel.

## Consequências

- **Isolamento**: o banco impõe o isolamento entre empresas em três camadas, cada uma testável por pgTAP sem depender do painel nem da ETL:
  - a FK composta, que impede referência cruzada;
  - os grants e o RLS, que impedem acesso direto;
  - as funções de `analitico`, que só devolvem dados da empresa da credencial.
- **Exceções à 3FN**: a repetição de `empresa_id` e o `bruto` são as únicas, ambas registradas acima. A agregação por conta faz três junções a partir do anúncio. Se o RNF-06 não for atendido com a empresa de referência, a saída é índice ou view materializada em `analitico`, a única camada onde a desnormalização é permitida.
- **Volume**: as ações das quebras acrescentam no máximo uma linha por categoria × dia, a do resultado principal (ADR-0011). A medição da Q-09 mostra se a estimativa do `docs/REQUIREMENTS.md` §4.2 precisa subir.
- **Calendário**: termina em 31/12/2035. A FK das datas faz a carga falhar de forma visível antes que algum dado se perca, e a extensão do intervalo é uma migration nova.
- **Domínios da API**:
  - **Status**: um valor novo, fora do domínio fechado de R-35, faz falhar a carga das empresas afetadas até uma migration ampliar o `CHECK`.
  - **Domínios abertos**: valores novos entram sem falha e aparecem como "Não identificado" até ganharem rótulo.
- **`pg_net`**: removido. Se um dia o usarmos, a decisão precisa rever o que ele expõe aos nossos papéis (R-30).
- **Senhas fora do repositório**: são definidas e rotacionadas à mão, pelo runbook (RF-53). Até a senha ser definida, um papel novo existe mas não conecta.
- **Dono dos objetos**: o `supabase db push` aplica as migrations com o `postgres` como papel efetivo, com ou sem a senha do banco (R-36). Toda tabela e toda função dos nossos esquemas ficam com ele como dono, e um teste pgTAP confere isso. Se uma versão futura do CLI mudar esse comportamento, o teste não pega, porque roda no banco local; a R-36 registra a versão verificada.
- **Login**: quando o login entrar (gatilhos do ADR-0004), as funções de `analitico` passam a resolver o escopo por `auth.uid()` e pelo vínculo usuário–empresa, e `credencial_acesso` dá lugar a esse vínculo. Nenhuma tabela de fato ou de entidade muda, porque todas já têm `empresa_id`.

## Referências

Consultadas em 03/11/2026. As que sustentam as restrições R-29 a R-36 também estão no `docs/REQUIREMENTS.md` §4.1 e §9.

Supabase:
- https://supabase.com/docs/guides/api/using-custom-schemas
- https://supabase.com/docs/guides/api/securing-your-api
- https://github.com/orgs/supabase/discussions/45329
- https://supabase.com/docs/guides/database/postgres/row-level-security
- https://supabase.com/docs/guides/database/postgres/roles
- https://supabase.com/docs/guides/database/functions
- https://supabase.com/docs/guides/database/connecting-to-postgres
- https://supabase.com/kb/troubleshooting/custom-role-inherits-privileges-that-were-not-explicitly-granted
- https://supabase.com/kb/troubleshooting/provisioning-credentials-without-log-exposure
- https://supabase.com/docs/reference/cli/supabase-test-db
- https://supabase.com/docs/reference/cli/supabase-db-push
- https://supabase.com/docs/guides/database/extensions/pg_net
- https://supabase.com/kb/troubleshooting/database-roles-can-read-request-headers-queued-by-pg_net

Código-fonte do Supabase CLI v2.114.0:
- https://github.com/supabase/cli/blob/v2.114.0/apps/cli-go/internal/utils/connect.go
- https://github.com/supabase/cli/blob/v2.114.0/apps/cli-go/internal/utils/flags/db_url.go
- https://github.com/supabase/cli/blob/v2.114.0/apps/cli-go/pkg/migration/apply.go

PostgreSQL 17:
- https://www.postgresql.org/docs/17/sql-createrole.html
- https://www.postgresql.org/docs/17/sql-alterrole.html
- https://www.postgresql.org/docs/17/app-psql.html
- https://www.postgresql.org/docs/17/ddl-rowsecurity.html
- https://www.postgresql.org/docs/17/ddl-priv.html
- https://www.postgresql.org/docs/17/sql-grant.html
- https://www.postgresql.org/docs/17/runtime-config-client.html
- https://www.postgresql.org/docs/17/sql-createfunction.html
- https://www.postgresql.org/docs/17/sql-createtable.html
- https://www.postgresql.org/docs/17/functions-binarystring.html
- https://www.postgresql.org/docs/17/view-pg-timezone-names.html
- https://www.postgresql.org/docs/17/datetime-posix-timezone-specs.html

Meta:
- https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/
- https://developers.facebook.com/docs/marketing-api/reference/ad-campaign/
- https://developers.facebook.com/docs/marketing-api/reference/adgroup/
- https://developers.facebook.com/docs/marketing-api/reference/ad-account/
- https://developers.facebook.com/docs/marketing-api/reference/ad-creative/
- https://developers.facebook.com/docs/graph-api/reference/page/
- https://developers.facebook.com/documentation/meta-pixel/implementation/conversion-tracking

Verificação local, em 03/11/2026, no Supabase local (imagem `supabase/postgres:17.6.1.158`, Supabase CLI 2.114.0), dentro de transações desfeitas com `ROLLBACK`:
- atributos de `postgres` e `service_role`;
- ausência de privilégios padrão num esquema novo;
- RLS sem política negando um papel próprio e política `TO` liberando;
- `INSERT` em coluna identity sem `USAGE` na sequência;
- `EXECUTE` padrão de `PUBLIC` e efeito do `REVOKE`;
- leitura via `SECURITY DEFINER` sem `SELECT` na tabela;
- `SET ROLE` negado ao criador e liberado por `WITH INHERIT FALSE, SET TRUE`;
- leitura da fila do `pg_net` por papel próprio e remoção da extensão pelo `postgres`, com o esquema `net` junto;
- `SET SESSION ROLE` mantido depois de `RESET ALL`;
- `UNIQUE NULLS NOT DISTINCT`;
- `sha256`;
- `AT TIME ZONE` aceitando `XYZ+3`, que não está em `pg_timezone_names`.

No mesmo banco, o `pg_dump` de `conta_anuncio` mostrou o `CHECK` dentro do `CREATE TABLE`, antes do `COPY`, e o trigger depois dele.
