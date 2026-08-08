# Slice Prompt — PSW-S24-PROD-C1

## Handoff

Start with zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the active
OpenSpec change `add-persistent-session-ingestion-worker`, and this prompt.
Implement only this production bootstrap hotfix.

## Incident

The guarded production launch of
`process_ingestion_runs_persistent_session --real-handle` repeatedly failed
before login with the sanitized message `Legacy bootstrap: navigation to login
page failed`. The production services provide
`PLAYWRIGHT_PROXY_SERVER=socks5://sirhosp-tailscale-proxy:1055`, but
`PlaywrightSessionHandle.start()` launches its persistent Chromium context
without the shared proxy configuration. It also omits the existing production
HTTPS-tolerance setting used by legacy extractors.

## Scope

Maximum four versioned files:

1. `apps/ingestion/extractors/playwright_session_handle.py`;
2. `tests/unit/test_playwright_session_handle.py`;
3. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`;
4. this slice prompt.

Do not change queue, login selectors, extraction behavior, Compose services,
credentials, retry semantics, or rollout status.

## TDD contract

1. Add a failing regression test proving a configured
   `PLAYWRIGHT_PROXY_SERVER` reaches
   `chromium.launch_persistent_context(proxy={"server": value})`.
2. Add a failing regression test proving the direct path omits `proxy` when the
   environment variable is absent.
3. Both launches must set `ignore_https_errors=True`, matching the production
   legacy Playwright paths.
4. Implement the minimum fix by reusing
   `automation.source_system.proxy_config.get_playwright_proxy`; do not create a
   second proxy parser.
5. Never log proxy values, credentials, URLs, cookies, page bodies, or raw
   exceptions.

## Acceptance

- The RED tests fail because `proxy` and `ignore_https_errors` are missing.
- The focused handle suite passes.
- The official container quality gate passes.
- LSP diagnostics are clean for both Python files.
- Strict OpenSpec and targeted Markdown lint pass.
- Create `/tmp/sirhosp-slice-PSW-S24-PROD-C1-report.md` with summary, acceptance
  checklist, changed files, literal before/after snippets, commands/results,
  risks, and next step.
- PSW-S24 live validation remains incomplete until the corrected image reaches
  production and real bootstrap/login succeeds.
