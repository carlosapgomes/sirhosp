# Slice RPSA-S10 — Aggregate reconciliation health and integrity report

## Mission

Implement only read-only, aggregate-safe health diagnostics for exit
coverage, backlog, ambiguities and source-confirmed duplicates, plus a
daily integrity command. It must not enqueue work, call the source or
mutate clinical state.

## Mandatory context-zero reading order

1. `AGENTS.md`, `PROJECT_CONTEXT.md`
2. Change proposal, design, tasks and ADR-0009
3. Delta spec `specs/ingestion-pipeline-health/spec.md` (three ADDED
   requirements: aggregate/alertable health; extraction coverage
   distinguishing confirmed zero; read-only and identity-safe) and the
   health-adjacent requirement in
   `specs/stale-admission-detection/spec.md`
4. RPSA-S4, S5, S7 and S9 reports (duplicate pairs, stale cases,
   durable zero-confirmation metadata, backfill review cohorts)
5. `apps/ingestion/pipeline_health.py` — the existing framework:
   `HealthConfig`, `HealthViolation`, `HealthResult.healthy`,
   `evaluate_pipeline_health`, per-domain `_evaluate_*` sections
6. `apps/ingestion/management/commands/check_ingestion_pipeline_health.py`
   (options → config, `_render`, exit-code convention)
7. `apps/ingestion/models.py` — `IngestionRun`,
   `IngestionRunStageMetric.details_json` (RPSA-S7 persists
   `zero_confirmed`/`attempt_count` on the `discharge_persistence`
   stage metrics alongside run counters)
8. Reconciliation evidence/case models: `DischargeRecord`/
   `DeathRecord.reconciliation_status`, `StaleAdmissionCase`,
   `ReconciliationEvent`, canonical `Admission` manager
9. `tests/unit/test_ingestion_pipeline_health.py` (32 existing tests —
   must not regress) and safe-output conventions

## Ground truth (established; do not reinvent)

- **Extend the existing framework** — add reconciliation sections to
  `evaluate_pipeline_health` (a `_evaluate_exit_reconciliation`-style
  function returning `HealthViolation` entries). No second health
  framework, no new models, no schema change.
- **Backlog by status group (count + oldest age)**: aggregate over the
  review-queue semantics established by RPSA-S6 —
  `DischargeRecord`/`DeathRecord` rows with
  `reconciliation_status` in {pending, ambiguous, conflict} plus open
  `StaleAdmissionCase` rows (a fourth group). Age = now minus the
  row's created/anchor timestamp, reported per group as count and
  oldest age. Events (`ReconciliationEvent`) are append-only audit and
  are NOT backlog: never count them as pending work.
- **Source-confirmed duplicate invariant**: count of canonical open
  admissions that have a same-patient, same-local-admission-date
  closed admission with the closed row at least as fresh as the open
  row (the exact RPSA-S9 duplicate-cohort shape). Any occurrence is a
  violation (default max 0) — the pair should have been merged or be
  in review; report the count only.
- **Extraction coverage from durable metadata only**: key discharges
  runs by extraction date via `IngestionRun` +
  `IngestionRunStageMetric.details_json`. A date is complete when the
  run succeeded AND (persisted records > 0 OR `zero_confirmed=true`
  with `attempt_count >= 2`); one successful empty attempt or a
  missing `zero_confirmed` flag is incomplete; a date with no
  successful run is missing. Never read in-memory extraction results
  or `DailyDischargeCount` (derived, not coverage).
- **Missing-dates gap**: report count and date bounds only. More than
  7 missing/incomplete catch-up dates raises an operator-action
  violation; health NEVER starts recovery itself.
- **Open outside current census (informational)**: count of canonical
  open admissions (merged_into IS NULL, discharge_date NULL) whose
  patient is absent from the most recent `CensusSnapshot` occupied
  set — aggregate count only, no threshold, no case creation (RPSA-S5
  owns case creation).
- **Named thresholds on `HealthConfig` with safe defaults, overridable
  via command options**:
  `missing_dates_max=7` (spec-fixed),
  `backlog_age_max_hours=48` (pending and ambiguous groups),
  `conflict_max_count=0`, `duplicate_max_count=0`.
  Healthy dataset: no violation → exit status 0; any violation → exit
  status 1 (reuse the existing command convention).
- **Two commands, one evaluation**: `check_ingestion_pipeline_health`
  gains the reconciliation sections in its regular evaluation; the new
  `report_admission_reconciliation_integrity` is a thin daily wrapper
  that runs the SAME evaluation with default config, always renders
  the reconciliation block, and exits nonzero on violations. No
  duplicated logic between the two commands.
- **Read-only and identity-safe**: no `.create/.update/.save/.delete`,
  no `call_command`, no source/queue/automation invocation anywhere in
  the touched evaluation code; identical database state before/after
  (assert via counts in tests). Output may carry dates, ages, status
  group names, counts and bounds — never patient/admission/source
  identifiers, names, record numbers or clinical text. Query field
  names in code are fine; values must not enter result messages.
- Synthetic fixtures only; no source automation or production access.

## Scope and file limit

Maximum **7 repository files changed**:

- `apps/ingestion/pipeline_health.py`
- `apps/ingestion/management/commands/check_ingestion_pipeline_health.py`
- `apps/ingestion/management/commands/report_admission_reconciliation_integrity.py`
  (new)
- `tests/unit/test_ingestion_pipeline_health.py` (extend; existing 32
  tests preserved)
