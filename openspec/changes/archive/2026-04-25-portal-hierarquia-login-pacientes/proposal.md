# Change Proposal: portal-hierarquia-login-pacientes

## Why

O produto já extrai e persiste dados clínicos, mas a experiência atual de navegação ainda está orientada a endpoints técnicos.

Fluxo desejado de uso (confirmado):

1. landing page pública com botão de login;
2. após login, cair direto em lista de pacientes;
3. clicar em paciente para ver admissões;
4. a partir daí, navegar para timeline e disparar nova extração por período;
5. busca permanece apenas em endpoint JSON (sem nova UI de busca neste ciclo).

Sem essa hierarquia mínima de páginas, há fricção operacional para uso diário e validação funcional por usuários não técnicos.

## What Changes

- Introduzir fluxo hierárquico simples de navegação autenticada.
- Adicionar lista de pacientes com filtro por nome e registro (patient_source_key).
- Redirecionar pós-login para a lista de pacientes.
- Expor ações contextuais de negócio nas telas de admissões/timeline:
  - nova extração;
  - link para busca JSON já existente.
- Manter busca apenas em JSON (`/search/clinical-events/`), sem criar tela HTML de busca.

## Non-Goals

- Não construir dashboard analítico.
- Não introduzir SPA, DRF ou arquitetura nova.
- Não alterar regras clínicas de ingestão.
- Não criar UI dedicada para busca textual neste change.
- Não mexer em Playwright selectors/extração além do estritamente necessário para navegação.

## Capabilities

### Added Capabilities

- `services-portal-navigation`: fluxo web autenticado com hierarquia landing -> login -> pacientes -> admissões -> timeline, com ações contextuais de operação.

## Impact

- Melhora forte de usabilidade sem overengineering.
- Reduz dependência de conhecimento técnico de endpoints.
- Prepara base para incremento incremental de UX mantendo monólito Django.
