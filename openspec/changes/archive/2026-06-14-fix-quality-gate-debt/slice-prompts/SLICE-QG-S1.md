# SLICE QG-S1 - Fix pre-existing quality gate debt

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/fix-quality-gate-debt/proposal.md`
- `openspec/changes/fix-quality-gate-debt/design.md`
- `openspec/changes/fix-quality-gate-debt/specs/quality-gate-health/spec.md`
- `openspec/changes/fix-quality-gate-debt/tasks.md`

Implement only this cleanup slice. Do not archive this change or any historical
extraction change.

## Branch protocol

Work on a dedicated branch:

```bash
git switch -c change/fix-quality-gate-debt
```

If the branch already exists, use:

```bash
git switch change/fix-quality-gate-debt
```

Do not implement this slice directly on `main`.

## Objective

Remove the known pre-existing quality-gate debt that blocked clean final
validation after Change 3:

1. stale inpatient report unit test failure;
2. services portal lint failures;
3. mypy duplicate-module issue around services portal sector tests.

## Known starting failures

Verify these before editing; do not assume the exact output is unchanged:

- unit failure:
  `test_reports_only_active_admissions_without_events_in_last_72h`;
- lint failure: long route line in `apps/services_portal/urls.py`;
- lint failures: two unused variables in tests, including ingestion metrics and
  stale inpatient command tests;
- typecheck failure: duplicate module involving
  `tests/unit/test_services_portal_sectors.py`.

## Suggested files

Prefer no more than 6 changed files unless the mypy fix requires package marker
files.

Likely files:

- `apps/services_portal/urls.py`
- `tests/integration/test_services_portal_ingestion_metrics_failures_tab.py`
- `tests/unit/test_report_suspected_stale_inpatients_command.py`
- possible management command behind `report_suspected_stale_inpatients`
- possible package/config file for the mypy duplicate-module fix

## Required behavior

Implement and test all of the following:

1. The stale inpatient report test passes without weakening clinical semantics.
2. Active patients with stale or missing events remain reportable when expected.
3. Recently admitted or recently evolved patients remain excluded when expected.
4. Services portal URL behavior remains unchanged.
5. Ruff reports no errors for the changed files.
6. The official typecheck gate no longer stops on duplicate module discovery.
7. No migrations, Celery, Redis, Playwright script changes, or extraction
   behavior changes are introduced.

## Guardrails

- Do not skip, xfail, or delete the failing stale inpatient test.
- Do not add broad mypy excludes or blanket ignores.
- Do not use `# noqa` or `# type: ignore` unless there is a narrow documented
  reason and no cleaner alternative.
- Do not touch `apps/discharges/services.py`.
- Do not change historical recovery command behavior.
- Use synthetic/anonymized test data only.
- Keep the diff narrow; do not run broad formatters on unrelated files.

## Validation

Run baseline commands before editing if practical, then final commands after
implementation:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  openspec/changes/fix-quality-gate-debt/proposal.md \
  openspec/changes/fix-quality-gate-debt/design.md \
  openspec/changes/fix-quality-gate-debt/tasks.md \
  openspec/changes/fix-quality-gate-debt/specs/quality-gate-health/spec.md \
  openspec/changes/fix-quality-gate-debt/slice-prompts/SLICE-QG-S1.md
openspec validate fix-quality-gate-debt --type change --strict
```

Focused diagnostic commands are encouraged before full gates, for example:

```bash
uv run pytest -q tests/unit/test_report_suspected_stale_inpatients_command.py
uv run ruff check apps/services_portal/urls.py \
  tests/integration/test_services_portal_ingestion_metrics_failures_tab.py \
  tests/unit/test_report_suspected_stale_inpatients_command.py
```

Host-only commands are diagnostic only; official evidence comes from the
container scripts above.

## Required report

Create `/tmp/sirhosp-slice-QG-S1-report.md` with:

- summary of the cleanup;
- baseline failures reproduced;
- files changed;
- before/after snippets for production files, if any;
- commands executed and results;
- confirmation that no historical recovery/extraction behavior was changed;
- risks, pending work, and next suggested step.

Commit the implementation after validation with a clear message, then stop.