- `tests/unit/test_reconciliation_integrity_report.py` (new)
- `tests/integration/test_reconciliation_health_commands.py` (new)
- this change's `tasks.md`

No schema, queue, source connector, UI or deploy change is allowed.
Any other file means stop and escalate.

## Contract matrix

| Metric/invariant | Required assertion |
| --- | --- |
| statuses | aggregate count + oldest age per status group |
| confirmed-zero coverage | durable `details_json` (`zero_confirmed=true`, `attempt_count>=2`) → complete |
| one empty attempt / missing flag | incomplete coverage |
| no successful run | missing date; gap count + bounds only |
| gap > 7 | operator-action violation; no recovery started |
| backlog age > 48h (pending/ambiguous) | unhealthy |
| any conflict evidence | violation (max 0) |
| source-confirmed duplicate pair | invariant violation (max 0), count only |
| open outside current census | aggregate count only |
| healthy dataset | exit status 0 |
| any violation | exit status 1, aggregate-safe output |
| all evaluations | identical DB counts before/after; zero source/queue calls |

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) | Teste/check |
| --- | --- | --- |
| backlog por grupo com idade | `pipeline_health.py` | unit (fixtures por status) |
| duplicado source-confirmed | `pipeline_health.py` | unit (par fresco conta; sem par=0) |
| coverage confirmed-zero durável | `pipeline_health.py` | unit (details_json variants) |
| datas faltantes + gap>7 | `pipeline_health.py` | unit (bounds sem identidade) |
| abertas fora do censo | `pipeline_health.py` | unit (count only) |
| thresholds nomeados + override | config + comandos | unit (default) + integração (option) |
| healthy=0 / violação=1 | ambos comandos | integração (exit codes) |
| wrapper diário sem duplicação | comando novo | unit (chama evaluate único) |
| read-only + zero source/queue | avaliação | unit (counts iguais, mocks sem calls) |
| output identity-safe | render | unit (assert stdout sem ids) |
| regressão dos 32 testes | teste existente | suíte existente verde |

## Bootstrap and baseline

```bash
git status --short          # must be clean
git rev-parse HEAD          # record BASE_REF (expected 4ddc492)
./scripts/test-in-container.sh check
```

Reference baseline at `4ddc492`: 3442 unit / 611 integration
(post-S9). Do not re-run full suites as a pre-baseline; report deltas
against these numbers. Escalate via contact_supervisor on any baseline
mismatch.

## TDD RED → GREEN → REFACTOR

RED first, focused (synthetic fixtures across the four domains):

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml up -d db
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/unit/test_ingestion_pipeline_health.py \
  tests/unit/test_reconciliation_integrity_report.py"
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/integration/test_reconciliation_health_commands.py"
```

Expected assertion-level failures: the new evaluation section/name not
importable (`AttributeError`/`ImportError`); `call_command` with the
unknown daily command raising `CommandError`; backlog fixture asserting
per-group counts/ages against a result lacking the reconciliation
fields; a duplicate pair fixture expecting a violation that the current
evaluation cannot produce; confirmed-zero fixture asserting complete
coverage where no coverage concept exists yet; exit-code assertions
(0/1) failing because no violation is detected.

GREEN: implement the reconciliation sections, thresholds, the daily
wrapper and rendering with the smallest change. Refactor only shared
formatting; keep commands thin. Clean code, DRY, YAGNI.

## Mandatory inspections

```bash
rg -n "\.create\(|\.update\(|\.save\(|\.delete\(|call_command|run_.*extraction|enqueue" apps/ingestion/pipeline_health.py apps/ingestion/management/commands/report_admission_reconciliation_integrity.py apps/ingestion/management/commands/check_ingestion_pipeline_health.py
rg -n "prontuario|nome|patient_source_key|admission_id=|source_key" apps/ingestion/pipeline_health.py apps/ingestion/management/commands/report_admission_reconciliation_integrity.py
rg -n "zero_confirmed|attempt_count|details_json|ambiguous|conflict|oldest|duplicate|missing" apps/ingestion/pipeline_health.py tests/unit/test_ingestion_pipeline_health.py
rg -n "missing_dates_max|backlog_age_max_hours|conflict_max_count|duplicate_max_count" apps config
```

Interpretation: the first returns no mutation/enqueue/source calls in
the evaluation paths; the second returns no identity-bearing output
fields; the third confirms durable-flag/backlog/invariant coverage in
code and tests; the fourth confirms named thresholds wired through
config and options.

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

Review every diff against `BASE_REF`. Mark only RPSA-S10 and create one
commit after all gates pass, then stop. Do not run source automation
or production.

## Automatic `INCOMPLETO`

Leave the task unchecked and make no commit if tree/baseline/dependency
fails, RED is not assertion-level, health mutates or enqueues anything,
confirmed-zero coverage reads in-memory results or `DailyDischargeCount`,
output leaks identifiers, thresholds are untested or unnamed, the daily
command duplicates evaluation logic, existing health behavior or its 32
tests regress, a gate fails or more than 7 files are needed.

## Required report

Write `/tmp/sirhosp-slice-RPSA-S10-report.md` with status, base/commit,
acceptance and requirement→file→test matrices, changed-file before/after
snippets, RED/GREEN (quoted assertions), health scenario exit codes,
before/after DB counts proving read-only evaluation, mocked zero
source/queue calls, output-safety inspection, all commands/gates, diff
check, risks and next step. Valid Markdown and synthetic data only.
