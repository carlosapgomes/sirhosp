# Slice SIRS-S4: Operations documentation and final verification

## Handoff for zero-context executor

Read `AGENTS.md`, `PROJECT_CONTEXT.md` and all artifacts under:

```text
openspec/changes/stale-ingestion-run-recovery/
```

Confirm SIRS-S1, SIRS-S2 and SIRS-S3 are implemented before editing docs.
Implement only documentation and final verification work in this slice unless a
small bug is discovered in the docs validation path. If code behavior is missing,
stop and report the blocker instead of implementing more code.

## Goal

Document how operators should run and interpret stale ingestion run recovery in
production, especially with Docker rootless workers and the adaptive
orchestrator running via host `systemd`.

## Expected documentation coverage

Document:

- why job-level stale recovery exists;
- heartbeat meaning and expected worker behavior;
- default stale limits by intent;
- heartbeat grace and sweep circuit breaker;
- dry-run command for manual inspection;
- apply command for manual intervention;
- orchestrator loop integration and how to disable it temporarily;
- terminal failed semantics: one job failed, not the whole batch discarded;
- no automatic requeue for stale recovery;
- safe rollback/disable procedure.

## Suggested implementation boundaries

Maximum intended changed files: 4.

Likely files:

- `deploy/README.md`
- systemd/orchestrator documentation if already present under `deploy/systemd/`
- possibly `tasks.md` only to mark tasks complete after implementation evidence

If you need more than 4 files, stop and explain why in the report.

## TDD / quality approach

This is a documentation slice, so there is no red/green code cycle unless a
small documentation-driven check exists. Still apply clean code principles to
examples:

- keep commands copy-pasteable;
- avoid exposing secrets;
- avoid speculative options not implemented;
- keep defaults aligned with actual command help and tests.

## Acceptance criteria

- Operators can run dry-run stale recovery from docs.
- Operators can understand when and how the orchestrator applies recovery.
- Docs explain that stale recovery marks failed terminally without requeue.
- Docs mention heartbeat is DB-based and does not require Docker/PID access.
- Docs include safe disable/rollback guidance.
- Markdown lint passes for every changed Markdown file.

## Validation gates

Run:

```bash
openspec validate stale-ingestion-run-recovery --type change --strict
./scripts/markdown-lint.sh
```

If full repository markdown lint fails because of pre-existing archived files,
run targeted markdownlint for every changed Markdown file and document the
pre-existing blocker.

Also run relevant project gates if docs touched command examples that may affect
static checks:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
```

## Required report

Create `/tmp/sirhosp-slice-SIRS-S4-report.md` with:

- summary of docs updated;
- acceptance checklist;
- files changed;
- before/after snippets;
- commands executed and results;
- known pre-existing validation blockers, if any;
- recommendation whether the change is ready for final review/archive.

Do not include patient data, credentials or real clinical text.
