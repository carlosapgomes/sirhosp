# SLICE S2 - Shared execution helpers

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/extract-admission-death-services/proposal.md`
- `openspec/changes/extract-admission-death-services/design.md`
- `openspec/changes/extract-admission-death-services/tasks.md`
- `openspec/changes/extract-admission-death-services/slice-prompts/SLICE-S1.md`
- The implementation and report from Slice S1, especially
  `/tmp/sirhosp-slice-S1-report.md` if available.

Implement only Slice S2. Do not start S3.

## Branch protocol

Continue working on the dedicated branch for this OpenSpec change:

```bash
git switch change/extract-admission-death-services
```

If the branch does not exist yet, create it with `git checkout -b
change/extract-admission-death-services`. Do not implement this slice directly
on `main`.

## Objective

Add focused helper functions for mechanics shared by admission and death
historical extraction services.

## Suggested scope

Add tests first for helpers covering:

- safe source-system credential resolution from settings/environment;
- stage metric creation for an `IngestionRun`;
- marking an `IngestionRun` as succeeded or failed;
- safe failure details that do not expose credentials.

Then implement the smallest helper module needed by the tests.

## Suggested files

Prefer no more than 5 changed files.

Likely files:

- shared module from Slice S1, or a sibling helper module under
  `apps/ingestion/`
- `tests/unit/test_historical_extraction_helpers.py`
- `openspec/changes/extract-admission-death-services/tasks.md`

## Constraints

- Do not modify discharge-related code in this change.
- Do not refactor `extract_admissions.py` or `extract_deaths.py` yet.
- Do not create a large framework or class hierarchy.
- Do not log or persist source-system passwords.
- Keep subprocess execution outside database transactions.

## Validation

Run focused helper tests and, if practical, the unit suite:

```bash
./scripts/test-in-container.sh unit
```

## Required report

Create `/tmp/sirhosp-slice-S2-report.md` with required slice evidence and note
any helper API decisions that S3 must follow.
