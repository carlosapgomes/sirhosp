# SLICE TC-S1 - Fix revealed mypy errors

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/fix-revealed-typecheck-errors/proposal.md`
- `openspec/changes/fix-revealed-typecheck-errors/design.md`
- `openspec/changes/fix-revealed-typecheck-errors/specs/typecheck-health/spec.md`
- `openspec/changes/fix-revealed-typecheck-errors/tasks.md`

Implement only this slice. Do not archive this change or the historical
extraction changes.

## Branch protocol

Work on a dedicated branch:

```bash
git switch -c change/fix-revealed-typecheck-errors
```

If the branch already exists, use:

```bash
git switch change/fix-revealed-typecheck-errors
```

Do not implement this slice directly on `main`.

## Objective

Fix the four mypy errors revealed after the duplicate-module issue was resolved:

- `tests/unit/test_discharge_persistence_hardening.py:51`
- `tests/unit/test_discharge_extraction_service.py:61`
- `apps/services_portal/views.py:2072`
- `apps/services_portal/views.py:2108`

The goal is for the official typecheck gate to pass without broad suppressions.

## Suggested files

Prefer no more than 4 changed Python files.

Likely files:

- `tests/unit/test_discharge_persistence_hardening.py`
- `tests/unit/test_discharge_extraction_service.py`
- `apps/services_portal/views.py`

Only touch additional files if required by focused tests or a minimal typing
helper.

## Required behavior

Implement and test all of the following:

1. The official typecheck gate no longer reports the four revealed errors.
2. Discharge unit-test assertions remain behaviorally equivalent.
3. Services portal view output/data shape remains behaviorally equivalent.
4. No broad mypy excludes, blanket ignores, or unrelated `# type: ignore`
   comments are added.
5. No historical recovery or extraction orchestration behavior changes.
6. No migrations, Celery, Redis, or Playwright script changes.

## Guardrails

- Do not weaken tests merely to satisfy mypy.
- Do not add `# noqa` or `# type: ignore` unless narrowly justified in the
  report and no cleaner alternative exists.
- Do not touch `apps/discharges/services.py`.
- Do not touch the historical recovery command unless typecheck directly
  reports it, which is not expected.
- Do not address unrelated integration-test failures in this slice.
- Use synthetic/anonymized test data only.

## Validation

Run baseline typecheck before editing if practical, then final commands:

```bash
uv run ruff check \
  tests/unit/test_discharge_persistence_hardening.py \
  tests/unit/test_discharge_extraction_service.py \
  apps/services_portal/views.py
uv run pytest -q \
  tests/unit/test_discharge_persistence_hardening.py \
  tests/unit/test_discharge_extraction_service.py
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh typecheck
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  openspec/changes/fix-revealed-typecheck-errors/proposal.md \
  openspec/changes/fix-revealed-typecheck-errors/design.md \
  openspec/changes/fix-revealed-typecheck-errors/tasks.md \
  openspec/changes/fix-revealed-typecheck-errors/specs/typecheck-health/spec.md
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  openspec/changes/fix-revealed-typecheck-errors/slice-prompts/SLICE-TC-S1.md
openspec validate fix-revealed-typecheck-errors --type change --strict
```

Host-only commands are diagnostic only; official evidence comes from the
container scripts above.

If services portal view tests are identifiable, run focused tests for them and
record the command/result. If no focused test is practical, explain why in the
report and rely on unit/typecheck plus unchanged output shape reasoning.

## Required report

Create `/tmp/sirhosp-slice-TC-S1-report.md` with:

- summary of the cleanup;
- baseline typecheck errors reproduced;
- files changed;
- before/after snippets for production files, if any;
- commands executed and results;
- confirmation that no historical recovery/extraction behavior was changed;
- note about unrelated integration-test caveats if encountered;
- risks, pending work, and next suggested step.

Commit the implementation after validation with a clear message, then stop.
