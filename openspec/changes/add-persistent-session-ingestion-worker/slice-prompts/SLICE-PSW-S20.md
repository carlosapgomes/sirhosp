# SLICE PSW-S20: Action-First Real Evolution Dispatch

## Handoff for a Context-Zero Implementer

Implement only PSW-S20 after PSW-S19 is committed. Read project instructions,
all change artifacts, PSW-S19 report, adapter, bridge, legacy navigation,
persistent PDF flow, command full-sync, `path2.py`, and focused tests. Start
clean.

The real legacy UI has no reloadable evolution deep link. The real handle must
not try `/evolutions/...` before action navigation.

## Mandatory DeepSeek4-Flash Protocol

1. Record `BASE_REF`, clean status, and requirement matrix.
2. Run official unit baseline before editing and record exit/summary.
3. Write a real-like failing adapter test first; capture RED proving action
   navigation was not reached.
4. Implement minimum GREEN; keep stub compatibility explicit.
5. Run and interpret URL/action/timeout inspections.
6. Run every official gate.
7. Mark tasks/report/commit/push only after complete evidence; then stop.

## Objective

Make evolution extraction action-first for the real persistent handle, while
retaining URL/container behavior only for explicit test/stub capabilities.
Required date/report steps must fail safely rather than continue with defaults.

## Requirements

- **R1:** Give real and stub/test sessions explicit capabilities; do not infer
  real behavior from an arbitrary method accidentally present on a mock.
- **R2:** For the real handle, call legacy evolution actions without first
  calling `open_tab` on a synthetic/direct evolution URL.
- **R3:** Preserve explicit JSON/pre fast paths only when their page state was
  reached legitimately; they must not bypass required real navigation.
- **R4:** If required date inputs cannot be filled, raise a typed sanitized
  failure and generate no report/persistence.
- **R5:** Distinguish no-evolutions from report timeout; timeout must use the
  shared timeout taxonomy from PSW-S17.
- **R6:** Propagate the requested timeout to action waits and downloads.
- **R7:** Error/stage messages must not contain patient identifiers, URLs with
  identifiers, raw HTML, credentials, or PDF bytes.
- **R8:** Preserve stub tests and current worker behavior.

## Expected Scope

Target maximum: 7 versioned files including `tasks.md`.

Expected: persistent adapter, bridge/navigation, typed errors only if required,
focused tests, command test only for full-sync wiring, and `tasks.md`.

Forbidden: models/migrations, chunking implementation (PSW-S21), PDF form POST
(PSW-S22), demographics/admissions persistence, rollout enablement.

## TDD

### RED

Mandatory real-like test:

```text
session exposes real action capability
open_tab would return False/fail
extract_evolutions(...)
-> action method called
-> open_tab not called
```

Also test required-date failure, report timeout classification, no-evolutions,
and legitimate fast path behavior.

### GREEN

Use a small explicit capability/boundary. Reorder flow without duplicating
normalization or persistence.

### REFACTOR

Remove obsolete real URL assumptions and misleading comments. Do not delete
explicit synthetic test support that remains useful.

## Mandatory Inspection Checks

```bash
rg -n "evolutions/|base_evolutions_url|open_tab|legacy_actions" \
  apps/ingestion/extractors/persistent_extraction_adapter.py \
  apps/ingestion/extractors/real_handle_bridge.py
rg -n "fill_evolution_dates|except Exception|return \[\]|timeout" \
  apps/ingestion/extractors/legacy_navigation.py \
  apps/ingestion/extractors/real_handle_bridge.py
```

Classify each URL fallback and each swallowed exception. No required real action
may silently continue.

## Binary Success Criteria

- [ ] Real-like test reaches action path with zero direct URL opens.
- [ ] Required date-fill failures stop report generation.
- [ ] No-evolutions and timeout are distinguishable.
- [ ] Timeout value reaches waits/downloads.
- [ ] Fast paths remain only in valid reached states.
- [ ] No identifying URL appears in stored errors.
- [ ] Current/stub regressions pass.
- [ ] All official gates pass.

## Self-Evaluation Gates

1. Can real extraction fail before the action method because of direct URL
   navigation?
2. Can missing date inputs produce a report for the wrong period?
3. Can report timeout be returned as an empty successful window?
4. Are MagicMock auto-created capabilities able to change dispatch?
5. Did this slice add chunking or form download prematurely?

Required answers: no, no, no, no, no.

## Validation

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate add-persistent-session-ingestion-worker --strict
git diff --name-only "$BASE_REF"...HEAD -- '*.md' | xargs -r markdownlint-cli2
```

## Required Report

Create `/tmp/sirhosp-slice-PSW-S20-report.md` with protocol evidence, dispatch
sequence before/after, RED/GREEN, timeout matrix, inspections, command results,
files, risks, and verifier handoff.

Final prompt: implement only PSW-S20. Any direct real URL prerequisite,
swallowed required action, identifier leak, or missing gate makes the slice
incomplete.
