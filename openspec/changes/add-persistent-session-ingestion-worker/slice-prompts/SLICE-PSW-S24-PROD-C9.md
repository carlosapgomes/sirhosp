# Slice Prompt — PSW-S24-PROD-C9

## Handoff

Start with zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the active
OpenSpec change `add-persistent-session-ingestion-worker`, and this prompt.
Implement only this production evolution-modal and framed-PDF correction.

## Production evidence

Sanitized live probes isolated three mismatches between the persistent bridge
and the rendered legacy report flow:

1. Both date inputs are present and visible, but Playwright's actionability
   click times out. A direct DOM focus followed by bounded `fill()` succeeds.
2. The visible Visualizar button's coordinate click emits no request. Its
   rendered handler declares a deterministic `PrimeFaces.ab` action; invoking
   that exact action emits one POST and opens the report.
3. The PDF `object[type="application/pdf"]` is inside `frame_pol`, with a
   dynamic-content URL in its `data` attribute. Resolving against the top-level
   page misses it and falls into a stale form-POST path that returns HTML.

All probes used the already-open authenticated handle and emitted only
sanitized structural metadata. No patient data, credentials, URLs, or PDF bytes
were persisted.

## Scope

Maximum six changed files:

1. `apps/ingestion/extractors/legacy_navigation.py`
2. `apps/ingestion/extractors/real_handle_bridge.py`
3. `tests/unit/test_legacy_navigation.py`
4. `tests/unit/test_real_handle_bridge.py`
5. this prompt
6. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`

Do not change the worker command, adapter contracts, queue policy, rollout
defaults, compose files, service definitions, or persistence models.

## Required change

- Focus each present evolution date input with a direct DOM click before its
  existing bounded fill; preserve typed sanitized timeout handling and the
  shared deadline.
- Generate the report with the exact declared PrimeFaces source/form/update
  action rather than a coordinate click; preserve bounded readiness checks and
  sanitized failures.
- Resolve the direct PDF URL from `frame_pol` and against that frame's URL.
  Preserve a top-level fallback for standalone/fake owners and keep every PDF
  operation bounded and in memory.
- Update stateful fakes without weakening end-to-end transition assertions.

## Acceptance

- RED proves the old coordinate-click and top-level-PDF behavior.
- Focused regression files pass.
- A production single-run `full_sync` succeeds through the guarded real command
  after the production checkout is rebuilt from the committed revision.
- The four-row bounded validation then succeeds in operator order through one
  authenticated handle, including the restart/rebootstrap boundary.
- Official unit, quality-gate, integration, OpenSpec strict, and Markdown gates
  pass before rollout status changes.
- Create `/tmp/sirhosp-slice-PSW-S24-PROD-C9-report.md` with sanitized evidence,
  literal before/after fragments, changed files, commands/results, risks, and
  the next step.
