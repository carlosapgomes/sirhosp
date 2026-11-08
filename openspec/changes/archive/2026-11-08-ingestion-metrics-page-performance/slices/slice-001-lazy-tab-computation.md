# Slice 001 — Lazy por aba/modo + remover contexto morto

- Slice ID: S1
- Change: `2026-11-08-ingestion-metrics-page-performance`
- Task: S1 em `tasks.md`

## Objective

A view `ingestion_metrics` calcula somente os agregados que a aba/modo
ativo renderiza, removendo as chaves mortas de contexto, sem alterar
nenhum conteúdo visível.

## Read first

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/2026-11-08-ingestion-metrics-page-performance/proposal.md`
- `openspec/changes/2026-11-08-ingestion-metrics-page-performance/design.md`
  — D1, D4
- `openspec/changes/2026-11-08-ingestion-metrics-page-performance/specs/ingestion-run-metrics-portal/spec.md`
  — "computes only what the active view renders"
- `apps/services_portal/views.py` — `ingestion_metrics`,
  `_build_filtered_queryset`, `_get_latest_batch_failure_stats`
- `apps/services_portal/templates/services_portal/ingestion_metrics.html`
  (somente leitura — provar que `runs`/`ingestion_stats` não são usados)

Follow the repository engineering policy in `AGENTS.md` and preserve
existing conventions. Prefer the smallest correct change; avoid
speculative abstraction and unrelated refactoring.

## Requirements

- R1 — Aba `runs` default (sem `batch_id`) renderiza os mesmos dados
  visíveis de antes (tabs, guidance de seleção, tabela de histórico).
- R2 — Aba `runs` default não computa o agregado de falhas finais de
  pacientes (nenhuma query contra `ingestion_finalrunfailure`, nenhum
  `build_patient_flow_findings` via `_attach_current_findings`).
- R3 — Agregação global da janela de runs (`_build_filtered_queryset`) e
  os 3 `DISTINCT` globais de opções de filtro (status/intent/falha sobre
  todos os runs finalizados) executam somente no modo detalhe
  (`show_batch_detail == True`). Fora de escopo neste slice: o
  `DISTINCT worker_label` por batch emitido pelo histórico (cai em S2).
- R4 — As chaves `runs` e `ingestion_stats` são removidas do contexto de
  `ingestion_metrics` (mortas — template não as usa).
- R5 — Aba `patients` e modo detalhe `?batch_id=` renderizam conteúdo
  idêntico ao anterior.
- R6 — Dashboard inalterado (usa `_compute_ingestion_stats` próprio).

## Expected blast radius

Provavelmente afetados:

- `apps/services_portal/views.py` — função `ingestion_metrics` apenas.
- `tests/unit/test_services_portal_ingestion_metrics.py` — novos testes
  de orçamento de queries + paridade de conteúdo.

Sensíveis / fora de escopo (escalar se precisar tocar):

- `apps/services_portal/templates/services_portal/ingestion_metrics.html`
  — nenhuma mudança neste slice.
- Dashboard, workers, retry, fechamento de batch, models, migrations.
- Colunas do histórico (slice 002), paginação (slice 003).

Comportamento anterior que permanece: todo HTML visível por aba/modo;
filtros e links das tabs; ordenação e page size do histórico.

## Failing-before plan

TDD com test seam prático (Django test client + `CaptureQueriesContext`
ou `assertNumQueries`):

1. Teste de orçamento (RED antes): GET default `tab=runs` sem batch —
   afirmar zero queries contendo `ingestion_finalrunfailure`, zero
   queries da agregação global de janela (`finished_at__gte` sobre runs)
   e zero dos 3 `DISTINCT` globais de filtro (status/intent/falha sem
   escopo de batch). Hoje todos executam → falha. Não afirmar "zero
   DISTINCT" genérico: o histórico ainda emite `DISTINCT worker_label`
   por batch até S2.
2. Teste de paridade (caracterização, GREEN antes e depois): fixtures
   com 1 batch finalizado + runs + 1 falha final; afirmar que o HTML
   default contém a linha do batch e não contém a tabela de pacientes;
   aba `patients` contém os cards e a tabela; detalhe contém runs.
   Mantém-se verde após o refactor.

## Implementation constraints

- Não alterar assinatura de `_build_filtered_queryset`,
  `_get_latest_batch_failure_stats` ou `_get_batch_history_context`;
  apenas condicionar as chamadas em `ingestion_metrics`.
- Não mover colunas nem métricas entre histórico/detalhe (slice 002).
- Não antecipar índices (slice 004) nem elisão (slice 003).
- Dropdowns continuam globais (D4) — apenas passam a ser calculados
  somente no modo detalhe.

## Validation

Focused validation (worker):

```bash
uv run pytest -q tests/unit/test_services_portal_ingestion_metrics.py
uv run pytest -q tests/integration/test_services_portal_ingestion_metrics_failures_tab.py
```

Project-required gates: referenciar `AGENTS.md` (o controller executa o
gate final; worker executa os focados acima + `check` se tocar view).

Runtime/verification evidence: não há mudança visual; evidência =
testes de orçamento + paridade. Opcional: medir queries/tempo do default
antes/depois com o procedimento do relatório e registrar no report.

## Acceptance criteria

- [ ] R1 demonstrado por teste de paridade do HTML default.
- [ ] R2 demonstrado por teste: zero queries de falha-final no default.
- [ ] R3 demonstrado por teste: agregação global e 3 `DISTINCT` de
      filtro ausentes no default e presentes no modo detalhe (asserção
      escopada — `DISTINCT worker_label` do histórico cai só em S2).
- [ ] R4 demonstrado: chaves removidas; grep confirma template sem uso.
- [ ] R5 demonstrado por testes de paridade (patients + detalhe).
- [ ] R6 demonstrado: suíte do dashboard verde, sem diff em dashboard.
- [ ] Testes focados acima verdes.

## Escalation conditions

Parar com `BLOCKED_NEEDS_DECISION` se descobrir: template usa `runs` ou
`ingestion_stats` em algum ramo; algum teste existente depende das
chaves removidas de forma que indique contrato público; condicionar as
chamadas exige mudar assinatura dos helpers; qualquer mudança visível
não aprovada; implicação de segurança/privacidade.

## Evidence report

Produzir `/tmp/sirhosp-slice-S1-report.md` com: status, requirements →
evidence, arquivos alterados, failing-before evidence, passing-after
evidence, comandos + exit status, expansão de blast radius (se houver),
riscos/limitações, decisões pendentes (se houver).

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
