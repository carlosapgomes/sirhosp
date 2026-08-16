# SLICE PSW-S13: Real Legacy Full-Sync Evolution Navigation

## Executor Profile

This prompt is written for **deepseek4-flash**.

Be literal and conservative:

- implement only this slice;
- do not infer hidden requirements;
- do not broaden scope;
- if a required PSW-S12 artifact is missing, stop and report the blocker;
- prefer small, explicit functions over clever abstractions;
- keep tests deterministic with fake Playwright-like objects;
- never use real legacy credentials, screenshots, PDFs, cookies, raw HTML, or
  patient data in repository files or reports.

## Handoff for Context-Zero Executor

You are implementing only slice PSW-S13 for OpenSpec change
`add-persistent-session-ingestion-worker` in SIRHOSP.

Expected branch:

```bash
git branch --show-current
# expected: feature/add-persistent-session-ingestion-worker
```

Before coding:

```bash
git status --short
```

Stop and report if:

- branch is not `feature/add-persistent-session-ingestion-worker`;
- PSW-S12 is not implemented and committed;
- unrelated modified files are present;
- required files from PSW-S12 cannot be found.

Do not mix this slice with other features, archived OpenSpec changes,
refactors, formatting-only changes, or production rollout work.

## Dependency

PSW-S13 depends on PSW-S12.

PSW-S12 should have:

- removed real-handle dependency on admissions/evolutions URL templates for
  `admissions_only` smoke;
- introduced a minimal real UI navigation boundary modeled after
  `automation/source_system/medical_evolution/path2.py`;
- produced `/tmp/sirhosp-slice-PSW-S12-report.md`.

If these are absent, stop. Do not implement PSW-S12 inside this slice.

## Problem to Fix

The real legacy system is Java/JSP/PrimeFaces. It does not expose reloadable
URLs for patient admissions or evolution extraction.

The current PSW-S11 PDF fallback can fill dates and download a PDF only after a
report page is already open. It does not perform the real UI path required to
reach that report.

The known working reference is the action-based flow in:

```text
automation/source_system/medical_evolution/path2.py
```

Reference flow:

```text
login
-> search patient
-> open Internações
-> choose overlapping admission
-> open Detalhes da Internação
-> click Evolução
-> fill DD/MM/YYYY dates
-> select Crescente
-> visualize report
-> download/read PDF
-> normalize evolutions
```

## Slice Goal

Make one guarded real-handle `full_sync` smoke capable of extracting evolutions
through the real legacy action flow, while reusing the already-open persistent
Playwright session/context.

The result must continue to persist through the existing shared ingestion path.

This remains **manual smoke only**. Do not claim production rollout readiness.

## Non-Goals

Do not:

- implement continuous production rollout;
- add Celery, Redis, queues, or services;
- modify `process_ingestion_runs.py`;
- modify the current subprocess extractor behavior;
- shell out to `path2.py`;
- call `sync_playwright()` again;
- create a fresh browser or context per job;
- save real PDFs, screenshots, HTML, cookies, credentials, or patient data;
- copy the whole `path2.py` script.

## Read First

Read these files before editing:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md` if present
3. `openspec/changes/add-persistent-session-ingestion-worker/proposal.md`
4. `openspec/changes/add-persistent-session-ingestion-worker/design.md`
5. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`
6. `openspec/changes/add-persistent-session-ingestion-worker/specs/`
7. `/tmp/sirhosp-slice-PSW-S12-report.md`
8. `/tmp/sirhosp-slice-PSW-S11-report.md`
9. `apps/ingestion/extractors/legacy_navigation.py` or PSW-S12 equivalent
10. `apps/ingestion/extractors/real_handle_bridge.py`
11. `apps/ingestion/extractors/persistent_evolution_pdf.py`
12. `apps/ingestion/extractors/persistent_extraction_adapter.py`
13. `apps/ingestion/evolution_ingestion.py`
14. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`
15. `automation/source_system/medical_evolution/path2.py`
16. `automation/source_system/medical_evolution/source_system.py`
17. Existing tests for persistent PDF, bridge, adapter, and worker command

## Reference Selectors and Functions

Use `path2.py` as the source of truth for action order and selectors.

Relevant functions:

- `choose_target_admissions(...)`;
- `click_menu_internacoes(page)`;
- `open_internacao_detail(page, admission)`;
- `open_report_for_interval(page, chunk_start, chunk_end)`;
- `wait_for_report_page(page)`;
- `download_pdf_from_report(page, context, report_frame, ...)`;
- `baixar_pdf_via_formulario_relatorio(...)`;
- `build_chunks_for_interval(start, end)`.

Relevant selectors/labels:

- frame name `frame_pol`;
- details link title `Detalhes da Internação`;
- button `Evolução`;
- date input `dataInicio:dataInicio:inputId_input`;
- date input `dataFim:dataFim:inputId_input`;
- button `#bt_UltimosQuinzedias:button`;
- report frame URL fragment `relatorioAnaEvoInternacaoPdf.xhtml`;
- form `#printLinks` fallback for PDF download.

## Implementation Shape

Prefer this shape unless PSW-S12 already established a better equivalent:

1. Put real legacy action helpers in the PSW-S12 navigation module, for example
   `apps/ingestion/extractors/legacy_navigation.py`.
2. Keep `RealHandleBridge` as the boundary used by
   `PersistentExtractionAdapter`.
3. Add one focused method on the bridge, for example:

   ```python
   extract_evolutions_via_legacy_actions(
       *,
       patient_record: str,
       start_date: str,
       end_date: str,
       timeout: int,
   ) -> list[dict[str, Any]]
   ```

