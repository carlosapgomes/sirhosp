# Slice 002 — Histórico leve + eficiência no detalhe do batch

- Slice ID: S2
- Change: `2026-11-08-ingestion-metrics-page-performance`
- Task: S2 em `tasks.md`
- Depende de: S1 aceito (parte do commit aceito de S1).

## Objective

A tabela de histórico exibe somente colunas baratas calculadas por uma
única agregação SQL por página, e o detalhe do batch passa a exibir o
bloco de eficiência (workers, concorrência, throughput, médias).

## Read first

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/2026-11-08-ingestion-metrics-page-performance/proposal.md`
- `openspec/changes/2026-11-08-ingestion-metrics-page-performance/design.md`
  — D2, D3, orçamento de queries
- `openspec/changes/2026-11-08-ingestion-metrics-page-performance/specs/ingestion-run-metrics-portal/spec.md`
  — "prioritizes batch history" (MODIFIED), "Batch detail exposes worker
  efficiency metrics" (ADDED)
- `apps/services_portal/views.py` — `_compute_batch_metrics`,
  `_get_batch_history_context`, `_summarize_batch_findings`,
  `ingestion_metrics`
- `apps/services_portal/templates/services_portal/ingestion_metrics.html`
  — tabela de histórico + bloco de detalhe

Follow the repository engineering policy in `AGENTS.md` and preserve
existing conventions. Prefer the smallest correct change; avoid
speculative abstraction and unrelated refactoring.

## Requirements

- R1 — Cada linha do histórico exibe somente: Batch ID, Status (com
  apresentação derivada de findings quando houver), Início, Fim,
  Duração, Jobs, Sucesso, Falha. As colunas Workers, Pico, Jobs/min,
  Méd/job, Méd/tent não são renderizadas no histórico.
- R2 — Contagens Jobs/Sucesso/Falha do histórico vêm de uma única query
  agregada por página (`GROUP BY` batch/status sobre os batches da
  página); nenhum full scan de runs/attempts por batch para o
  histórico.
- R3 — O default não emite nenhuma query que carregue runs ou attempts
  por batch para o histórico (zero queries contra
  `ingestion_ingestionrunattempt`; runs tocados somente pelo agregado
  limitado de R2).
- R4 — O modo `?batch_id=` exibe bloco de eficiência do lote com os
  mesmos valores que `_compute_batch_metrics` calculava: workers
  distintos, pico e média de concorrência, throughput, média/job,
  média/tentativa (reutilizar o helper existente para 1 batch).
- R5 — Apresentação de findings no histórico preservada (derived status
  e contagens agregadas, 1 query/página).
- R6 — Page size 20, ordenação `-finished_at, -id`, empty states e aba
  `patients` inalterados.

## Expected blast radius

Provavelmente afetados:

- `apps/services_portal/views.py` — `_get_batch_history_context` (novo
  agregado), `ingestion_metrics` (bloco de eficiência no detalhe),
  remoção/simplificação do uso de `_compute_batch_metrics` no histórico.
- `apps/services_portal/templates/services_portal/ingestion_metrics.html`
  — headers/células do histórico + novo bloco no detalhe.
- `tests/unit/test_services_portal_ingestion_metrics.py` — conteúdo,
  valores e orçamento de queries.
- `TestIngestionMetricsBatchHistory` (a partir de ~L756) **exige
  atualização**: `test_batch_history_context_worker_metrics`,
  `test_batch_history_context_peak_concurrency` e
  `test_batch_history_context_throughput_and_durations` afirmam
  `observed_worker_count/labels`, `observed_peak_concurrency`,
  `throughput_jobs_per_minute` e `avg_*` nas entradas do histórico —
  exatamente as métricas removidas. Mover as asserções de valores para
  os testes do detalhe e reescrever as do histórico para o novo
  contrato (R1/R2). Grep complementar por `Workers`, `Pico`,
  `Jobs/min`, `Méd/job`, `Méd/tent` para pegar asserções de HTML —
  asserções da aba `patients` permanecem válidas e intocadas.

Sensíveis / fora de escopo (escalar se precisar tocar):

- `_compute_batch_metrics` em si — reutilizar, não reescrever; se ficar
  sem outro chamador além do detalhe, manter (sem delete especulativo).
- `_summarize_batch_findings` e classificador de findings — sem mudança.
- Paginação (slice 003), índices (slice 004), dashboard, workers.

Comportamento anterior que permanece: todos os valores exibidos são os
mesmos, apenas em outro lugar (histórico→detalhe); findings agregados;
aba patients idêntica.

## Failing-before plan

TDD:

1. Teste de conteúdo (RED antes): fixture com 1 batch finalizado com
   runs/attempts; GET default — afirmar que o HTML do histórico contém
   `Jobs`/`Sucesso`/`Falha` e **não contém** os headers `Pico`,
   `Méd/job`, `Méd/tent` na tabela de histórico. Hoje contém → falha.
   (Atenção: `Jobs/min` também aparece na aba patients — afirmar no
   escopo da tabela de histórico, não no HTML inteiro.)
2. Teste de ausência de scans (RED antes): fixture com batches contendo
   runs + attempts; GET default — afirmar zero queries contra
   `ingestion_ingestionrunattempt` e que nenhuma query carrega runs por
   batch fora do agregado único de contagens. Hoje o histórico varre
   attempts e runs por batch → falha. Não usar comparação K-vs-2K de
   contagem: o nº de queries já é fixo por batch (`.iterator()`), então
   essa comparação passaria antes e depois sem provar nada.
3. Teste de detalhe (RED antes): GET `?batch_id=` — afirmar presença do
   bloco de eficiência com os valores esperados da fixture. Hoje
   ausente → falha.

## Implementation constraints

- Não alterar `_compute_batch_metrics` salvo o mínimo para reutilizá-lo
  no detalhe; não recalcular no detalhe o que `selected_batch_stats` já
  calcula (aceitar pequena duplicação de contagens em vez de refactor).
- Não mudar page size, ordenação, rotas ou querystring.
- Não antecipar elisão (slice 003): paginações continuam `page_range`
  neste slice.
- Atualizar somente testes acoplados ao contrato antigo do histórico;
  não reescrever suítes.

## Validation

Focused validation (worker):

```bash
uv run pytest -q tests/unit/test_services_portal_ingestion_metrics.py
uv run pytest -q tests/integration/test_services_portal_ingestion_metrics_failures_tab.py
uv run pytest -q tests/integration/test_patient_flow_findings_observability.py
```

Project-required gates: referenciar `AGENTS.md` (controller executa o
gate final).

Runtime/verification evidence: GET default + detalhe via test client
com fixtures volumosas (ex.: 3 batches × 60 runs × attempts) registrando
queries antes/depois no report; opcional: screenshot do histórico e do
detalhe em dev para prova visual da coluna movida.

## Acceptance criteria

- [ ] R1 demonstrado por teste de conteúdo do histórico.
- [ ] R2 demonstrado: agregado único (inspeção de queries ou teste).
- [ ] R3 demonstrado por teste de ausência de scans por batch.
- [ ] R4 demonstrado por teste de conteúdo/valores do detalhe.
- [ ] R5 demonstrado por teste existente de findings verde.
- [ ] R6 demonstrado: page size/ordenação/empty/patients sem diff.
- [ ] Testes focados acima verdes; testes atualizados restritos ao
      contrato antigo do histórico (`TestIngestionMetricsBatchHistory` +
      grep de HTML), justificados no report.

## Escalation conditions

Parar com `BLOCKED_NEEDS_DECISION` se descobrir: valores do detalhe
divergem dos que o histórico exibia (helper não reutilizável sem
reescrita); agregado único inviável sem mudar ordenação/paginação;
testes de findings exigem colunas antigas no histórico (conflito de
spec); qualquer dado clínico novo exposto; mudança de schema necessária.

## Evidence report

Produzir `/tmp/sirhosp-slice-S2-report.md` com: status, requirements →
evidence, arquivos alterados, failing-before evidence, passing-after
evidence, comandos + exit status, runtime/verification evidence,
expansão de blast radius e testes atualizados (justificativa),
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
