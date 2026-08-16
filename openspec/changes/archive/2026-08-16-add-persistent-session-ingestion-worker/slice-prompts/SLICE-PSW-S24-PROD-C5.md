# Slice Prompt — PSW-S24-PROD-C5

## Handoff

Start with zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the active
OpenSpec change `add-persistent-session-ingestion-worker`, and this prompt.
Implement only this production-proven POL menu navigation correction.

## Production evidence

After production bootstrap and authentication succeeded, the guarded single-run
smoke reached admissions extraction but timed out before completing. A sanitized
stage probe established:

```text
STAGE bootstrap: OK
STAGE ensure_search_screen: NavigationTimeoutError
STAGE teardown: DONE
```

A second sanitized probe used the exact established extractor interaction:

```text
STAGE initial_search: ABSENT
STAGE pol_visible: OK
STAGE pol_dom_click: OK
STAGE search_after_dom: VISIBLE
STAGE teardown: DONE
```

The PrimeFaces `#polMenu` is visible, but Playwright's normal actionability click
times out. Direct DOM click opens the patient search screen. This is the same
first interaction used by the existing production demographics and medical
evolution extractors.

## Scope

Maximum four versioned files:

1. `apps/ingestion/extractors/legacy_navigation.py`;
2. `tests/unit/test_legacy_navigation.py`;
3. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`;
4. this slice prompt.

Do not change login, credentials, proxy, browser lifecycle, queue selection,
claim discipline, intents, persistence services, Compose, or rollout defaults.

## TDD contract

1. Add a failing regression proving `#polMenu` is opened by direct DOM click
   before Playwright's normal click.
2. Model the observed condition where the normal click would time out but the
   DOM click succeeds and reveals `#prontuarioInput`.
3. Reuse the production-proven JavaScript `element.click()` interaction.
4. Retain the bounded normal-click fallback when DOM evaluation fails.
5. Preserve typed, sanitized failure mapping when every required interaction
   path fails.

## Acceptance

- RED: the new production interaction contract fails before implementation.
- All `TestEnsureSearchScreen` tests pass after implementation.
- Unit suite passes in the official container.
- Official quality gate passes.
- LSP diagnostics are clean for changed Python files.
- Strict OpenSpec and targeted Markdown lint pass.
- Create `/tmp/sirhosp-slice-PSW-S24-PROD-C5-report.md` with summary, checklist,
  changed files, literal before/after fragments, commands/results, risks, and
  next step.
- Commit and push the four-file slice before production rebuild.
- PSW-S24 remains incomplete until the selected queued admissions run succeeds,
  naturally enqueues the required `full_sync`, and bounded validation passes.
