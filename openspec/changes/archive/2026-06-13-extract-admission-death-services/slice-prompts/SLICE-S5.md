# SLICE S5 - Death extraction service and command wrapper

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/extract-admission-death-services/proposal.md`
- `openspec/changes/extract-admission-death-services/design.md`
- `openspec/changes/extract-admission-death-services/specs/historical-extraction-services/spec.md`
- `openspec/changes/extract-admission-death-services/specs/ingestion-run-observability/spec.md`
- `openspec/changes/extract-admission-death-services/tasks.md`
- Slice reports S1-S4 if available.

Implement only Slice S5. Do not start S6.

## Branch protocol

Continue working on the dedicated branch for this OpenSpec change:

```bash
git switch change/extract-admission-death-services
```

If the branch does not exist yet, create it with `git checkout -b
change/extract-admission-death-services`. Do not implement this slice directly
on `main`.

## Objective

Move `extract_deaths` orchestration into a Python-callable service and keep the
existing command as a compatible wrapper.

## Current code to inspect

- `apps/deaths/management/commands/extract_deaths.py`
- `apps/deaths/services.py`
- `apps/ingestion/extractors/subprocess_utils.py`
- admission service implementation from S3 as the pattern to follow

## Suggested scope

- Add tests that mock subprocess execution and generated JSON output.
- Implement a death extraction service that returns the shared result contract.
- Keep `process_deaths(records, reference_date=...)` as the persistence
  function.
- Update the command to parse arguments and delegate to the service.
- Preserve existing CLI options and non-zero failure behavior.

## Suggested files

Prefer no more than 6 changed files.

Likely files:

- `apps/deaths/services.py` or new `apps/deaths/extraction.py`
- `apps/deaths/management/commands/extract_deaths.py`
- shared ingestion helper module if a small adjustment is needed
- focused death tests
- `openspec/changes/extract-admission-death-services/tasks.md`

## Constraints

- Do not modify discharge-related code in this change.
- Do not modify admissions except for tiny shared-helper fixes if unavoidable.
- Do not change the Playwright automation script.
- Do not implement historical recovery orchestration.
- Keep credentials out of returned metrics, stage details, and logs.

## Validation

Run focused death tests. If time permits, run:

```bash
./scripts/test-in-container.sh unit
```

## Required report

Create `/tmp/sirhosp-slice-S5-report.md` with before/after snippets showing the
command wrapper and new service entry point.
