# Slice RPSA-S7 — Confirmed-zero extraction and recovery integration

## Mission

Implement only semantic confirmation of empty discharge reports plus
propagation of safe reconciliation counters through extraction and
historical recovery. One empty/missing report is not success; exactly one
independent confirmation is required. Do not change schedules, dashboard,
health or backfill.

## Mandatory context-zero reading order

1. `AGENTS.md`, `PROJECT_CONTEXT.md`
2. Change proposal, design, tasks and ADR-0009
3. `specs/historical-extraction-services/spec.md` (confirmed-zero
   scenarios: first empty retried, two empties confirm zero, confirmation
   fails or disagrees) and `specs/historical-recovery-command/spec.md`
   (unconfirmed zero is a failed step; successful steps are not retried)
4. RPSA-S2 report/diff (reconciliation counters contract) and the S6
   acceptance state (HEAD `1a93585`)
5. `apps/discharges/extraction_service.py` (`run_discharge_extraction`
   orchestration, `_persist_discharge_records`,
   `_reconcile_persisted_records` counters, `create_stage_metric` usage)
   and `apps/discharges/management/commands/extract_discharges.py`
   (thin wrapper) and `refresh_daily_discharge_counts.py` (argument-less
   global aggregate command)
6. `apps/ingestion/historical_extraction.py` (`create_stage_metric`,
   `ExtractionResult` shape), `historical_recovery.py` (step success/
   failure/skip model, retry rounds, fail-fast) and
   `management/commands/recover_historical_data.py`
7. Existing recovery tests to mirror conventions (without editing them):
   `tests/unit/test_historical_recovery_failures.py`,
   `test_historical_recovery_orchestration.py`,
   `test_historical_extraction_contract.py`

## Ground truth (established; do not reinvent)

- "Empty" means: the automation subprocess completed successfully but
  produced no XLS file in the output directory OR an XLS with zero
  parseable rows. Anything else keeps existing semantics (validation
  errors, timeouts, source failures).
- Confirmation is exactly ONE additional independent invocation of the
  same subprocess (fresh temporary output directory). Maximum two source
  invocations per `run_discharge_extraction` call — prove with mock call
  counting. There is no third attempt.
- First attempt empty: do NOT mark success, do NOT overwrite or delete
  prior evidence, do NOT write `DailyDischargeCount` (never `count=0`
  from absence). Then run the confirmation:
  - confirmation empty too → semantically confirmed zero: extraction
    result is SUCCESSFUL, and the durable stage-metric `details_json`
    for stage `discharge_extraction` gains `zero_confirmed: true` and
    `attempt_count: 2` alongside the existing RPSA-S2
    `reconciliation_<status>` counters; `ExtractionResult` exposes a
    way for later health/catch-up code to distinguish confirmed zero
    from missing/unconfirmed coverage (e.g. a defaulted field — the
    dataclass gains fields with defaults so the thin
    `extract_discharges` command and every existing caller keep
    compiling and behaving);
  - confirmation non-empty → process the confirmation rows normally
    (persist + reconcile exactly like a first-attempt success);
    `attempt_count: 2`, `zero_confirmed: false`;
  - confirmation fails/times out → extraction FAILED with a structured,
    credential-safe failure reason (e.g. `zero_unconfirmed`), stage
    metric `failed` carrying `zero_confirmed: false` and
    `attempt_count: 2`; prior evidence untouched.
- Non-empty first attempt: single invocation, `attempt_count: 1`,
  `zero_confirmed: false`, existing behavior otherwise (persist,
  reconcile, counters).
- Persist `attempt_count` (1 or 2) and `zero_confirmed` on every
  successful/failed discharge stage metric of this flow — durable
  across query/process boundaries (re-query by run id in tests).
- Aggregate refresh ordering: a confirmed successful extraction (rows
  or confirmed zero) invokes `refresh_daily_discharge_counts` exactly
  once via `django.core.management.call_command` AFTER persistence and
  reconciliation complete. Failed or unconfirmed extractions NEVER
  invoke it. The command takes no arguments (global aggregate) — do not
  invent per-date arguments.
- Recovery integration: `historical_recovery.py` already treats
  `success=False` service results as failed steps with normal retry
  limits and never re-runs successful steps. Therefore an unconfirmed
  zero MUST surface as `success=False` (the new failure reason) so the
  spec scenario "unconfirmed zero is a failed step" holds with no
  structural recovery change. Only touch `historical_recovery.py` /
  `recover_historical_data.py` if aggregate-safe propagation of the new
  metadata into step summaries genuinely requires it — if existing
  metrics pass-through already carries `details_json`, prefer zero
  changes there and say so in the report.
