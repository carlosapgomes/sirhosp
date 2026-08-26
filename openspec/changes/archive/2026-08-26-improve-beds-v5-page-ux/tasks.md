## 1. IBPU-S1 — Resumo da situação real e ponte compacta

- [x] 1.1 Ler `slice-prompts/SLICE-IBPU-S1.md`, registrar `BASE_REF`, árvore
  limpa e baseline oficial em container antes de editar.
- [x] 1.2 Criar testes RED para a seção `Situação real do hospital`
  (posição, total na taxa + fora da taxa, estados operacionais, incompleta
  omitida quando zero, privacidade) e para a ponte v5 ao fim da página,
  recolhida por padrão.
- [x] 1.3 Implementar `_V5RealTotals` a partir de
  `physical_reconciliation_json` persistido, expor como `physical.v5_real` e
  renderizar a nova seção somente na branch v5.
- [x] 1.4 Mover a seção `Como os pacientes foram contados` para após a lista
  de setores, em collapsible recolhido por padrão, preservando conteúdo
  agregado e branches v1–v4.
- [x] 1.5 Executar gates oficiais, gerar
  `/tmp/sirhosp-slice-IBPU-S1-report.md`, marcar somente 1.x, commit/push e
  parar.

## 2. IBPU-S2 — Métricas oficiais nos cabeçalhos dos cards

- [x] 2.1 Ler `slice-prompts/SLICE-IBPU-S2.md`, confirmar S1 completo e
  registrar novo baseline limpo.
- [x] 2.2 Criar testes RED dos cabeçalhos v5: setor comum, acima da
  capacidade textual, unrated, pendente, sem capacidade cadastrada, unmapped,
  `0 pacientes` explícito e 3A por partição sem total combinado.
- [x] 2.3 Criar testes RED da limpeza: sem badge de contagem de códigos no
  cabeçalho v5, sem badges por paciente de política de contagem e exceções
  factuais mantidas.
- [x] 2.4 Implementar `header_metrics` derivado dos valores persistidos de
  `official_rows`, renderizar badges no cabeçalho, remover código morto de
  política por paciente e preservar corpo e regressão v1–v4.
- [x] 2.5 Executar gates oficiais, gerar
  `/tmp/sirhosp-slice-IBPU-S2-report.md`, marcar somente 2.x, commit/push e
  parar.

## 3. IBPU-S3 — Fim do N+1 com orçamento de queries

- [x] 3.1 Ler `slice-prompts/SLICE-IBPU-S3.md`, confirmar S2 completo e
  registrar novo baseline limpo com a contagem de queries atual documentada.
- [x] 3.2 Criar teste RED de orçamento: renderização autenticada com catálogo
  de 4 grupos versus 12 grupos deve diferir em no máximo 8 queries.
- [x] 3.3 Corrigir o N+1 com prefetch de `catalog__groups__memberships` no
  caminho exact-run, sem mudança de comportamento e sem tocar cálculo
  persistido.
- [x] 3.4 Executar gates oficiais, gerar
  `/tmp/sirhosp-slice-IBPU-S3-report.md`, marcar somente 3.x, commit/push e
  parar.

## 4. IBPU-S4 — Release RC12 e deploy de produção

- [x] 4.1 Ler `slice-prompts/SLICE-IBPU-S4.md` e auditar S1–S3, delta spec,
  relatórios e ausência de migrations/catálogos novos no intervalo da RC.
- [x] 4.2 Executar check, unit, integration, lint, typecheck, quality-gate,
  OpenSpec strict e Markdown lint; qualquer falha bloqueia release.
- [x] 4.3 Criar por TDD o runbook `v0.1.0-rc.12` e o índice: escopo somente
  UI, sem migration, sem catálogo, preflight, drenagem, backup, deploy,
  verificação por agregados e rollback trivial.
- [x] 4.4 Publicar tag/release/imagem imutáveis pelo workflow oficial e
  implantar em produção conforme runbook, mantendo RC11 como rollback.
- [x] 4.5 Confirmar produção saudável (health, 302, dez workers, `/beds` v5
  com novos cabeçalhos por agregados, zero PHI), gerar
  `/tmp/sirhosp-slice-IBPU-S4-report.md`, marcar somente 4.x e parar.
