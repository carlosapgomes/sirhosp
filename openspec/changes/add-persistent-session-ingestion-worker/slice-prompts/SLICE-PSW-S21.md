# SLICE PSW-S21: Canonical Chunking and Multi-Admission Flow

## Handoff for a Context-Zero Implementer

Implement only PSW-S21 after PSW-S20 is committed. Read project instructions,
all change artifacts, PSW-S20 report, canonical
`automation/source_system/medical_evolution/chunking.py`, `path2.py` admission
selection/iteration, persistent navigation/bridge/adapter, gap planner, and
focused tests. Start clean.

## Mandatory DeepSeek4-Flash Protocol

1. Record `BASE_REF`, clean status, and requirement matrix.
2. Run official unit baseline before editing; record exact summary/exit.
3. Write chunk and multi-admission tests first and capture expected RED.
4. Implement minimum GREEN by reusing the canonical chunking module.
5. Inspect for duplicate/dead chunking and unbounded windows.
6. Run every official validation command.
7. Update tasks/report/commit/push only when complete and stop.

## Objective

For each full-sync gap, select every overlapping admission and extract bounded,
progressing 15-day chunks with canonical overlap through the same authenticated
session.

## Requirements

- **R1:** Reuse `build_chunks_for_interval` from the canonical dependency-free
  chunking module; do not copy its algorithm.
- **R2:** Every chunk spans at most 15 inclusive calendar days with canonical
  one-day overlap and deterministic boundaries.
- **R3:** Guarantee progress and termination for one-day, exact-15-day,
  16-day, and final-single-day intervals.
- **R4:** Remove the duplicate unused persistent helper after migrating callers.
- **R5:** Select all admissions overlapping the requested gap with deterministic
  ordering and keep each real admission key on its events.
- **R6:** Restore/reopen the admissions list and correct detail/report state
  between admissions and chunks without new browser/context/login.
- **R7:** A genuine empty chunk returns no fake events and does not discard
  events already collected from earlier chunks/admissions.
- **R8:** A failure records the responsible bounded window without patient data
  and follows existing retry/cleanup semantics.
- **R9:** Preserve current worker behavior and gap planning.

## Expected Scope

Target maximum: 7 versioned files including `tasks.md`.

Expected: canonical chunk import/boundary, persistent legacy navigation/bridge,
focused chunk/navigation/adapter tests, and `tasks.md`.

Forbidden: editing canonical chunking behavior unless a characterization test
proves an existing bug affecting both paths; models/migrations; PDF download
mechanism; demographics/admissions persistence; rollout docs.

## TDD

### RED

Add table-driven chunk cases and a bounded anti-hang test. Add two overlapping
admissions with multiple chunks, an empty middle/final chunk, and correct key
association. Initial RED must expose unbounded/no chunking or duplicate helper
behavior.

### GREEN

Delegate to canonical chunking and implement the smallest state-restoration loop.

### REFACTOR

Delete duplicate dead helper/tests/comments. Keep iteration logic explicit and
avoid a generic workflow engine.

## Mandatory Inspection Checks

```bash
rg -n "build_chunks_for_interval|_CHUNK_DAYS|_CHUNK_OVERLAP|timedelta.*CHUNK" \
  apps/ingestion automation/source_system/medical_evolution
rg -n "for .*admission|for .*chunk|admission_key|open_internacao_detail" \
  apps/ingestion/extractors/legacy_navigation.py \
  apps/ingestion/extractors/real_handle_bridge.py
```

Expected: one canonical algorithm; no unused duplicate; every source report
window comes from a bounded chunk.

## Binary Success Criteria

- [ ] Boundary table and anti-hang tests pass.
- [ ] No chunk exceeds 15 days.
- [ ] Multiple admissions and chunks are all processed deterministically.
- [ ] Event admission keys are correct.
- [ ] Empty later chunks preserve earlier results.
- [ ] Same browser/session is retained.
- [ ] Duplicate helper is removed.
- [ ] All official gates pass.

## Self-Evaluation Gates

1. Is any chunking algorithm copied into `apps/ingestion`?
2. Can `chunk_start` repeat forever at `end`?
3. Can one empty chunk erase accumulated events?
4. Can events from two admissions lose their distinct keys?
5. Can iteration create a new browser/context/login?

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

Create `/tmp/sirhosp-slice-PSW-S21-report.md` with protocol evidence, complete
chunk boundary table, multi-admission trace, RED/GREEN, inspections,
commands/exit codes, files, risks, and verifier handoff.

Final prompt: implement only PSW-S21. Any unbounded window, duplicate algorithm,
hang risk, lost prior event, or missing gate means incomplete.
