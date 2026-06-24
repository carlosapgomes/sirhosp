# Tasks: stale-ingestion-run-recovery

## 1. Slice SIRS-S1 - Worker heartbeat persistence

- [X] 1.1 Add failing tests proving `process_ingestion_runs` populates
  `worker_heartbeat_at` when a run is claimed and refreshes it while processing.
- [X] 1.2 Add nullable heartbeat field to `IngestionRun` and create the Django
  migration without adding new tables or external dependencies.
- [X] 1.3 Implement a small heartbeat helper for the ingestion worker that
  refreshes the active run at a low frequency and stops on terminal state.
- [X] 1.4 Ensure worker terminal success/failure paths keep existing behavior and
  do not leak patient data in heartbeat-related logs.
- [X] 1.5 Validate S1 with focused tests, `./scripts/test-in-container.sh check`,
  lint/typecheck for touched scope when feasible, OpenSpec validation and
  markdown lint for changed Markdown.
- [X] 1.6 Create `/tmp/sirhosp-slice-SIRS-S1-report.md` with summary,
  acceptance checklist, files changed, before/after snippets, commands, results,
  risks and next step.

## 2. Slice SIRS-S2 - Stale recovery service and command

- [ ] 2.1 Add failing tests for candidate detection using per-intent age limits,
  heartbeat grace, default unknown-intent limit and safe dry-run output.
- [ ] 2.2 Add failing tests proving apply mode marks abandoned runs as terminal
  `failed`, clears retry scheduling, does not requeue and records safe metadata.
- [ ] 2.3 Add failing tests proving batch closure after recovery and circuit
  breaker abort without mutations when candidates exceed the sweep limit.
- [ ] 2.4 Implement reusable stale recovery service and a management command
  `recover_stale_ingestion_runs` with `--dry-run`, `--apply`, heartbeat grace,
  per-intent limits and `--max-runs-per-sweep`.
- [ ] 2.5 Keep batch-closing logic DRY by extracting or reusing a small helper
  instead of duplicating behavior across worker and recovery code.
- [ ] 2.6 Validate S2 with focused tests, official container checks for touched
  scope, OpenSpec validation and markdown lint.
- [ ] 2.7 Create `/tmp/sirhosp-slice-SIRS-S2-report.md` with implementation
  evidence for third-party LLM review.

## 3. Slice SIRS-S3 - Orchestrator integration

- [ ] 3.1 Add failing tests proving the adaptive orchestrator loop invokes stale
  recovery before computing queue eligibility when recovery is enabled.
- [ ] 3.2 Add failing tests proving recovery circuit-breaker results keep the
  orchestrator waiting and prevent a new census cycle.
- [ ] 3.3 Wire the orchestrator to call the reusable recovery service with
  configurable flags while preserving dry-run and one-cycle behavior safety.
- [ ] 3.4 Ensure orchestrator logs remain safe and report recovery counts without
  patient names, clinical text or credentials.
- [ ] 3.5 Validate S3 with focused tests, official container checks for touched
  scope, OpenSpec validation and markdown lint.
- [ ] 3.6 Create `/tmp/sirhosp-slice-SIRS-S3-report.md` with implementation
  evidence for third-party LLM review.

## 4. Slice SIRS-S4 - Operations documentation and final verification

- [ ] 4.1 Update deploy/operator documentation with heartbeat, stale recovery
  defaults, dry-run command, apply command and orchestrator integration.
- [ ] 4.2 Document recommended production defaults for Docker rootless workers and
  host `systemd` orchestrator, including how to disable recovery temporarily.
- [ ] 4.3 Document operational interpretation: failed stale run is a partial job
  loss, not a discarded batch, and no automatic requeue is performed.
- [ ] 4.4 Validate S4 with markdown lint, OpenSpec validation and any affected
  static checks.
- [ ] 4.5 Create `/tmp/sirhosp-slice-SIRS-S4-report.md` with documentation diff,
  commands, results, risks and next step.

## 5. Final verification

- [ ] 5.1 Run `openspec validate stale-ingestion-run-recovery --type change --strict`.
- [ ] 5.2 Run `./scripts/test-in-container.sh check`.
- [ ] 5.3 Run relevant unit/integration tests in container for all touched code.
- [ ] 5.4 Run `./scripts/test-in-container.sh lint`.
- [ ] 5.5 Run `./scripts/test-in-container.sh typecheck` and document any
  pre-existing or justified exceptions.
- [ ] 5.6 Run `./scripts/markdown-lint.sh` or targeted markdownlint for all
  changed Markdown files.
- [ ] 5.7 Stop after final report; do not archive the change without explicit
  operator approval.
