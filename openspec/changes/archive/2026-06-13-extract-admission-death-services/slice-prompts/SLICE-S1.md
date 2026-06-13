# SLICE S1 - Shared extraction contract

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/extract-admission-death-services/proposal.md`
- `openspec/changes/extract-admission-death-services/design.md`
- `openspec/changes/extract-admission-death-services/specs/historical-extraction-services/spec.md`
- `openspec/changes/extract-admission-death-services/specs/ingestion-run-observability/spec.md`
- `openspec/changes/extract-admission-death-services/tasks.md`

Implement only Slice S1. Do not start S2.

## Branch protocol

Work in a dedicated branch for this OpenSpec change:

```bash
git checkout -b change/extract-admission-death-services
```

If the branch already exists, switch to it instead of creating a new branch. Do
not implement this slice directly on `main`.

## Objective

Create the minimal shared result contract for historical extraction services.
This slice must not change current management command behavior.

## Suggested scope

- Add tests for a shared result object representing:
  - extraction type;
  - target start/end dates or target date;
  - success/failure;
  - metrics dictionary;
  - failure reason;
  - safe error message;
  - optional `IngestionRun` id.
- Implement the smallest contract needed by the tests.

## Suggested files

Prefer no more than 4 changed files.

Likely files:

- `apps/ingestion/historical_extraction.py` or similar new module
- `tests/unit/test_historical_extraction_contract.py`
- `openspec/changes/extract-admission-death-services/tasks.md`

## Constraints

- Do not modify discharge-related code in this change.
- Do not modify `extract_admissions.py` or `extract_deaths.py` in this slice.
- Do not create `recover_historical_data`.
- Do not add database models.
- Do not include credentials or patient data in test fixtures.

## Validation

Run focused tests, preferably through the container wrapper when practical:

```bash
./scripts/test-in-container.sh unit
```

If using a narrower host-only diagnostic command, clearly mark it as diagnostic
in the report.

## Required report

Create `/tmp/sirhosp-slice-S1-report.md` with:

- summary;
- acceptance checklist;
- files changed;
- before/after snippets;
- commands executed and results;
- risks and next suggested step.
