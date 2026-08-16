# SLICE PSW-S19: Restart, Rebootstrap, and Lifecycle Configuration

## Handoff for a Context-Zero Implementer

Implement only PSW-S19 after PSW-S18 is committed. Read project instructions,
all change artifacts, PSW-S18 report, session controller/handle/bridge,
bootstrap helper, command options, profile lifecycle, and focused tests. Start
from a clean branch.

A Chromium restart creates an unauthenticated session. Readiness after restart
requires bootstrap/login and `#tempoSessao`, not merely a connected context.

## Mandatory Protocol for the Implementing LLM

1. Record `BASE_REF`, branch, clean status, and requirement matrix.
2. Run official unit baseline before edits; record exit and summary.
3. Add tests first and capture RED for restart-without-authentication.
4. Implement minimum GREEN with no background login thread.
5. Run lifecycle/config inspections and interpret defaults/overrides.
6. Run every official validation command.
7. Only then update PSW-S19, report, commit, push, and stop.

Any missing evidence, failing gate, or unauthenticated post-restart claim makes
the slice incomplete.

## Inherited Contracts — Frozen and Not Reopened

PSW-S17 and the verified PSW-S18 cleanup contract are frozen prerequisites.
Preserve their observable behavior without re-auditing timeout taxonomy,
sanitization internals, exception context objects, or DOM cleanup semantics.

PSW-S17 sanitization applies only to persisted fields, logs, command output,
`CommandError`, and rendered tracebacks. Suppressed internal `__context__` is
accepted unless re-emitted. Its deadline remains cooperative, not a hard
wall-clock bound.

If a non-critical inherited defect is discovered, name a separate remediation;
do not absorb it into PSW-S19. Only a critical safety defect or a blocker to an
explicit requirement below may stop this slice.

## Acceptance Freeze and Artifact Policy

The requirements, lifecycle paths, and configuration keys below are the full
acceptance surface. Do not add new thresholds, health policies, selectors, or
private implementation invariants during implementation or verification.

Update active requirements in place; never add D-numbered corrective
appendices. The report needs Before/After fragments only for files changed in
this execution pass.

## Objective

After a health/lifecycle restart, bootstrap a fresh authenticated legacy
session before another claim. Expose conservative, validated lifecycle and
headless configuration and prove real multi-job reuse semantics with fakes.

## Requirements

- **R1:** Characterize disconnected, max-jobs, max-lifetime, failure-threshold,
  renewal-threshold, and normal shutdown paths.
- **R2:** Restart browser/context at a safe point only between jobs unless the
  current browser is unusable.
- **R3:** Re-run sanitized bootstrap/login after every restart and require a
  valid `#tempoSessao` readiness marker.
- **R4:** Do not claim a run while restart/rebootstrap is incomplete or failed.
- **R5:** On rebootstrap failure, retain recovery state and retry safely without
  mutating an unclaimed run.
- **R6:** Expose max jobs, max lifetime, consecutive failures, renewal threshold,
  and `--headless`/`--no-headless` through one documented configuration path;
  validate positive ranges and fail before claim on invalid values.
- **R7:** Preserve exclusive profile ownership and release only after shutdown.
- **R8:** Prove two jobs use one login/context, then a threshold causes exactly
  one restart plus rebootstrap before a later job.
- **R9:** Keep current-worker CLI and behavior unchanged.

## Closed Configuration Set

Only these configuration values belong to PSW-S19:

| Key | Required validation | Required proof |
| --- | --- | --- |
| max jobs | positive integer | threshold causes one restart |
| max lifetime | positive duration | expiry requests restart |
| consecutive failures | positive integer | threshold requests restart |
| renewal threshold | positive duration | threshold state is effective |
| headless | explicit boolean | CLI value reaches concrete handle |

Before editing, record each existing default and its CLI/settings source in the
report. Do not introduce additional lifecycle configuration in this slice.

## Expected Scope

Target maximum: 8 versioned files including `tasks.md`.

Expected: controller/config, handle/bridge bootstrap boundary, persistent
command, focused tests, optional settings/example update only if required by the
chosen config path, and `tasks.md`.

Forbidden: models/migrations, intent behavior, clinical persistence, navigation
selectors beyond readiness, PDF/chunk logic, production rollout enablement.

## TDD

### RED

Add a fake handle whose restart yields blank/unauthenticated HTML. Prove the
existing code cannot process a later run. Add configuration validation and
multi-job/restart sequence tests.

### GREEN

Introduce the smallest explicit restart-and-bootstrap orchestration. Reuse the
existing bootstrap helper; do not duplicate credentials/login selectors.

### REFACTOR

Keep lifecycle ownership in one boundary. Remove ambiguous restart methods or
comments that imply connectivity equals authentication.

## Mandatory Inspection Checks

```bash
rg -n \
  "restart_browser|bootstrap_legacy_session|tempoSessao|ensure_session_ready" \
  apps/ingestion/extractors \
  apps/ingestion/management/commands/\
process_ingestion_runs_persistent_session.py
rg -n "max_jobs|max_lifetime|max_consecutive|renewal_threshold|headless" \
  apps config docs/operations/persistent-worker-rollout.md
rg -n "launch_persistent_context|release_after_shutdown|user_data_dir" \
  apps/ingestion/extractors
```

Explain which layer owns restart, bootstrap, configuration, and profile cleanup.

## Binary Success Criteria

- [ ] Post-restart claims require authenticated readiness.
- [ ] Failed rebootstrap mutates no queued run.
- [ ] Multi-job sequence proves one login before threshold.
- [ ] Later job proves exactly one restart/rebootstrap.
- [ ] The five enumerated configuration values are effective and validated.
- [ ] Headless CLI reaches the concrete handle.
- [ ] Current worker remains unchanged.
- [ ] All official gates pass.

## Self-Evaluation Gates

1. Can a connected blank page be considered ready?
2. Can restart occur without subsequent bootstrap?
3. Can invalid thresholds reach the processing loop?
4. Can a run become running during recovery?
5. Did the slice introduce a second lifecycle owner?

Required answers: no, no, no, no, no.

## Validation

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh quality-gate
openspec validate add-persistent-session-ingestion-worker --strict
git diff --name-only "$BASE_REF"...HEAD -- '*.md' | xargs -r markdownlint-cli2
```

## Required Report

Create `/tmp/sirhosp-slice-PSW-S19-report.md` with protocol evidence, lifecycle
state diagram/table, config table, RED/GREEN, inspections, commands/exit codes,
files, risks, and verifier handoff.
Include real Before/After fragments only for files changed in this pass. Do not
re-prove inherited PSW-S17 or PSW-S18 contracts.

Final prompt: implement only PSW-S19. Connectivity without authentication,
claims during recovery, ineffective configuration, or missing evidence means
`Status: INCOMPLETE`.
