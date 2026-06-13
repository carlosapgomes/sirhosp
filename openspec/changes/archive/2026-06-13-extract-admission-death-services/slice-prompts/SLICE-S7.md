# SLICE S7 - Change-level validation and documentation handoff

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/extract-admission-death-services/proposal.md`
- `openspec/changes/extract-admission-death-services/design.md`
- `openspec/changes/extract-admission-death-services/specs/historical-extraction-services/spec.md`
- `openspec/changes/extract-admission-death-services/specs/ingestion-run-observability/spec.md`
- `openspec/changes/extract-admission-death-services/tasks.md`
- Slice reports S1-S6 if available.

Implement only Slice S7. This is the final validation slice for Change 1.

## Branch protocol

Continue working on the dedicated branch for this OpenSpec change:

```bash
git switch change/extract-admission-death-services
```

If the branch does not exist yet, create it with `git checkout -b
change/extract-admission-death-services`. Do not implement this slice directly
on `main`.

## Objective

Verify the completed Change 1 behavior and prepare a clean handoff for Change 2.

## Suggested scope

- Add or adjust tests proving admissions and deaths service executions preserve
  `IngestionRun` and stage metric observability.
- Verify management commands still expose `--date`, `--start-date`, and
  `--end-date`.
- Run relevant validation commands.
- Update OpenSpec checkboxes for completed tasks.
- Write a short handoff note for Change 2 if implementation details differ from
  the design roadmap.

## Suggested files

Prefer no more than 5 changed files, excluding test snapshot churn if any.

Likely files:

- focused tests for observability/command compatibility
- `openspec/changes/extract-admission-death-services/tasks.md`
- optional
  `openspec/changes/extract-admission-death-services/change-2-handoff.md`

## Constraints

- Do not modify discharge-related code in this change.
- Do not start official census/discharge refactoring in this slice.
- Do not create `recover_historical_data`.
- Do not add new production dependencies.

## Validation

Run at least:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
```

If any command cannot be run, document why and include the exact error.

## Required report

Create `/tmp/sirhosp-slice-S7-report.md` with:

- final acceptance checklist;
- validation commands and results;
- any remaining risks;
- recommended next OpenSpec change name and scope.
