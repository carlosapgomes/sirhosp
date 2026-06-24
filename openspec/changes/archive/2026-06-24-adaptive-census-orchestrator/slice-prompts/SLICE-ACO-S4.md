# SLICE ACO-S4 - Deploy documentation and timer removal

## Handoff for context-zero executor

You are implementing only Slice ACO-S4 of the OpenSpec change
`adaptive-census-orchestrator` in the SIRHOSP Django project.

Read these files before coding:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/adaptive-census-orchestrator/proposal.md`
- `openspec/changes/adaptive-census-orchestrator/design.md`
- `openspec/changes/adaptive-census-orchestrator/tasks.md`
- `openspec/changes/adaptive-census-orchestrator/specs/adaptive-census-orchestration/spec.md`
- `deploy/README.md`
- `deploy/census-scheduler.sh`
- `deploy/systemd/sirhosp-census.service`
- `deploy/systemd/sirhosp-census.timer`
- Files changed by Slices ACO-S1, ACO-S2 and ACO-S3

Start from a clean working tree. If ACO-S1 through ACO-S3 are not implemented,
stop.

## Objective

Remove the obsolete fixed census timer path and document the adaptive
orchestrator as the supported production strategy. This slice is deployment and
documentation focused.

## Expected behavior

Implement and validate:

1. `deploy/README.md` no longer recommends `sirhosp-census.timer` or a fixed
   8-hour census schedule.
2. Obsolete census timer artifacts are removed or clearly replaced so operators
   cannot accidentally install the fixed timer path.
3. Documentation explains that the worker still runs continuously with
   `process_ingestion_runs --loop --sleep-seconds 5`.
4. Documentation explains how to run the adaptive orchestrator continuously.
5. If adding a systemd unit, it must be a long-running service for
   `run_adaptive_census_cycles --loop`, not an `OnCalendar` timer.
6. Troubleshooting covers active queue, stale running runs, source-system
   failures and how to fall back to manual execution.

## Suggested files

Prefer no more than 5 changed files.

Likely files:

- `deploy/README.md`
- `deploy/systemd/sirhosp-census-orchestrator.service` if service guidance is
  provided as a unit file
- Remove `deploy/census-scheduler.sh` if no longer used
- Remove `deploy/systemd/sirhosp-census.service` if no longer used
- Remove `deploy/systemd/sirhosp-census.timer`

Do not change application orchestration code in this slice unless a small docs
mismatch is discovered and clearly justified.

## Engineering constraints

- Use small, precise documentation changes.
- Keep Markdown valid with the project markdownlint configuration.
- Do not use `<!-- markdownlint-disable -->` comments.
- Do not add a fixed schedule, cron expression or `OnCalendar` replacement for
  censo.
- Keep instructions copy-pasteable and credential-safe.
- Apply YAGNI: no packaging, no installer script, no broad deploy rewrite.

## Acceptance checklist

- There is no documented fixed census timer path.
- The adaptive orchestrator service path is clear.
- The manual fallback remains documented.
- All changed Markdown passes `./scripts/markdown-lint.sh`.
- Removed files are listed explicitly in the report.

## Validation commands

Run documentation and project validation:

```bash
./scripts/markdown-lint.sh
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
openspec validate adaptive-census-orchestrator --type change --strict
```

If shell scripts or systemd files are changed, also run any available shell or
static checks used by the project. Do not invent a broad deploy test harness.

## Required report

Create `/tmp/sirhosp-slice-ACO-S4-report.md` with:

- summary of deploy and documentation changes;
- files changed or removed;
- before/after snippets for documentation and unit files;
- commands executed and results;
- confirmation that no fixed census timer remains documented;
- manual rollback/fallback instructions;
- risks, pending work and next suggested step.

Stop after the report. Do not archive the change unless explicitly asked.