- Reuse the RPSA-S2 reconciliation counters exactly
  (`_reconcile_persisted_records`); do not duplicate matching rules.
- Credentials still travel via argv today; this slice MUST NOT worsen
  it (no new credential plumbing, no echoing) — RPSA-S7A removes argv
  transport for all four extractors.
- Extract one small attempt function (single subprocess invocation +
  parse) called at most twice; defer persistence until the semantic
  outcome is known. Refactor only duplicate result assembly; preserve
  fail-fast and end-of-batch retry behavior.
- No schedules, dashboard, health-surface or backfill changes here.

## Scope and file limit

Maximum **9 repository files changed** — 7 core plus 2 authorized
exceptions (second one added by controller amendment, 2026-09-04):

- `apps/discharges/extraction_service.py`
- `apps/ingestion/historical_extraction.py` (only if `ExtractionResult`
  field additions live there)
- `apps/ingestion/historical_recovery.py` (conditional — see ground
  truth; may end unchanged)
- `apps/ingestion/management/commands/recover_historical_data.py`
  (conditional — same condition)
- `tests/unit/test_discharge_zero_confirmation.py` (new)
- `tests/unit/test_historical_recovery.py` (new — unconfirmed-zero
  failed-step and confirmed-zero not-retried unit coverage with mocked
  service results)
- `tests/unit/test_recover_historical_data_command.py`
  (EXISTS at `tests/unit/` — extend, do not rewrite; command-level
  scenarios with mocked service/plan execution)
- this change's `tasks.md`

Authorized exception (controller amendment, 2026-09-04, runtime
escalation resolved):

- `tests/unit/test_daily_discharge_count.py` — ONLY the
  `TestExtractDischargesHook::test_service_module_contains_persistence_logic`
  `call_command` assertion, replaced by the strictly stronger guard
  (`content.count("call_command(") == 1` plus the pinned
  `call_command("refresh_daily_discharge_counts")` literal, with an
  RPSA-S7 comment). Nothing else in that file.

Controller amendment (2026-09-04, runtime escalation resolved): the
original list named `tests/integration/test_recover_historical_data_command.py`
by a classification error — the module actually lives at `tests/unit/`.
The authorized slot is the real path above; the file limit counts it as
the same slot (9 total including both amendments).

Controller amendment (2026-09-04, runtime escalation resolved): the
original list named `tests/integration/test_recover_historical_data_command.py`
by a classification error — the module actually lives at `tests/unit/`.
The authorized slot is the real path above; still 8 files total.

If the `extract_discharges` command or any other file requires behavior
changes, stop `INCOMPLETO`; do not exceed the list (9 files, amendments
included). The three existing recovery test modules listed in the
reading order must NOT be edited.

## Contract matrix

| Initial attempt | Confirmation | Required result |
| --- | --- | --- |
| non-empty success | not called | persist/reconcile normally; attempt_count=1 |
| empty or missing XLS | empty | confirmed-zero success; durable `zero_confirmed`+attempt_count=2; refresh invoked after reconciliation |
| empty or missing XLS | failure/timeout | failed (`zero_unconfirmed`); prior evidence untouched; no refresh; no `DailyDischargeCount=0` |
| empty or missing XLS | non-empty | process confirmation rows normally; attempt_count=2; refresh after reconciliation |
| initial failure/timeout | not called | existing failure semantics; attempt_count recorded |

