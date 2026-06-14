# SLICE C3-S5 - Legacy shell script and documentation handoff

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

Implement only Slice C3-S5. Do not start the next slice.

## Branch protocol

Continue working on the dedicated branch for this OpenSpec change:

```bash
git switch change/add-historical-recovery-command
```

If the branch does not exist yet, stop and ask for the previous slice handoff.
Do not implement this slice directly on `main`.

## Objective

Clarify the relationship between the legacy shell helper and the new canonical
Django recovery command.

## Suggested scope

Before coding, confirm Slice C3-S4 was committed. If not, stop and ask for the
S4 commit/handoff. Do not mix uncommitted S4 changes into this slice.

Decide whether to keep or minimally update `scripts/recover-historical-data.sh`.
Add a handoff note and confirm no persistent recovery model was introduced.

Carry forward these C3-S4 verifier notes:

- The Django command is now the canonical recovery entry point; the legacy shell
  script should either stay explicitly documented as legacy or delegate to the
  new command with minimal behavior change.
- `recover_historical_data.py` may contain small unreachable defensive branches
  in date-range parsing. Remove them if touched and if tests remain clear.
- A dry-run end-to-end command test without mocking the whole orchestrator would
  be valuable to verify the command and orchestrator are wired together.
- Do not print raw exception text. If this slice adds logging for diagnostics,
  use only sanitized/generic messages unless a redaction helper is added and
  tested.

## Suggested files

Prefer no more than 5 changed files unless tests require a small helper.

Likely files:

- `scripts/recover-historical-data.sh` if updated
- `openspec/changes/add-historical-recovery-command/recovery-handoff.md`
- `openspec/changes/add-historical-recovery-command/tasks.md`
- optional `apps/ingestion/management/commands/recover_historical_data.py` for
  small cleanup only
- optional `tests/unit/test_recover_historical_data_command.py` for a dry-run
  end-to-end command test

If you touch production Python in this documentation/handoff slice, keep the
change minimal and explain why in the report.

## Required behavior

Implement and document all of the following:

1. State clearly that `python manage.py recover_historical_data` is the
   canonical recovery entry point.
2. State clearly whether `scripts/recover-historical-data.sh` remains a legacy
   helper or now delegates to the Django command.
3. Confirm no recovery job model, attempt model, migration, Celery, Redis, or
   new persistent orchestration state was added.
4. Confirm existing extractor management commands remain supported wrappers.
5. If adding diagnostics, do not print or log raw service exception text.
6. If adding a dry-run command test, ensure it exercises the command without
   mocking the whole orchestrator and proves no extractor service is called.
7. If touching the command file, remove only obvious unreachable defensive
   branches and keep existing validation behavior unchanged.

## Optional dry-run end-to-end test guidance

A useful test can patch the four extractor service functions or service registry
entries to raise if called, then invoke:

```bash
python manage.py recover_historical_data --date 01/06/2026 --dry-run
```

The assertion should prove the command exits successfully and none of the
services were called. Do not use real Playwright automation.

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
./scripts/markdown-lint.sh
openspec validate add-historical-recovery-command --type change --strict
```

If Python files are changed, also run focused checks such as:

```bash
uv run ruff check \
  apps/ingestion/management/commands/recover_historical_data.py \
  tests/unit/test_recover_historical_data_command.py
uv run pytest -q tests/unit/test_recover_historical_data_command.py
```

If `./scripts/test-in-container.sh unit` runs the whole unit suite instead of
focused paths, document that behavior. Host-only `uv run pytest ...` is
acceptable only as diagnostic evidence, not as the official gate.

## Required report

Create `/tmp/sirhosp-slice-C3-S5-report.md` with:

- summary of the slice;
- acceptance checklist;
- files changed;
- before/after snippets for changed production files;
- commands executed and results;
- risks, pending work, and next suggested slice.
