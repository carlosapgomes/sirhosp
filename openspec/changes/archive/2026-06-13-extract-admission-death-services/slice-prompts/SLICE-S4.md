# SLICE S4 - Admission persistence hardening

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/extract-admission-death-services/proposal.md`
- `openspec/changes/extract-admission-death-services/design.md`
- `openspec/changes/extract-admission-death-services/specs/historical-extraction-services/spec.md`
- `openspec/changes/extract-admission-death-services/tasks.md`
- Slice reports S1-S3 if available.

Implement only Slice S4. Do not start S5.

## Branch protocol

Continue working on the dedicated branch for this OpenSpec change:

```bash
git switch change/extract-admission-death-services
```

If the branch does not exist yet, create it with `git checkout -b
change/extract-admission-death-services`. Do not implement this slice directly
on `main`.

## Objective

Harden admission persistence for deterministic repeated execution.

## Current code to inspect

- `apps/admissions/services.py`
- admission extraction service from S3
- tests added in S3

## Suggested scope

- Add tests proving repeated persistence for the same reference date does not
  duplicate `AdmissionRecord` rows.
- Add tests proving empty admission output persists
  `DailyAdmissionCount(count=0, raw_data=[])` and leaves no stale records.
- Add the smallest transaction/idempotency changes required by the tests.

## Suggested files

Prefer no more than 5 changed files.

Likely files:

- `apps/admissions/services.py`
- focused admission persistence tests
- `openspec/changes/extract-admission-death-services/tasks.md`

## Constraints

- Do not modify discharge-related code in this change.
- Do not modify death extraction in this slice.
- Do not modify official census or discharges.
- Keep destructive persistence inside a transaction when changing
  delete/recreate behavior.

## Validation

Run focused admission persistence tests. If practical, run:

```bash
./scripts/test-in-container.sh unit
```

## Required report

Create `/tmp/sirhosp-slice-S4-report.md` with evidence for idempotency and
empty-output behavior.