Also prove: confirmation is a distinct source invocation (mock call
count = 2, never 3); unconfirmed zero does not write
`DailyDischargeCount=0` anywhere; durable stage metadata survives a new
query/process boundary; recovery retries an unconfirmed zero as a
failed step and does not re-run a confirmed-zero success; successful
and ambiguous rows remain idempotent and aggregate-safe; failure
metadata stays structured and credential-safe.

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| confirmação única (máx. 2 invocações) | `extraction_service.py` | unit: mock conta invocações por caminho da matriz |
| confirmed-zero durável | `extraction_service.py` (+`historical_extraction.py` se `ExtractionResult` mora lá) | unit: re-query do stage metric por run id pós-serviço |
| unconfirmed = failed estruturado | `extraction_service.py` | unit: `success=False`, reason novo, metadata sem credenciais |
| não sobrescrever evidência pré-confirmacão | `extraction_service.py` | unit: evidência pré-existente intacta nos 3 caminhos de confirmação |
| sem `DailyDischargeCount=0` por ausência | `extraction_service.py` | unit: zero agregados criados/atualizados em caminho unconfirmed |
| refresh pós-reconciliação somente confirmado | `extraction_service.py` | unit: ordenação de chamadas mockadas (rows, confirmed-zero) vs nunca no falho |
| recovery: unconfirmed zero = step failed | `historical_recovery.py` (ou nada) | unit novo + integration estendida: exit non-zero, retry ocorre |
| recovery: confirmed zero não re-executado | idem | unit novo: retry round não chama o passo bem-sucedido |
| comando recovery integra cenários | `recover_historical_data.py` (ou nada) | unit estendido (`tests/unit/test_recover_historical_data_command.py`) com mocks de service/plan |

## RED

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml up -d db
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/unit/test_discharge_zero_confirmation.py \
  tests/unit/test_historical_recovery.py \
  tests/unit/test_recover_historical_data_command.py"
```

- Falha esperada (unit novo): coleta/asserção das funções e metadados
  ainda inexistentes (AttributeError/ImportError/asserções de
  contagem/ordenção) — falhas de asserção reais, não de ambiente.
- Falha esperada (unit estendido existente): cenários novos de
  unconfirmed-zero e confirmed-zero sem suporte atual falham nas
  asserções de exit code/summary/retry no caminho
  `tests/unit/test_recover_historical_data_command.py`.
- Baseline de referência no HEAD (`1a93585`): 3348 unit / 595
  integration. Qualquer falha não relacionada deve ser escalada via
  `contact_supervisor`.

## GREEN / verificação local

- Os mesmos comandos focados do RED passam (exit 0).
- `./scripts/test-in-container.sh unit` e `integration` verdes; desvios
  além dos novos testes explicados no relatório.
- `./scripts/test-in-container.sh lint` e `typecheck` sem erro.
- `uv run --no-sync python manage.py makemigrations --check` limpo
  (nenhuma migração esperada neste slice).

## Mandatory inspections

```bash
rg -n "zero_confirmed|attempt_count|zero_unconfirmed" \
  apps/discharges apps/ingestion tests
rg -n "refresh_daily_discharge_counts|call_command" \
  apps/discharges/extraction_service.py tests
rg -n "DailyDischargeCount.*(create|update)|update_or_create\(" \
  apps/discharges/extraction_service.py
rg -n "for .*range|while |retry" apps/discharges/extraction_service.py
rg -n "username|password|prontuario|nome" \
  apps/discharges/extraction_service.py apps/ingestion/historical_recovery.py
```

Interpretation: the confirmation loop is bounded to two invocations; no
`DailyDischargeCount` writes live in the extraction service; metadata
carries no credentials or patient identity; refresh ordering is pinned
by mocked call-order assertions. Any argv credential handling change
beyond keeping current behavior fails the slice (RPSA-S7A owns that).

## Gates and completion

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate reconcile-patient-exits-and-stale-admissions --strict
./scripts/markdown-lint.sh
git diff --check
```

Inspect all diffs against `BASE_REF`. Mark only RPSA-S7 and create one
commit after every gate passes, then stop. Do not activate timers or
access production.

## Automatic `INCOMPLETO`

No checkbox/commit if tree/baseline/dependency fails, RED is not
assertion-level, one empty attempt is accepted as success, confirmation
can run more than once, prior data is overwritten before confirmation,
confirmed coverage lives only in memory, recovery treats unconfirmed
zero as success, `DailyDischargeCount=0` is written from absence,
refresh ordering is absent or the extraction writes the aggregate
directly, identity/credentials leak or worsen, a migration appears, any
gate fails or the file limit is exceeded.

## Required report

Create `/tmp/sirhosp-slice-RPSA-S7-report.md` with status, base/commit,
complete attempt matrix with per-cell mock call counts, traceability
matrices, changed-file before/after snippets, RED/GREEN evidence,
prior-evidence and no-zero-aggregate assertions, refresh call-order
proofs, durable-metadata re-query proof, output-safety inspection
results, command and gate results, diff check, whether each conditional
recovery file ended changed and why, risks and next step. Valid Markdown
and synthetic data only.
