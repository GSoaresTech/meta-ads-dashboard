# ADR-0002: Modelo multiempresa

- Status: Aceito
- Data: 29/10/2026

## Contexto

O sistema nasce sem cliente e precisa atender várias empresas sem mudança de código. Uma única rotina de extração usa as credenciais do App da Meta na BM do operador (ADR-0003). O painel começa sem login (ADR-0004), mas poderá ter.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| **(a) Uma implantação para todas as empresas**: chave da empresa em toda tabela de negócio, com isolamento no banco | Um projeto Supabase, um deploy e uma rotina de extração. Incluir a chave desde o início custa pouco; incluí-la depois exigiria migrar todas as tabelas | Um erro de isolamento exporia dados entre empresas, o que exige teste de isolamento obrigatório |
| (b) Uma implantação por empresa (projeto Supabase e deploy próprios) | Isolamento físico | Multiplica por empresa os projetos Supabase (cada um com custo próprio), os deploys, as migrations e os secrets |

## Decisão

Adotar a opção (a).

- Toda tabela de negócio tem `empresa_id NOT NULL` com FK para `empresa`.
- O isolamento é imposto no banco: o RLS nega o acesso pela API REST, e o painel só chama funções de `analitico` que resolvem a credencial para uma empresa ou para o operador (ADR-0004).
- A chave interna da empresa é um UUID, que é o único identificador de empresa permitido em logs (CLAUDE.md §8).
- Quando o login entrar, um vínculo N:N usuário–empresa substitui a credencial por link, e as políticas RLS passam a usar `auth.uid()`. Como `empresa_id` já está em todas as tabelas, nenhuma delas precisa ser migrada.

## Consequências

- Cada função ou view de `analitico` precisa de teste de isolamento (RNF-14).
- Cadastrar uma empresa não altera nenhum arquivo do repositório (RNF-22). Basta a empresa compartilhar a conta de anúncios com a BM do operador e o operador atribuí-la ao System User e cadastrá-la na área do operador.
- Todas as empresas dividem o mesmo banco; o volume por empresa está estimado no `docs/REQUIREMENTS.md` §4.2.
