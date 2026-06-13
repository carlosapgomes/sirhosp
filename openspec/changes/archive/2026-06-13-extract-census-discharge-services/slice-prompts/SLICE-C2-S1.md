# SLICE C2-S1 - Official census extraction service and command wrapper

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/extract-census-discharge-services/proposal.md`
- `openspec/changes/extract-census-discharge-services/design.md`
- `openspec/changes/extract-census-discharge-services/specs/historical-extraction-services/spec.md`
- `openspec/changes/extract-census-discharge-services/specs/ingestion-run-observability/spec.md`
- `openspec/changes/extract-census-discharge-services/tasks.md`

Implement only Slice C2-S1. Do not start the next slice.

## Branch protocol

Work in a dedicated branch for this OpenSpec change:

```bash
git switch -c change/extract-census-discharge-services
```

If the branch already exists, switch to it instead of creating a new branch. Do
not implement this slice directly on `main`.

## Objective

Extract official census orchestration from the management command into a
Python-callable service while preserving CLI compatibility.

## Suggested scope

Use TDD. Add characterization tests with mocked credentials, mocked
subprocess execution, and synthetic official census JSON output. Then implement
the minimal service and update the command wrapper.

## Suggested files

Prefer no more than 5 changed files unless tests require a small fixture helper.

Likely files:

- `apps/census/services.py` or a focused new census extraction module
- `apps/census/management/commands/extract_official_census.py`
- `tests/unit/test_official_census_extraction_service.py`
- optional focused command compatibility tests

## Constraints

- Do not modify admission/death behavior unless a tiny shared helper fix is
  required by this slice and covered by tests.
- Do not modify `apps/discharges/services.py` in this change.
- Do not start `recover_historical_data`.
- Do not add Celery, Redis, or new orchestration infrastructure.
- Preserve Playwright scripts as subprocess boundaries.
- Do not persist or log real credentials or real patient data.
- Use synthetic/anonymized fixtures only.

## Validation

Run at least:

```bash
./scripts/test-in-container.sh unit
openspec validate extract-census-discharge-services --type change --strict
```

If `./scripts/test-in-container.sh unit` runs the whole unit suite instead of
focused paths, document that behavior. You may add a host-only diagnostic
`uv run pytest -q <focused paths>` result, but it is not the official gate.

## Required report

Create `/tmp/sirhosp-slice-C2-S1-report.md` with:

- summary of the slice;
- acceptance checklist;
- files changed;
- before/after snippets for each changed production file;
- commands executed and results;
- risks, pending work, and next suggested slice.
