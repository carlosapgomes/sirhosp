# SLICE C3-S4 - Management command wrapper and operator output

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/add-historical-recovery-command/proposal.md`
- `openspec/changes/add-historical-recovery-command/design.md`
- `openspec/changes/add-historical-recovery-command/specs/historical-recovery-command/spec.md`
- `openspec/changes/add-historical-recovery-command/specs/ingestion-run-observability/spec.md`
- `openspec/changes/add-historical-recovery-command/tasks.md`
- `openspec/changes/extract-census-discharge-services/change-3-handoff.md`

Implement only Slice C3-S4. Do not start the next slice.

## Branch protocol

Continue working on the dedicated branch for this OpenSpec change:

```bash
git switch change/add-historical-recovery-command
```

If the branch does not exist yet, stop and ask for the previous slice handoff.
Do not implement this slice directly on `main`.

## Objective

Add the `recover_historical_data` management command as a thin wrapper around
the orchestration module.

## Suggested scope

Test CLI parsing, stdout/stderr summaries, dry-run output, and exit status.
Keep orchestration logic out of the command class.

Before coding, confirm Slice C3-S3 was committed. If not, stop and ask for the
S3 commit/handoff. Do not mix uncommitted S3 changes into this slice.

Carry forward these C3-S3 verifier notes:

- `apps/ingestion/historical_recovery.py` may still have a stale module
  docstring saying the module does not call extractor services. If present,
  update it in this slice because the module now contains planning,
  orchestration, dry-run, fail-fast, and safe exception handling.
- C3-S3 intentionally uses a generic operator-facing message for unexpected
  service exceptions: `Unexpected extractor failure.` Do not reintroduce raw
  exception text in stdout/stderr.
- If command output includes dry-run extraction types, avoid displaying guessed
  inconsistent values like `discharges_extraction`; either print the extractor
  name only or introduce a canonical mapping.

## Suggested files

Prefer no more than 5 changed files unless tests require a small helper.

Likely files:

- `apps/ingestion/management/commands/recover_historical_data.py`
- `apps/ingestion/historical_recovery.py` if small wrapper support is needed
- `tests/unit/test_recover_historical_data_command.py`

If you touch existing S1/S2/S3 tests, list the file and reason explicitly in the
slice report.

## Required behavior

Implement and test all of the following:

1. The management command is a thin wrapper around the orchestration module.
2. The command accepts `--date DD/MM/AAAA` for a single-day recovery.
3. The command accepts `--start-date DD/MM/AAAA --end-date DD/MM/AAAA` for an
   inclusive range.
4. The command rejects ambiguous input when `--date` is combined with
   `--start-date` or `--end-date`.
5. The command supports repeatable `--extractor` values and delegates selection
   to the planning/orchestration module.
6. The command supports `--dry-run` and must not call real extractor services in
   dry-run mode.
7. The command supports `--fail-fast` and propagates it to the plan.
8. The command exits successfully when the aggregated result succeeds.
9. The command exits non-zero when the aggregated result has failed steps.
10. Operator output must be deterministic and must not contain raw exception
    text or credential-like values.

If the command prints dry-run steps, prefer showing `extractor` values
(`discharges`, `admissions`, `deaths`, `official_census`) rather than guessed
`extraction_type` values. If an extraction type is needed, add a canonical
mapping such as:

```text
discharges -> discharge_extraction
admissions -> admission_extraction
deaths -> death_extraction
official_census -> official_census_extraction
```

## Logging guidance

Do not log or print raw exception messages that may contain credentials. If this
slice adds logging for unexpected failures, log only sanitized/generic context
unless a dedicated redaction helper is introduced and covered by tests.
Operator-facing output should use the safe message already produced by the
orchestrator.

## Constraints

- Do not modify `apps/discharges/services.py`.
- Do not modify Playwright automation scripts.
- Do not add Celery, Redis, queues, or new orchestration infrastructure.
- Do not add persistent recovery job models or migrations.
- Do not use `call_command` or subprocessed Django commands to run extractors.
- Do not delete existing extractor management commands.
- Do not archive OpenSpec changes in this slice.
- Use synthetic/anonymized test data only.
- Do not print or log raw service exception text.

## Validation

Run at least:

```bash
uv run ruff check apps/ingestion/historical_recovery.py \
  apps/ingestion/management/commands/recover_historical_data.py \
  tests/unit/test_recover_historical_data_command.py
uv run pytest -q tests/unit/test_recover_historical_data_command.py
./scripts/test-in-container.sh unit
openspec validate add-historical-recovery-command --type change --strict
```

If `./scripts/test-in-container.sh unit` runs the whole unit suite instead of
focused paths, document that behavior. Host-only `uv run pytest ...` is
acceptable only as diagnostic evidence, not as the official gate.

## Required report

Create `/tmp/sirhosp-slice-C3-S4-report.md` with:

- summary of the slice;
- acceptance checklist;
- files changed;
- before/after snippets for changed production files;
- commands executed and results;
- risks, pending work, and next suggested slice.
