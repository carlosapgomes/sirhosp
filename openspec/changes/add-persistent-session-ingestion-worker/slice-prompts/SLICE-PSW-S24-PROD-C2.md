# Slice Prompt — PSW-S24-PROD-C2

## Handoff

Start with zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the active
OpenSpec change `add-persistent-session-ingestion-worker`, and this prompt.
Implement only this production login-submission hotfix.

## Incident

After PSW-S24-PROD-C1 successfully routed persistent Chromium through the
hospital Tailscale SOCKS5 proxy, real bootstrap navigated to the login page and
filled both username and password. Submission then failed at the canonical
`Entrar` button click. An existing production extractor submits the same form
by pressing Enter in the password field.

## Scope

Maximum four versioned files:

1. `apps/ingestion/extractors/legacy_session_bootstrap.py`;
2. `tests/unit/test_legacy_session_bootstrap.py`;
3. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`;
4. this slice prompt.

Do not change proxy handling, credentials, readiness evidence, queue behavior,
extraction behavior, Compose services, retry semantics, or rollout status.

## TDD contract

1. Add a failing test where the canonical `Entrar` click raises and pressing
   Enter on the already-resolved password field succeeds.
2. Preserve the canonical button as the first submission path.
3. Fall back only after button-click failure.
4. Preserve the existing `#tempoSessao` authenticated-readiness check after
   submission.
5. When both submission paths fail, raise the same sanitized
   `LegacyBootstrapError`; never expose raw exceptions or credential values.
6. Update the existing sanitized-failure test to cover failure of both paths.

## Acceptance

- The RED regression fails at the previous button-only implementation.
- The focused bootstrap suite passes.
- The official container quality gate passes.
- LSP diagnostics are clean for both Python files.
- Strict OpenSpec and targeted Markdown lint pass.
- Create `/tmp/sirhosp-slice-PSW-S24-PROD-C2-report.md` with summary, acceptance
  checklist, changed files, literal before/after snippets, commands/results,
  risks, and next step.
- PSW-S24 live validation remains incomplete until the corrected image reaches
  production and the real bootstrap probe observes `#tempoSessao`.
