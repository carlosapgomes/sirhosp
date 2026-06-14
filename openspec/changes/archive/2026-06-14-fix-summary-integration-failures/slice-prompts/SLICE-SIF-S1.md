# SLICE SIF-S1 - Fix summary integration failures

## Handoff for context-zero executor

Read these files first:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/fix-summary-integration-failures/proposal.md`
- `openspec/changes/fix-summary-integration-failures/design.md`
- `openspec/changes/fix-summary-integration-failures/specs/summary-llm-traceability/spec.md`
- `openspec/changes/fix-summary-integration-failures/tasks.md`
- `openspec/specs/summary-llm-traceability/spec.md`
- `openspec/specs/admission-progressive-summary/spec.md`

Implement only this slice. Do not archive this change or any recovery/extraction
change.

## Branch protocol

Start from a clean working tree. If `README.md` or any unrelated file is
modified, stop and ask for that change to be committed or stashed first.

Work on a dedicated branch:

```bash
git switch -c change/fix-summary-integration-failures
```

If the branch already exists, use:

```bash
git switch change/fix-summary-integration-failures
```

Do not implement this slice directly on `master`.

## Objective

Fix the ten known integration failures in summary HTTP coverage:

- nine failures in `tests/integration/test_summary_cost_visibility_http.py`;
- one failure in `tests/integration/test_summary_http.py` for missing admission
  reference on the summary status page.

The goal is for `./scripts/test-in-container.sh integration` to pass.

## Suggested files

Prefer no more than 6 changed implementation/test files.

Likely files:

- `tests/integration/test_summary_cost_visibility_http.py`
- `tests/integration/test_summary_http.py`
- summary views/templates under `apps/summaries/` or `templates/`

Only touch additional files if needed by the diagnosis.

## Required behavior

Implement and test all of the following:

1. Summary status page displays linked pipeline phase costs in USD.
2. Summary status page displays BRL conversion or a clear no-rate fallback.
3. Summary read page displays linked pipeline total cost in USD and BRL/fallback.
4. Phase-1 reuse remains visible on status/read pages.
5. Summary status page displays patient name and admission source reference.
6. Tests use current linked `SummaryRun` to `SummaryPipelineRun` semantics.
7. Assertions are not weakened merely to make tests pass.
8. No historical recovery or extraction behavior changes are introduced.
9. No migrations, Celery, Redis, or Playwright script changes are introduced.

## Diagnostic guidance

Before changing code, inspect whether the failing cost tests create
`SummaryPipelineRun` rows linked to the `SummaryRun` being displayed. The current
spec says views query by explicit `summary_run` linkage rather than by
`admission + latest`. If fixtures are stale, update fixtures while preserving
cost/reuse assertions.

If fixtures are already correct and the page still omits costs, fix the
production view/template. If legacy unlinked pipeline runs need a fallback,
implement it narrowly and test both linked and fallback behavior.

For the admission reference failure, prefer restoring operator-visible admission
context in the template/context instead of deleting the assertion.

## Guardrails

- Do not skip, xfail, or delete the failing integration tests.
- Do not remove cost, reuse, or admission-context assertions.
- Do not expose raw LLM prompts, raw payloads, or sensitive data on public pages.
- Do not touch `apps/discharges/services.py`.
- Do not touch `recover_historical_data` unless unexpectedly required, which
  should be treated as a blocker and reported first.
- Keep the diff narrow; do not run broad formatters on unrelated files.

## Validation

Run baseline focused tests before editing if practical, then final commands:

```bash
uv run pytest -q tests/integration/test_summary_cost_visibility_http.py \
  tests/integration/test_summary_http.py::TestSummaryRunStatusView
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  openspec/changes/fix-summary-integration-failures/proposal.md \
  openspec/changes/fix-summary-integration-failures/design.md \
  openspec/changes/fix-summary-integration-failures/tasks.md
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  openspec/changes/fix-summary-integration-failures/specs/summary-llm-traceability/spec.md
npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
  openspec/changes/fix-summary-integration-failures/slice-prompts/SLICE-SIF-S1.md
openspec validate fix-summary-integration-failures --type change --strict
```

Host-only commands are diagnostic only; official evidence comes from the
container scripts above.

## Required report

Create `/tmp/sirhosp-slice-SIF-S1-report.md` with:

- summary of the cleanup;
- baseline integration failures reproduced;
- root cause classification for fixture staleness versus production regression;
- files changed;
- before/after snippets for production files, if any;
- commands executed and results;
- confirmation that no historical recovery/extraction behavior was changed;
- risks, pending work, and next suggested step.

Commit the implementation after validation with a clear message, then stop.
