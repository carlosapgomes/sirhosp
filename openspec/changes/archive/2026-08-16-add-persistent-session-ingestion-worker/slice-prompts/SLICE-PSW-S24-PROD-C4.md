# Slice Prompt — PSW-S24-PROD-C4

## Handoff

Start with zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the active
OpenSpec change `add-persistent-session-ingestion-worker`, and this prompt.
Implement only this real Playwright/ORM lifecycle correction.

## Production evidence

The isolated standard bridge bootstrap passed against the real portal:

```text
Persistent real bootstrap OK
```

The first guarded single-run smoke then failed before claim with:

```text
django.core.exceptions.SynchronousOnlyOperation:
You cannot call this from an async context - use a thread or sync_to_async.
```

It also emitted `Error stopping Playwright (sanitized)`. Exit code was 1. The
selected row remained unclaimed because the first `transaction.atomic()` was
rejected.

Root causes:

1. Playwright's synchronous API keeps its dispatcher event loop active on the
   command thread, so Django's async-safety check rejects otherwise synchronous,
   serialized ORM work.
2. `sync_playwright().__enter__()` returns the public Playwright object, but
   shutdown incorrectly called `__exit__()` on that returned object instead of
   its documented `stop()` API.

## Scope

Maximum six versioned files:

1. `apps/ingestion/extractors/playwright_session_handle.py`;
2. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`;
3. `tests/unit/test_playwright_session_handle.py`;
4. `tests/unit/test_persistent_worker_command.py`;
5. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`;
6. this slice prompt.

Do not change queue selection, claim discipline, intents, persistence services,
browser profile isolation, proxy configuration, login, extraction, Compose,
or rollout defaults.

## TDD contract

1. Add a failing handle test requiring `Playwright.stop()` exactly once and
   forbidding `__exit__()` on the returned Playwright object.
2. Add integrated real-mode proof that `DJANGO_ALLOW_ASYNC_UNSAFE=true` is
   present during the real database claim.
3. Scope that documented Django escape hatch to explicit `--real-handle`
   processing and teardown only, then restore the previous environment value.
4. Keep the stub/default path unchanged.
5. Preserve adapter shutdown and profile release on every exit path.

The escape hatch is valid here because this dedicated management-command
process performs serialized synchronous ORM work and has no concurrent async ORM
consumer; Playwright's internal dispatcher is the only active event loop.

## Acceptance

- RED: exactly the new ORM-guard and Playwright-stop contracts fail.
- Unit suite passes in the official container.
- Official quality gate passes.
- LSP diagnostics are clean for all changed Python files.
- Strict OpenSpec and targeted Markdown lint pass.
- Create `/tmp/sirhosp-slice-PSW-S24-PROD-C4-report.md` with summary, checklist,
  changed files, literal before/after fragments, commands/results, risks, and
  next step.
- Commit and push the six-file slice before production rebuild.
- PSW-S24 remains incomplete until the same selected queued run succeeds and
  naturally enqueues the required `full_sync`, followed by bounded validation.
