# Tasks: adaptive-census-orchestrator

## 1. Slice S1 - Operational state and dry-run

- [X] 1.1 Add focused tests for drained queue, active queue, open batch,
  cooldown and stale-running detection.
- [X] 1.2 Implement a small orchestration service/helper that computes the safe
  start decision without mutating data.
- [X] 1.3 Add the management command shell with `--dry-run` and operator output
  that reports whether a cycle would start.
- [X] 1.4 Validate S1 with focused tests, Django check, lint, typecheck where
  relevant, OpenSpec validation and markdown lint for changed docs.
- [X] 1.5 Create `/tmp/sirhosp-slice-ACO-S1-report.md` with before/after
  snippets, commands, results, risks and next step.

## 2. Slice S2 - One safe real cycle

- [X] 2.1 Add tests proving `--once` skips when blocked, acquires/rejects the
  coordination lock, runs extraction only when eligible and processes by the
  newly identified census extraction run id.
- [X] 2.2 Implement single-cycle execution using existing management commands,
  exact run-id detection and fail-safe handling for zero or multiple new runs.
- [X] 2.3 Ensure extraction failure prevents snapshot processing and returns a
  non-zero command outcome.
- [X] 2.4 Validate S2 with focused tests, official container commands for the
  touched scope, OpenSpec validation and markdown lint.
- [X] 2.5 Create `/tmp/sirhosp-slice-ACO-S2-report.md` with implementation
  evidence for third-party LLM review.
- [X] 2.6 Regression fix (post-review): capture `SystemExit` from the real
  `extract_census` (`sys.exit(1)`) so failure returns a structured
  `extraction_failed` outcome instead of crashing the orchestrator.
  Added regression test `test_extraction_systemexit_is_controlled`.

## 3. Slice S3 - Continuous loop behavior

- [X] 3.1 Add tests for loop waiting, cooldown waiting, failure backoff and
  graceful SIGTERM/SIGINT handling using mocked sleep and command calls.
- [X] 3.2 Implement `--loop`, `--sleep-seconds`, `--min-interval-minutes`,
  `--failure-backoff-minutes` and `--stale-running-minutes` behavior.
- [X] 3.3 Keep loop logs safe: aggregate counts and operational identifiers only,
  with no patient names, clinical text or credentials.
- [X] 3.4 Validate S3 with focused tests, official container commands for the
  touched scope, OpenSpec validation and markdown lint.
- [X] 3.5 Create `/tmp/sirhosp-slice-ACO-S3-report.md` with implementation
  evidence for third-party LLM review.

## 4. Slice S4 - Deploy documentation and timer removal

- [X] 4.1 Remove the obsolete fixed census timer script/unit files from deploy
  artifacts or replace references with the adaptive orchestrator service.
- [X] 4.2 Add deploy documentation for running the worker continuously and the
  adaptive census orchestrator continuously.
- [X] 4.3 Add or update systemd unit guidance for the orchestrator service without
  reintroducing an `OnCalendar` timer for censo.
- [X] 4.4 Validate S4 with markdown lint, OpenSpec validation and any affected
  shell/static checks.
- [X] 4.5 Create `/tmp/sirhosp-slice-ACO-S4-report.md` with documentation diff,
  commands, results, risks and next step.

## 5. Final verification

- [X] 5.1 Run `openspec validate adaptive-census-orchestrator --type change --strict`.
- [X] 5.2 Run `./scripts/test-in-container.sh check`.
- [X] 5.3 Run relevant unit/integration tests in container for all touched code.
- [X] 5.4 Run `./scripts/test-in-container.sh lint`.
- [X] 5.5 Run `./scripts/test-in-container.sh typecheck` and document any
  pre-existing or justified exceptions.
- [X] 5.6 Run `./scripts/markdown-lint.sh` for all changed Markdown files.
- [X] 5.7 Stop after final report; do not archive the change without explicit
  operator approval.
  (Approved by operator on 2026-06-23.)
