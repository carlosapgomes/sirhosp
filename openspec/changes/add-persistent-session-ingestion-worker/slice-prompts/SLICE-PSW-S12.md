# SLICE PSW-S12: Real Legacy Patient/Admissions Navigation

## Handoff for Context-Zero Executor

You are implementing only slice PSW-S12 for OpenSpec change
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

## Problem to Fix

PSW-S10 introduced `SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE` and
`SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE` so the persistent adapter could call
`open_tab(template.format(...))`.

Manual validation showed this assumption is wrong for the real legacy system:
it is Java/JSP/PrimeFaces and does not expose reloadable deep links for patient
admissions/evolutions. The working automation is action-based Playwright
navigation, as implemented in
`automation/source_system/medical_evolution/path2.py`.

This slice replaces the admissions part of the real-handle smoke path with
real UI navigation modeled after `path2.py`, while keeping the current worker
and subprocess extractor unchanged.

## Slice Goal

Make `process_ingestion_runs_persistent_session --real-handle --run-id <id>
--max-runs 1` able to process a single `admissions_only` run by navigating the
real legacy UI actions instead of relying on admissions URL templates.

This slice deliberately stops at admissions snapshot capture. Full-sync
evolution detail/PDF navigation is assigned to PSW-S13.

## Read First

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md` if present
3. `openspec/changes/add-persistent-session-ingestion-worker/proposal.md`
4. `openspec/changes/add-persistent-session-ingestion-worker/design.md`
5. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`
6. `openspec/changes/add-persistent-session-ingestion-worker/specs/`
7. `/tmp/sirhosp-slice-PSW-S10-report.md`
8. `/tmp/sirhosp-slice-PSW-S11-report.md`
9. `apps/ingestion/extractors/legacy_session_bootstrap.py`
10. `apps/ingestion/extractors/playwright_session_handle.py`
11. `apps/ingestion/extractors/real_handle_bridge.py`
12. `apps/ingestion/extractors/persistent_extraction_adapter.py`
13. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`
14. `automation/source_system/medical_evolution/path2.py`
15. `automation/source_system/medical_evolution/source_system.py`
16. `tests/unit/test_real_handle_bridge.py`
17. `tests/unit/test_persistent_worker_command.py`
18. `tests/unit/test_legacy_session_bootstrap.py`

Focus on these stable `path2.py` actions/selectors:

- `ensure_search_screen(page)`;
- `#prontuarioInput`;
- link `Pesquisa Avançada`;
- text `Internações`;
- frame name `frame_pol`;
- `wait_internacoes_table(page)`;
- `read_internacoes_rows(page)`;
- `_build_admission_snapshot(admissions)`.

## Development Method

Use strict TDD:

1. Add failing tests that prove the real handle does not require admissions or
   evolutions URL templates for an `admissions_only` smoke.
2. Add failing tests for a fake Playwright page that executes the patient
   search and admissions-table navigation sequence.
3. Implement the smallest navigation helper/bridge change needed to pass.
4. Refactor only after green tests.

Apply clean code, DRY, and YAGNI:

- port only the minimal action navigation needed for admissions snapshot;
- do not copy all of `path2.py`;
- do not shell out to `path2.py`;
- do not launch a new browser/context/Playwright instance per job;
- keep Playwright-specific code behind the real handle/bridge boundary;
- keep queue/run lifecycle logic in the management command unchanged.

## Scope and File Budget

Target maximum changed files: 7.

Expected files:

- a focused legacy navigation helper module, for example
  `apps/ingestion/extractors/legacy_navigation.py`;
- `apps/ingestion/extractors/real_handle_bridge.py`;
- `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`;
- focused unit tests for the navigation helper and command/bridge wiring;
- rollout docs only if needed to prevent unsafe manual-smoke instructions.

Do not modify `process_ingestion_runs.py` or the current subprocess extractor.
If the required change exceeds this budget, stop and report the narrower next
slice instead of broadening scope.

## Required Behavior

### 1. Remove admissions/evolutions template requirement from real smoke

`--real-handle` must still require:

- `--run-id <id>`;
- `--max-runs 1`;
- `SOURCE_SYSTEM_URL`;
- `SOURCE_SYSTEM_USERNAME`;
- `SOURCE_SYSTEM_PASSWORD`.

It must no longer fail before claim just because these are missing:

- `SOURCE_SYSTEM_ADMISSIONS_URL_TEMPLATE`;
- `SOURCE_SYSTEM_EVOLUTIONS_URL_TEMPLATE`.

Keep `SOURCE_SYSTEM_SAFE_RENEWAL_URL` behavior conservative. If you can safely
default renewal to an already-authenticated root/search action within the file
budget, test it. Otherwise keep it optional or document the remaining renewal
constraint without blocking the admissions smoke.

### 2. Navigate by real UI actions for admissions

For an `admissions_only` run, the real handle path must navigate like the
working Playwright script:

1. use the bootstrapped page/session from PSW-S10;
2. ensure the search screen is visible;
3. fill `#prontuarioInput` with `patient_record`;
4. click/link through `Pesquisa Avançada` and `Internações`;
5. wait for `frame_pol` and `#tabelaInternacoes:resultList_data` rows;
6. read rows with details links and BR dates;
7. convert them to the canonical admission snapshot contract consumed by
   `AdmissionSnapshotParser`.

The persistent adapter may still see a synthetic
`<div id="admission-snapshot-data">` container internally, but the underlying
data must come from real UI actions, not from a direct URL template.

### 3. Preserve session and run semantics

The slice must preserve:

- `--real-handle` guardrails (`--run-id` and `--max-runs 1`);
- sanitized errors before/after claim;
- stage metrics and retry behavior;
- tab cleanup as cleanup only, never renewal evidence;
- current worker behavior unchanged;
- no real patient data, screenshots, cookies, PDFs, raw HTML, or credentials in
  tests, logs, docs, or reports.

### 4. Keep full-sync explicitly pending

If a selected run is `full_sync`, it may still fail or remain blocked in this
slice. Do not claim full-sync real navigation is production-ready. PSW-S13 owns
real detail/evolution/PDF navigation.

## Acceptance Criteria

- Tests prove `--real-handle --run-id <id> --max-runs 1` no longer requires
  admissions/evolutions URL templates before creating the real handle.
- Tests prove missing source URL/username/password still fails before claim with
  sanitized messages.
- Tests prove the admissions path calls the expected action-navigation sequence
  on fake Playwright objects.
- Tests prove admissions rows from representative synthetic legacy DOM/frame
  data are converted to the canonical snapshot shape.
- Tests prove no subprocess, `sync_playwright()` re-entry, or new browser is
  introduced in this path.
- Tests prove current stub mode and current worker behavior remain unchanged.
- OpenSpec validation passes.
- If docs are changed, they clearly state that this is manual smoke only, not
  production rollout.

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

Create `/tmp/sirhosp-slice-PSW-S12-report.md` with:

- slice summary;
- explanation of why URL templates were removed for admissions;
- chosen navigation approach and rationale;
- acceptance checklist;
- files changed;
- before/after snippets for each changed file;
- commands executed and results;
- branch and `git status --short`;
- guarded admissions-only smoke command example with placeholders only;
- rollout status after this slice;
- risks, pending items, and suggested next step.

Stop after this slice.
