# Slice Prompt - RHID-S1-C5 Adaptive Census Failure Exit

## Handoff

Start from zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the complete
`add-release-image-hospital-deploy` OpenSpec change,
`apps/census/management/commands/run_adaptive_census_cycles.py`, the relevant
unit tests in `tests/unit/test_adaptive_census_orchestrator.py`, the production
runbook, the prior RHID reports under `/tmp`, and this prompt before editing.

During RC3 acceptance, `run_adaptive_census_cycles --once` persisted a failed
`census_extraction` run and printed `EXTRACTION FAILED`, but returned process
status zero. That makes operator scripts and one-shot production probes report a
failed cycle as successful. Blocked and lock-held outcomes are normal safe
no-work states; failed, ambiguous, and unknown outcomes are command failures.
Continuous `--loop` behavior is not part of this correction.

## Scope and file limit

Modify no more than these five tracked files:

1. `apps/census/management/commands/run_adaptive_census_cycles.py`
2. `tests/unit/test_adaptive_census_orchestrator.py`
3. `openspec/changes/add-release-image-hospital-deploy/specs/adaptive-census-orchestration/spec.md`
4. `openspec/changes/add-release-image-hospital-deploy/tasks.md`
5. `openspec/changes/add-release-image-hospital-deploy/slice-prompts/SLICE-RHID-S1-C5.md`

Do not modify orchestration state transitions, extraction code, models,
migrations, Compose files, the loop retry policy, or clinical behavior. Do not
record credentials, source-system values, or patient data. If another tracked
file is required, stop and report the blocker rather than expanding scope.

## Required change

1. Add failing command-level regression tests for one-shot `extraction_failed`,
   `ambiguous_runs`, and an unknown outcome.
2. Preserve successful zero exit for `success`, `blocked`, and `lock_held`.
3. Raise Django `CommandError` after emitting a concise operator-facing message
   for each failed, ambiguous, or unknown one-shot outcome so the management
   command exits nonzero from a real shell.
4. Keep `--dry-run` and `--loop` behavior unchanged.
5. Add a delta requirement documenting the one-shot exit-status contract.

## Acceptance criteria

- [ ] RED proves all three failure outcomes currently return successfully.
- [ ] Focused command tests pass after the minimum implementation.
- [ ] Failure details remain visible without duplicate traceback-like output.
- [ ] `success`, `blocked`, and `lock_held` remain non-exceptional.
- [ ] `--dry-run` and continuous-loop tests remain green.
- [ ] Strict OpenSpec, official check/unit/lint/typecheck, and Markdown lint pass.
- [ ] `/tmp/sirhosp-slice-RHID-S1-C5-report.md` records before/after fragments,
      RED/GREEN evidence, commands, results and risks without sensitive data.

## Stop rule

Use TDD: RED, minimum GREEN, then controlled cleanup. Run official container
commands for final gate claims. Update task checkboxes only after evidence
exists. Create the required report, commit and push the correction, then stop
this slice before publishing or modifying the hospital runtime.
