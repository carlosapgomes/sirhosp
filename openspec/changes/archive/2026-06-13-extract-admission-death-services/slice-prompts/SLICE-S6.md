# SLICE S6 - Death persistence hardening

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/extract-admission-death-services/proposal.md`
- `openspec/changes/extract-admission-death-services/design.md`
- `openspec/changes/extract-admission-death-services/specs/historical-extraction-services/spec.md`
- `openspec/changes/extract-admission-death-services/tasks.md`
- Slice reports S1-S5 if available.

Implement only Slice S6. Do not start S7.

## Branch protocol

Continue working on the dedicated branch for this OpenSpec change:

```bash
git switch change/extract-admission-death-services
```

If the branch does not exist yet, create it with `git checkout -b
change/extract-admission-death-services`. Do not implement this slice directly
on `main`.

## Objective

Harden death persistence for deterministic repeated execution.

## Current code to inspect

- `apps/deaths/services.py`
- death extraction service from S5
- tests added in S5

## Suggested scope

- Add tests proving repeated persistence for the same reference date does not
  duplicate `DeathRecord` rows.
- Add tests proving empty death output persists `DailyDeathCount(count=0,
  raw_data=[])` and leaves no stale records.
- Add the smallest transaction/idempotency changes required by the tests.

## Suggested files

Prefer no more than 5 changed files.

Likely files:

- `apps/deaths/services.py`
- focused death persistence tests
- `openspec/changes/extract-admission-death-services/tasks.md`

## Constraints

- Do not modify discharge-related code in this change.
- Do not modify admissions except for tiny shared-helper fixes if unavoidable.
- Do not modify official census or discharges.
- Keep destructive persistence inside a transaction when changing
  delete/recreate behavior.

## Validation

Run focused death persistence tests. If practical, run:

```bash
./scripts/test-in-container.sh unit
```

## Required report

Create `/tmp/sirhosp-slice-S6-report.md` with evidence for idempotency and
empty-output behavior.
