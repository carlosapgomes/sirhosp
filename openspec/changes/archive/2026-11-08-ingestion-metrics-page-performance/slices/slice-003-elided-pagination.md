# Slice 003 — Paginação elidida sem overflow

- Slice ID: S3
- Change: `2026-11-08-ingestion-metrics-page-performance`
- Task: S3 em `tasks.md`
- Depende de: S2 aceito (fixtures com 150+ batches só são baratas com o
  histórico leve).

## Objective

As paginações do histórico e do detalhe elidem ranges longos
(primeira/última + janela + `…`) e nunca transbordam a viewport.

## Read first

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/2026-11-08-ingestion-metrics-page-performance/design.md`
  — D5
- `openspec/changes/2026-11-08-ingestion-metrics-page-performance/specs/ingestion-run-metrics-portal/spec.md`
  — "Long pagination ranges are elided"
- `apps/services_portal/views.py` — `_get_batch_history_context`,
  bloco de detalhe em `ingestion_metrics`
- `apps/services_portal/templates/services_portal/ingestion_metrics.html`
  — os dois blocos `<nav aria-label="Navegação …">`

Follow the repository engineering policy in `AGENTS.md` and preserve
existing conventions. Prefer the smallest correct change; avoid
speculative abstraction and unrelated refactoring.

## Requirements

- R1 — Histórico com mais páginas que o limiar de elisão renderiza
  primeira/última página, janela ao redor da atual e separadores `…`
  desabilitados — sem um link por página.
- R2 — Paginação de runs do detalhe (`?batch_id=`) com muitas páginas
  elide da mesma forma.
- R3 — Com poucas páginas (sem elisão), a paginação renderiza como antes
  (todos os números, prev/next).
- R4 — Links preservam estado: `batch_page`/`run_page`, `batch_id`,
  `tab`, `periodo`, `status`, `intent`, `failure_reason` conforme cada
  modo (paridade com os links atuais).
- R5 — O `<nav>` das paginações envolve o conteúdo (`flex-wrap`, centro
  mantido) em vez de transbordar à direita.

## Expected blast radius

Provavelmente afetados:

- `apps/services_portal/views.py` — expor ranges elididos no contexto
  (`Paginator.get_elided_page_range`).
- `apps/services_portal/templates/services_portal/ingestion_metrics.html`
  — os dois blocos de paginação apenas.
- `tests/unit/test_services_portal_ingestion_metrics.py` — testes de
  elisão e preservação de querystring.

Sensíveis / fora de escopo (escalar se precisar tocar):

- Page sizes (20/50), ordenações, filtros, colunas, resto do template.
- Qualquer CSS global ou outro template com paginação.

Comportamento anterior que permanece: prev/next, nº total de páginas,
conteúdo das tabelas, filtros do detalhe.

## Failing-before plan

TDD:

1. Teste de elisão do histórico (RED antes): criar 161 batches
   finalizados (9 páginas a 20/página); GET default — afirmar que o HTML
   contém `…` e que **não** contém link para todas as páginas
   intermediárias (ex.: ausência de `batch_page=5` quando na página 1).
   Hoje renderiza todas → falha.
2. Teste de elisão do detalhe (RED antes): 1 batch com 401 runs (9
   páginas a 50/página); GET `?batch_id=` — afirmar `…` presente. Hoje
   ausente → falha.
3. Teste sem elisão (GREEN antes e depois): 2 páginas — afirmar todos os
   números presentes, sem `…`. Caracterização do comportamento limite.

## Implementation constraints

- Usar `Paginator.get_elided_page_range` com defaults do Django (sem
  tuning de janela) salvo se o default não elidir no cenário de teste —
  nesse caso registrar no report.
- Elipse (`…`, `Paginator.ELLIPSIS`) renderizada como item desabilitado
  sem link, com `aria-hidden` ou texto equivalente acessível seguindo o
  padrão do projeto.
- Não extrair componente/tag de paginação reutilizável (YAGNI — dois
  pontos de uso com querystrings diferentes).
- Não alterar lógica de página inválida/`EmptyPage` existente.

## Validation

Focused validation (worker):

```bash
uv run pytest -q tests/unit/test_services_portal_ingestion_metrics.py
```

Project-required gates: referenciar `AGENTS.md` (controller executa o
gate final).

Runtime/verification evidence: teste com 9 páginas cobre o contrato;
prova visual opcional (screenshot dev em largura desktop mostrando
paginação elidida sem scroll horizontal). Registrar no report se feita.

## Acceptance criteria

- [ ] R1 demonstrado por teste de elisão do histórico.
- [ ] R2 demonstrado por teste de elisão do detalhe.
- [ ] R3 demonstrado por teste limite sem elisão.
- [ ] R4 demonstrado: links contêm os params esperados por modo.
- [ ] R5 demonstrado: classe de wrap presente nos dois `<nav>`.
- [ ] Testes focados verdes; nenhum outro template alterado.

## Escalation conditions

Parar com `BLOCKED_NEEDS_DECISION` se descobrir: default do Django não
elide e tuning de janela vira decisão de UX não aprovada; links atuais
têm params que conflitam com a elisão; paginação quebrada em outro modo
não coberto pelo contrato; necessidade de CSS global.

## Evidence report

Produzir `/tmp/sirhosp-slice-S3-report.md` com: status, requirements →
evidence, arquivos alterados, failing-before evidence, passing-after
evidence, comandos + exit status, runtime/verification evidence (se
houver), expansão de blast radius (se houver), riscos/limitações,
decisões pendentes (se houver).

## Worker handoff

Implement only this approved slice. Treat the slice and referenced
OpenSpec artifacts as the implementation contract. Reconstruct context
from the listed files; do not rely on prior conversation. Follow the
repository engineering policy. Produce failing-before evidence,
implement the smallest correct change, run focused validation, and
produce the required evidence report. Do not update `tasks.md`, commit,
push, merge, archive, or start another slice. If a new decision is
required, stop with `BLOCKED_NEEDS_DECISION` and evidence. Otherwise
finish with `READY_FOR_REVIEW` and `REPORT_PATH=<path>`.
