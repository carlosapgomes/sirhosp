# Design: Extract Admission and Death Services

## Context

`extract_admissions` and `extract_deaths` currently contain orchestration logic
directly inside Django management commands. Each command resolves credentials,
creates an `IngestionRun`, executes a Playwright automation script through
`run_subprocess`, records stage metrics, reads the generated JSON, persists
records, and exits with `sys.exit(1)` on failure.

This shape works for direct CLI operation, but it is a poor integration boundary
for a future daily historical recovery command. A recovery orchestrator needs to
call each extraction for a specific date, receive structured success/failure
information, retry failed jobs, and produce deterministic summaries without
parsing command output or catching `SystemExit` as the primary control flow.

This change intentionally starts with admissions and deaths because they are the
simplest historical report extractors and already delegate persistence to
`process_admissions` and `process_deaths`. It establishes the pattern for later
changes without touching the more complex official census and discharge flows.

## Goals / Non-Goals

**Goals:**

- Create a small, typed service contract for historical extraction executions.
- Expose admissions and deaths extraction as Python-callable services.
- Preserve existing management command CLI behavior and arguments.
- Keep existing Playwright automation scripts as subprocess-based executables.
- Preserve `IngestionRun` and `IngestionRunStageMetric` observability.
- Make admission/death persistence safer for repeated runs and future
  orchestration.
- Keep slices small enough for a context-zero executor LLM.

**Non-Goals:**

- Do not implement `recover_historical_data` in this change.
- Do not refactor `extract_official_census` or `extract_discharges` in this
  change.
- Do not modify `apps/discharges/services.py`; it is part of the existing
  discharge reconciliation flow and must be preserved.
- Do not introduce persistent historical recovery job models in this change.
- Do not replace subprocess-based Playwright scripts with direct imports.
- Do not introduce Celery, Redis, or additional orchestration infrastructure.

## Decisions

### Decision 1: Management commands become wrappers, services own execution

The extraction services will own the operational flow for admissions and deaths:
validate/resolve dates, resolve credentials, create/update `IngestionRun`, run
the Playwright subprocess, parse generated output, call persistence functions,
and return a structured result.

Management commands will remain responsible for argument parsing, user-facing
messages, and translating service failure into the existing non-zero command
exit behavior.

Alternatives considered:

- Keep logic in commands and use `call_command` later: faster now, but makes the
  recovery command depend on CLI behavior and `SystemExit` handling.
- Move all four extractors at once: cleaner final state, but too large for the
  desired slice execution model.

### Decision 2: Use a small shared result contract before generalizing deeply

Introduce a minimal shared result structure, for example an `ExtractionResult`
dataclass, with fields such as extraction type, date range, success status,
metrics, failure reason, error message, and linked `IngestionRun` id.

The contract should be useful for admissions/deaths now and extensible for
official census/discharges later, but it should not try to model every future
need. Avoid a large abstraction framework.

Alternatives considered:

- Return raw dictionaries: less code, but weaker contracts for future
  orchestration and tests.
- Create a generic extractor class hierarchy immediately: likely over-engineered
  before all four extractors are migrated.

### Decision 3: Keep Playwright automation scripts as subprocess boundaries

The scripts under `automation/source_system/` remain standalone. Services
continue to execute them via
`apps.ingestion.extractors.subprocess_utils.run_subprocess`, preserving
process-group cleanup and timeout behavior.

Alternatives considered:

- Import automation scripts directly: would require disentangling CLI parsing,
  Playwright lifecycle, and process isolation.
- Reimplement browser automation inside Django services: unnecessary and higher
  risk.

### Decision 4: Make shared helpers practical, not mandatory abstractions

Shared code may be introduced for repeated mechanics:

- source-system credential resolution;
- automation script path resolution;
- `IngestionRun` creation and finalization;
- stage metric recording;
- subprocess failure classification;
- safe error truncation.

However, each slice should prefer small extracted helpers over a large
framework. The final shape can still be refined after official census and
discharges are migrated in Change 2.

### Decision 5: Keep period support but prefer daily execution for future recovery

The admissions and deaths commands currently accept `--date` and
`--start-date`/`--end-date`. This compatibility must remain. For the future
historical recovery command, the preferred orchestration will be a deterministic
matrix of one date × one extraction type at a time, even if the underlying
service can represent a date range.

## Risks / Trade-offs

- Regression in CLI behavior → Keep command compatibility tests for success and
  failure paths; commands should still exit non-zero on service failure.
- Leaking credentials in logs or result payloads → Do not store full subprocess
  command arguments containing username/password in result metrics, errors, or
  stage details.
- Over-generalized helpers → Limit shared helpers to mechanics used by both
  admissions and deaths in this change.
- Transaction scope hides partial progress → Use transactions around destructive
  persistence, but keep extraction subprocess outside database transactions.
- Existing `IngestionRunAttempt` retry semantics are not used here → Accept for
  this change; a later recovery command can decide whether to use existing
  attempts or introduce historical job/attempt models.

## Migration Plan

1. Add shared result contract and targeted helper functions without changing
command behavior. 2. Extract admissions execution into a service and update the
command wrapper. 3. Extract deaths execution into a service and update the
command wrapper. 4. Add/adjust tests for service results, command compatibility,
observability, and idempotent persistence. 5. Run the official containerized
checks for the changed scope.

Rollback strategy: because external command interfaces are preserved, rollback
can be done by reverting the service extraction and restoring command-local
orchestration if tests reveal unacceptable drift.

## Multi-Change Roadmap

This change is phase 1 of a broader plan.

### Change 2: `extract-census-discharge-services`

Intended scope:

- Apply the same service-entry-point pattern to `extract_official_census`.
- Protect official census delete/recreate persistence with transaction
  boundaries.
- Extract discharge XLS parsing and `DailyDischargeCount`/`DischargeRecord`
  persistence from `extract_discharges` into a new module, not into
  `apps/discharges/services.py`.
- Preserve `apps/discharges/services.py` because it belongs to the existing
  discharge reconciliation flow.
- Keep both commands as compatible wrappers.
- Add hardening tests for empty/missing output files and repeated execution.

### Change 3: `add-historical-recovery-command`

Intended scope:

- Add `recover_historical_data` management command.
- Default to yesterday for daily scheduled operation.
- Support explicit `--date` and `--start-date`/`--end-date` modes.
- Generate deterministic date × extraction-type jobs.
- Execute services sequentially, collect failures, retry failed jobs at the end,
  and return reliable exit codes.
- Add `--dry-run` and possibly extraction filtering.
- Add systemd timer documentation after the command behavior is stable.

### Possible Change 4: `persist-historical-recovery-jobs`

Intended scope if needed after Change 3:

- Add persistent recovery job and attempt tracking if in-memory retry summaries
  are insufficient.
- Enforce idempotency/locking for `(date, extraction_type)` recovery jobs.
- Add `--retry-failed-only`, `--force`, and richer operational reporting.
- Integrate job history into admin or operational portal views if valuable.
