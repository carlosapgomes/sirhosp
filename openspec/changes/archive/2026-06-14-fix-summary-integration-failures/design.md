# Fix Summary Integration Failures Design

## Context

After the historical extraction and quality-gate cleanup sequence, the unit,
lint, and typecheck gates pass. The integration gate still reports ten failures
limited to summary HTTP tests:

- nine failures in `test_summary_cost_visibility_http.py`, where status/read
  pages no longer display expected cost and phase reuse content;
- one failure in `test_summary_http.py`, where the status page no longer shows
  the admission reference expected by the test.

These failures predate the latest extraction work. They likely relate to summary
pipeline traceability changes, template changes, or stale fixtures that create
`SummaryPipelineRun` rows without linking them to the displayed `SummaryRun`.

## Goals / Non-Goals

**Goals:**

- Make `./scripts/test-in-container.sh integration` pass for the ten summary
  failures.
- Preserve operator-visible cost information on summary status/read pages.
- Preserve admission identity/context on the run status page.
- Keep test updates aligned with current specs; do not weaken assertions merely
  to make tests pass.
- Keep changes narrow and evidence-driven.

**Non-Goals:**

- Do not change historical extraction or recovery command behavior.
- Do not alter summary generation pipeline semantics beyond page/query fixes
  needed for the failing tests.
- Do not add migrations, Celery, Redis, or Playwright changes.
- Do not broad-refactor summary views/templates outside the failing surface.

## Decisions

### Decision: Diagnose fixtures versus production regression first

The implementer MUST inspect the current summary specs and production query path
before editing tests. If a failing fixture creates an impossible or legacy state,
update the fixture to match current behavior. If the page lost required operator
information, fix the view/template.

Alternative considered: update assertions to match current output. This is
rejected unless the current output is explicitly correct under the specs.

### Decision: Respect explicit SummaryRun linkage

The current `summary-llm-traceability` spec says pipeline runs are linked to the
originating `SummaryRun` and views query by that link rather than by latest
admission. Integration fixtures SHOULD create linked records if testing cost
visibility for a specific displayed run.

Alternative considered: make views fall back to latest pipeline by admission in
all cases. This can be useful for legacy display, but must not override the
explicit linked-run semantics without a spec update.

### Decision: Preserve readable operator output

If production templates are changed, they SHOULD show values already persisted
on `SummaryPipelineRun` and existing admission identifiers without exposing raw
LLM payloads or sensitive prompt content.

Alternative considered: hide cost/admission details and rely on admin logs. This
is rejected because existing specs and tests require operator-visible summary
context.

## Risks / Trade-offs

- Updating stale fixtures may hide a real UI regression. Mitigation: verify the
  spec and keep assertions for concrete costs, reuse indicators, and admission
  reference.
- Changing templates can affect user-facing pages. Mitigation: run focused HTTP
  tests and the full integration gate.
- Legacy pipeline runs without `summary_run` may still exist. Mitigation: if a
  fallback is added, test it explicitly and keep linked-run lookup primary.
