# SLICE S3 - Admission extraction service and command wrapper

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/extract-admission-death-services/proposal.md`
- `openspec/changes/extract-admission-death-services/design.md`
- `openspec/changes/extract-admission-death-services/specs/historical-extraction-services/spec.md`
- `openspec/changes/extract-admission-death-services/specs/ingestion-run-observability/spec.md`
- `openspec/changes/extract-admission-death-services/tasks.md`
- Slice reports S1 and S2 if available.

Implement only Slice S3. Do not start S4.

## Branch protocol

Continue working on the dedicated branch for this OpenSpec change:

```bash
git switch change/extract-admission-death-services
```

If the branch does not exist yet, create it with `git checkout -b
change/extract-admission-death-services`. Do not implement this slice directly
on `main`.

## Objective

Move `extract_admissions` orchestration into a Python-callable service and keep
the existing command as a compatible wrapper.

## Current code to inspect

- `apps/admissions/management/commands/extract_admissions.py`
- `apps/admissions/services.py`
- `apps/ingestion/extractors/subprocess_utils.py`
- shared modules added in S1/S2

## Suggested scope

- Add tests that mock subprocess execution and generated JSON output.
- Implement an admission extraction service that returns the shared result
  contract.
- Keep `process_admissions(records, reference_date=...)` as the persistence
  function.
- Update the command to parse arguments and delegate to the service.
- Preserve existing CLI options and non-zero failure behavior.

## Suggested files

Prefer no more than 6 changed files.

Likely files:

- `apps/admissions/services.py` or new `apps/admissions/extraction.py`
- `apps/admissions/management/commands/extract_admissions.py`
- shared ingestion helper module if a small adjustment is needed
- focused admission tests
- `openspec/changes/extract-admission-death-services/tasks.md`

## Constraints

- Do not modify discharge-related code in this change.
- Do not modify death extraction in this slice.
- Do not change the Playwright automation script.
- Do not implement historical recovery orchestration.
- Keep credentials out of returned metrics, stage details, and logs.

## Validation

Run focused admission tests. If time permits, run:

```bash
./scripts/test-in-container.sh unit
```

## Required report

Create `/tmp/sirhosp-slice-S3-report.md` with before/after snippets showing the
command wrapper and new service entry point.
