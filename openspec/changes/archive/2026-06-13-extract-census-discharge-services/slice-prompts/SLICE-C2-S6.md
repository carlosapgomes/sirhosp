# SLICE C2-S6 - Change validation and Change 3 handoff

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/extract-census-discharge-services/proposal.md`
- `openspec/changes/extract-census-discharge-services/design.md`
- `openspec/changes/extract-census-discharge-services/specs/historical-extraction-services/spec.md`
- `openspec/changes/extract-census-discharge-services/specs/ingestion-run-observability/spec.md`
- `openspec/changes/extract-census-discharge-services/tasks.md`

Implement only Slice C2-S6. Do not start the next slice.

## Branch protocol

Continue working on the dedicated branch for this OpenSpec change:

```bash
git switch change/extract-census-discharge-services
```

If the branch does not exist yet, stop and ask for the previous slice handoff.
Do not implement this slice directly on `main`.

## Objective

Perform final validation for Change 2 and prepare the handoff for
`add-historical-recovery-command`.

## Suggested scope

Do not add new production behavior unless a validation failure requires a tiny
fix. Update task checkboxes, write `change-3-handoff.md`, and document validation
results and known unrelated failures.

## Suggested files

Prefer no more than 5 changed files unless tests require a small fixture helper.

Likely files:

- `openspec/changes/extract-census-discharge-services/tasks.md`
- `openspec/changes/extract-census-discharge-services/change-3-handoff.md`
- optional focused tests only if final validation exposes a small gap

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
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
openspec validate extract-census-discharge-services --type change --strict
```

If `./scripts/test-in-container.sh unit` runs the whole unit suite instead of
focused paths, document that behavior. You may add a host-only diagnostic
`uv run pytest -q <focused paths>` result, but it is not the official gate.

## Required report

Create `/tmp/sirhosp-slice-C2-S6-report.md` with:

- summary of the slice;
- acceptance checklist;
- files changed;
- before/after snippets for each changed production file;
- commands executed and results;
- risks, pending work, and next suggested slice.