4. Call that method from the adapter only for the real-handle path when the
   existing fast paths do not return events.
5. Reuse `persistent_evolution_pdf.py` for PDF text extraction and
   normalization where possible.
6. Let existing adapter enrichment add persistible fields, unless tests prove a
   narrower bridge-side enrichment is needed.

Do not introduce a broad new architecture.

## Development Method

Use strict TDD.

### RED

Add failing tests first. Keep them synthetic and anonymous.

Minimum failing tests:

1. overlapping admissions are selected for a requested window;
2. no overlapping admission raises a sanitized extraction error;
3. fake Playwright page/frame sequence opens admission details;
4. fake sequence clicks `Evolução`, fills BR dates, selects `Crescente` when
   present, and clicks visualize;
5. report/PDF download uses the existing page/context request object;
6. no-evolutions window returns `[]` and not fake data;
7. full-sync persists normalized events through existing shared service;
8. existing JSON/script and `pre.report-text` fast paths still work;
9. no subprocess, no `sync_playwright()` re-entry, no new browser/context.

### GREEN

Implement only the smallest code needed to pass the tests.

### REFACTOR

Refactor only after tests pass. Keep changes local to this slice.

## Scope and File Budget

Target maximum changed files: **9**.

Expected files:

- PSW-S12 navigation helper module;
- `apps/ingestion/extractors/real_handle_bridge.py`;
- `apps/ingestion/extractors/persistent_extraction_adapter.py` if wiring is
  needed;
- `apps/ingestion/extractors/persistent_evolution_pdf.py` only for a focused
  PDF form/download helper;
- focused unit tests for navigation/PDF/bridge;
- command or adapter tests only for wiring/persistence;
- rollout docs only if status wording changes.

Do not edit unrelated files.

If reliable full-sync real navigation cannot fit within the budget, stop and
write a blocker report instead of broadening scope.

## Required Behavior

### 1. Real action navigation for full-sync evolutions

For each planned gap window, the persistent real path must:

1. ensure or reopen the admissions list for the patient;
2. choose admissions overlapping the requested window;
3. open the matching admission detail;
4. click `Evolução`;
5. fill legacy date inputs in `DD/MM/YYYY`;
6. select ascending order when the selector is present;
7. click report visualization;
8. detect either an empty/no-evolutions message or a stable report page;
9. download the PDF with the existing authenticated context;
10. normalize PDF text into the adapter evolution contract;
11. return events to the adapter so existing enrichment/persistence continues.

### 2. Preserve fast paths

Keep these existing fast paths working:

- `evolution-data-json` script;
- `pre.report-text`;
- existing `EvolutionPdfFlow` behavior where still useful.

The real action navigation replaces direct URL navigation for the real legacy
path. It is not a rewrite of parsing or persistence.

### 3. Sanitized failure semantics

Map failures to existing extraction taxonomy with sanitized messages.

Handle at least:

- no overlapping admission;
- detail row not found;
- evolution button disabled;
- modal/report timeout;
- no-evolutions dialog;
- PDF URL unavailable;
- PDF form download unavailable;
- invalid PDF;
- normalization failure.

Error messages must not contain credentials, cookies, raw HTML, screenshots,
PDF bytes, or real patient identifiers.

### 4. Cleanup and session semantics

Preserve current semantics:

- tab cleanup is cleanup only;
- tab close is never evidence of session renewal;
- opening/rendering a new legacy tab/action is the only reliable renewal
  evidence;
- no background keepalive clicks during arbitrary actions;
- guardrails remain: `--real-handle --run-id <id> --max-runs 1`.

### 5. Production status

After this slice, the branch may be ready for one-run guarded manual smoke.
It is still **not production rollout-ready**.

Keep docs/report explicit about:

- live validation still pending;
- operational threshold tuning still pending;
- no continuous persistent worker in production yet.

## Acceptance Criteria

- Tests prove full-sync real handle no longer depends on evolutions URL
  templates.
- Tests prove overlapping admissions are selected correctly.
- Tests prove non-overlapping admissions fail or skip with sanitized behavior,
  as appropriate for the chosen helper contract.
- Tests prove the evolution modal/report sequence fills `DD/MM/YYYY` dates.
- Tests prove timeout values propagate to waits/downloads.
- Tests prove synthetic PDF bytes are downloaded through the existing
  page/context request object.
- Tests prove no-evolutions windows return `[]`.
- Tests prove normalized events include persistible fields after adapter
  enrichment and are persisted by full-sync.
- Tests prove existing JSON/script and `pre.report-text` fast paths still work.
- Tests prove current subprocess extractor and current worker behavior remain
  unchanged.
- Tests prove no subprocess, no new browser/context, and no Playwright re-entry.
- OpenSpec validation passes.

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

If Markdown files changed, validate only changed Markdown files with
`markdownlint-cli2`. Do not run global Markdown formatters or linters that
rewrite unrelated files.

## Required Report

Create:

```text
/tmp/sirhosp-slice-PSW-S13-report.md
```

The report must include:

- slice summary;
- confirmation that PSW-S12 was present;
- explanation of the JSP/PrimeFaces action navigation path;
- chosen implementation approach and rationale;
- acceptance checklist;
- files changed;
- before/after snippets for each changed file;
- commands executed and results;
- branch and `git status --short`;
- guarded full-sync smoke command example with placeholders only;
- rollout status after this slice;
- risks, pending items, and suggested next step.

Stop after this slice.
