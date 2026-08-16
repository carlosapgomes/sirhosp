# SLICE PSW-S11: Persistent Real Evolution PDF Flow

## Handoff for Context-Zero Executor

You are implementing only slice PSW-S11 for OpenSpec change
`add-persistent-session-ingestion-worker` in SIRHOSP.

Continue on branch:

```bash
git branch --show-current
# expected: feature/add-persistent-session-ingestion-worker
```

Before coding, run:

```bash
git status --short
```

If unrelated changes are present, stop and report. Do not mix this slice with
other features, archived OpenSpec changes, or opportunistic refactors.

## Slice Goal

Make persistent `full_sync` capable of extracting evolutions from the real
legacy PDF report flow using the already-open persistent Playwright session.

This slice starts after PSW-S10. Assume PSW-S10 provides safe single-run manual
controls and authenticated real legacy bootstrap. This slice focuses only on
the evolution report/PDF path.

## Why This Slice Exists

PSW-S9 can translate evolution data from synthetic representative forms:

- `<script id="evolution-data-json">`;
- `<pre class="report-text">`.

The real legacy flow is likely closer to `automation/source_system/medical_evolution/path2.py`:
select an admission, set date filters, generate a report, download/read a PDF,
and parse it into normalized evolution events.

The current subprocess-based extractor launches its own browser. The persistent
worker must not do that. It must reuse the existing `PlaywrightSessionHandle`
and its current browser context.

## Read First

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md` if present
3. `openspec/changes/add-persistent-session-ingestion-worker/proposal.md`
4. `openspec/changes/add-persistent-session-ingestion-worker/design.md`
5. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`
6. `openspec/changes/add-persistent-session-ingestion-worker/specs/`
7. `/tmp/sirhosp-slice-PSW-S9-report.md`
8. `/tmp/sirhosp-slice-PSW-S10-report.md`
9. `apps/ingestion/extractors/real_handle_bridge.py`
10. `apps/ingestion/extractors/playwright_session_handle.py`
11. `apps/ingestion/extractors/persistent_extraction_adapter.py`
12. `apps/ingestion/evolution_ingestion.py`
13. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`
14. `apps/ingestion/extractors/playwright_extractor.py`
15. `automation/source_system/medical_evolution/path2.py`
16. `automation/source_system/medical_evolution/source_system.py`
17. Existing parser and normalization tests for evolutions

## Development Method

Use strict TDD:

1. Add failing tests for a persistent evolution PDF extraction capability using
   fake Playwright pages/frames/downloads and synthetic anonymous PDF/text.
2. Implement the smallest bridge/helper needed to pass the tests.
3. Add command/adapter regression tests proving `full_sync` uses the persistent
   path without subprocess or new browser launches.
4. Refactor only after green tests.

Apply clean code, DRY, and YAGNI:

- reuse stable parsing helpers from `path2.py` or shared modules;
- do not copy large scripts into the worker;
- do not shell out to `path2.py`;
- do not launch a fresh browser, context, or Playwright instance per job;
- keep clinical persistence in `apps.ingestion.evolution_ingestion`;
- keep Playwright details behind the handle/bridge boundary.

## Scope and File Budget

Target maximum changed files: 10.

Expected files:

- a focused persistent PDF extraction helper or bridge update;
- `PlaywrightSessionHandle` only if a minimal capability method is needed;
- `RealHandleBridge` only if it remains the chosen adapter boundary;
- focused unit tests;
- command tests only if wiring changes;
- rollout docs only if status changes.

If full legacy navigation plus PDF parsing cannot fit within 10 files, stop
and report a narrower follow-up slice. Do not fake production readiness.

## Required Behavior

### 1. Reuse the persistent browser/session

The real evolution flow must run through the already-open persistent handle.
It must not:

- call `subprocess`;
- run `path2.py` as a command;
- call `sync_playwright()` again;
- create a fresh browser for each run.

Tests must prove those actions are not used in the persistent path.

### 2. Support the real PDF report path

Implement a minimal vertical path for one admission/window:

- navigate or interact with the existing legacy page as required;
- select or target the admission associated with the gap window;
- apply start/end dates;
- generate the evolution report;
- identify or download the PDF through the existing page/context;
- extract text with existing PyMuPDF/helper logic;
- normalize it into the same evolution event dict shape used by
  `PersistentExtractionAdapter.extract_evolutions()`;
- return an empty list, not success with fake data, when no report data exists.

Use synthetic PDF/text fixtures in tests. Do not add real patient files,
screenshots, cookies, or downloaded PDFs to the repository.

### 3. Preserve fallback strategies

Keep the PSW-S9 lightweight strategies as fast paths where useful:

- `evolution-data-json` script;
- `pre.report-text` content.

Add the PDF flow as a real legacy fallback, not as a replacement that breaks
existing tests.

### 4. Preserve failure semantics

Map failures to the existing extraction taxonomy without leaking sensitive
data:

- timeout waiting for report/download;
- no eligible admission row;
- PDF URL/download unavailable;
- invalid or empty PDF text;
- parser/normalization failure.

The persistent worker must keep current run lifecycle semantics, retries,
stage metrics, cleanup, and session restart rules.

## Acceptance Criteria

- Tests prove the persistent path downloads or reads a PDF using the existing
  handle/context, not a new browser or subprocess.
- Tests prove representative PDF/text is normalized into evolution events with
  the expected keys: `admission_key`, `happened_at`, `event_type`, `content`,
  and `profession`.
- Tests prove `full_sync` persists events through the existing shared service.
- Tests prove JSON/script and `pre.report-text` paths still work.
- Tests prove timeout values reach report/download waits.
- Tests prove failures are sanitized and do not include credentials, cookies,
  raw HTML, or patient-identifying fixture data.
- Tests prove tab cleanup remains cleanup only and not renewal evidence.
- Current subprocess extractor and current worker behavior remain unchanged.
- Rollout docs, if modified, distinguish manual validation from production
  rollout.

## Validation Commands

Run at minimum:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate add-persistent-session-ingestion-worker --strict
```

If Markdown files changed, validate only those files with `markdownlint-cli2`.
Do not run global Markdown formatters or linters that rewrite unrelated files.

## Required Report

Create `/tmp/sirhosp-slice-PSW-S11-report.md` with:

- slice summary;
- chosen PDF extraction approach and rationale;
- acceptance checklist;
- files changed;
- before/after snippets for each changed file;
- commands executed and results;
- branch and `git status --short`;
- manual full-sync smoke command example with placeholders only;
- rollout status after this slice;
- risks, pending items, and suggested next step.

Stop after this slice.
