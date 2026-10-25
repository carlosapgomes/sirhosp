# Tasks

## 1. Map somente leitura da feature de pendências

- [x] 1.1 Criar `.pi/skills/verify-sirhosp/features/pending-items.md` no formato de contrato do índice (4 seções H2, sub-features, jornada de leitor, status `future`), atualizar o índice em `features/README.md` e a disciplina de rotas em `SKILL.md` (leituras novas permitidas; `export.xlsx` e superfícies de escrita proibidas mesmo como GET). Verificação: `./scripts/markdown-lint.sh` sem erros e conferência mecânica de que todo handle (`nav-pendencias`, `view-patients`/`view-items`, `indicators-*`, `filters-apply`, `pending-history-*`) e toda rota citada existem no código (templates/urls) no momento da escrita.

## Sequência e autoridade

Task única; executor e revisão conforme `AGENTS.md`. Demonstrar o mapa num round MCP real é operação futura do operador (janela dev + dataset fictício + workers parados), não parte desta change.
