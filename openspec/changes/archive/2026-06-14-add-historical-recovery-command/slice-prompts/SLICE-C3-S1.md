# SLICE C3-S1 - Recovery planning and result contracts

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

Implement only Slice C3-S1. Do not start the next slice.

## Branch protocol

Work in a dedicated branch for this OpenSpec change:

```bash
git switch -c change/add-historical-recovery-command
```

If the branch already exists, switch to it instead of creating a new branch. Do
not implement this slice directly on `main`.

## Objective

Create testable planning/result contracts for historical recovery without
calling extractor services yet.

## Suggested scope

Use TDD. Cover single date, inclusive ranges, invalid dates, ambiguous date
arguments, and deterministic extractor subset ordering.

## Suggested files

Prefer no more than 5 changed files unless tests require a small helper.

Likely files:

- `apps/ingestion/historical_recovery.py`
- `tests/unit/test_historical_recovery_planning.py`

## Constraints

- Do not modify `apps/discharges/services.py`.
- Do not modify Playwright automation scripts.
- Do not add Celery, Redis, queues, or new orchestration infrastructure.
- Do not add persistent recovery job models or migrations.
- Do not use `call_command` or subprocessed Django commands to run extractors.
- Do not delete existing extractor management commands.
- Do not archive OpenSpec changes in this slice.
- Use synthetic/anonymized test data only.

## Validation

Run at least:

```bash
./scripts/test-in-container.sh unit
openspec validate add-historical-recovery-command --type change --strict
```

If `./scripts/test-in-container.sh unit` runs the whole unit suite instead of
focused paths, document that behavior. Host-only `uv run pytest ...` is
acceptable only as diagnostic evidence, not as the official gate.

## Required report

Create `/tmp/sirhosp-slice-C3-S1-report.md` with:

- summary of the slice;
- acceptance checklist;
- files changed;
- before/after snippets for changed production files;
- commands executed and results;
- risks, pending work, and next suggested slice.
