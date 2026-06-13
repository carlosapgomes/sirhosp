# SLICE C2-S4 - Discharge persistence hardening

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/extract-census-discharge-services/proposal.md`
- `openspec/changes/extract-census-discharge-services/design.md`
- `openspec/changes/extract-census-discharge-services/specs/historical-extraction-services/spec.md`
- `openspec/changes/extract-census-discharge-services/specs/ingestion-run-observability/spec.md`
- `openspec/changes/extract-census-discharge-services/tasks.md`

Implement only Slice C2-S4. Do not start the next slice.

## Branch protocol

Continue working on the dedicated branch for this OpenSpec change:

```bash
git switch change/extract-census-discharge-services
```

If the branch does not exist yet, stop and ask for the previous slice handoff.
Do not implement this slice directly on `main`.

## Objective

Harden discharge report persistence so repeated execution and empty output are
deterministic.

## Suggested scope

Add failing tests first. Cover repeated processing of the same synthetic XLS,
zero-output behavior, and daily count persistence. Confirm no changes were made
to `apps/discharges/services.py`.

## Suggested files

Prefer no more than 5 changed files unless tests require a small fixture helper.

Likely files:

- `apps/discharges/extraction_service.py`
- `tests/unit/test_discharge_persistence_hardening.py`
- optional existing discharge extraction service tests

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
git diff --exit-code -- apps/discharges/services.py
openspec validate extract-census-discharge-services --type change --strict
```

If `./scripts/test-in-container.sh unit` runs the whole unit suite instead of
focused paths, document that behavior. You may add a host-only diagnostic
`uv run pytest -q <focused paths>` result, but it is not the official gate.

## Required report

Create `/tmp/sirhosp-slice-C2-S4-report.md` with:

- summary of the slice;
- acceptance checklist;
- files changed;
- before/after snippets for each changed production file;
- commands executed and results;
- risks, pending work, and next suggested slice.
