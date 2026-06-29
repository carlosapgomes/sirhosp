# Slice DCOS-S2 Prompt: Operator Documentation and Validation Guidance

## Handoff for a zero-context implementer

You are implementing only Slice DCOS-S2 of OpenSpec change
`dedicated-census-orchestrator-service` in the SIRHOSP repository.

Slice DCOS-S1 should already have added the production `census_orchestrator`
service and updated the systemd unit. This slice updates operator-facing
documentation and tests so future operators know how to start, validate,
monitor and roll back the dedicated runtime.

Read these files completely before coding:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/dedicated-census-orchestrator-service/proposal.md`
- `openspec/changes/dedicated-census-orchestrator-service/design.md`
- `openspec/changes/dedicated-census-orchestrator-service/specs/production-census-orchestrator-runtime/spec.md`
- `openspec/changes/dedicated-census-orchestrator-service/specs/adaptive-census-orchestration/spec.md`
- `openspec/changes/dedicated-census-orchestrator-service/tasks.md`
- `compose.prod.yml`
- `deploy/systemd/sirhosp-census-orchestrator.service`
- `deploy/README.md`

## Scope

Implement only documentation and documentation tests.

Allowed repository files for this slice:

- `deploy/README.md`
- one focused unit test file under `tests/unit/`
- `README.md` only if it contains now-inaccurate production orchestrator
  commands after DCOS-S1
- `AGENTS.md` only if it contains now-inaccurate production orchestrator
  commands after DCOS-S1
- `openspec/changes/dedicated-census-orchestrator-service/tasks.md`, only if
  you mark completed DCOS-S2 tasks after evidence exists

Do not modify Compose, systemd, Python code, tests from DCOS-S1, database code
or scraping code in this slice. If documentation exposes a missing runtime
requirement, stop and report the blocker instead of changing runtime files.

## Documentation intent

Update `deploy/README.md` so the recommended production loop uses the dedicated
`census_orchestrator` service, not a long-lived `docker compose exec -T web`
process.

The docs must cover:

- why the dedicated service exists;
- how to start it manually, for example with `docker compose ... --profile
  orchestrator up -d census_orchestrator`;
- how to run `--dry-run` and `--once` using the dedicated service for volatile
  runtime validation;
- how to install/enable the updated systemd unit;
- how the systemd `ExecStart` foreground behavior, `--abort-on-container-exit`
  and `Restart=on-failure` interact during container exit/restart scenarios;
- how to check status and logs;
- how to validate tmpfs and `/dev/shm` inside the orchestrator container;
- how to compare host disk writes with `iostat` or an equivalent host-level
  command;
- all `CENSUS_ORCHESTRATOR_*` sizing variables and conservative defaults;
- ENOSPC/shared-memory troubleshooting;
- rollback and disable procedure;
- warning not to run the old `web` loop and the dedicated service in parallel;
- warning not to print or commit real secrets from `docker compose config`.

Keep the documentation concise. Prefer commands that use synthetic placeholders
where secrets would otherwise be shown. Do not include real credentials.

## Engineering methodology

Use TDD, clean code, DRY and YAGNI:

1. **Red:** add focused documentation tests that fail because deploy docs still
   describe the old `web` execution path or lack dedicated service validation.
2. **Green:** update only the documentation needed to satisfy the tests and
   specs.
3. **Refactor:** remove duplication and improve headings without broadening the
   scope.

The test may read Markdown as plain text, matching the style of
`tests/unit/test_deploy_worker_tmpfs_guidance.py`. Avoid brittle full-paragraph
assertions; check meaningful tokens and section presence.

## Required validation

Run at least:

```bash
./scripts/test-in-container.sh unit
./scripts/markdown-lint.sh
openspec validate dedicated-census-orchestrator-service --type change --strict
```

If time and environment allow, also run:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

If a command cannot run, document the reason clearly.

## Acceptance criteria

- The focused documentation tests fail before documentation changes and pass
  after implementation.
- `deploy/README.md` recommends `census_orchestrator` for the continuous
  production loop.
- Docs preserve manual `--dry-run` and `--once` workflows and use the dedicated
  service when validating volatile runtime behavior.
- Docs include tmpfs, `/dev/shm`, Docker status/logs and host disk-write
  validation guidance.
- Docs list `CENSUS_ORCHESTRATOR_SHM_SIZE` and the four
  `CENSUS_ORCHESTRATOR_TMPFS_*` variables.
- Docs include rollback/disable instructions and the parallel-loop warning.
- Top-level docs are touched only if they were inaccurate.
- Markdown lint passes without `markdownlint-disable` comments.
- No credentials, patient data, PDFs, dumps or debug artifacts are committed.

## Required report

Create `/tmp/sirhosp-slice-DCOS-S2-report.md` with:

- summary of the slice;
- checklist of acceptance criteria;
- files changed;
- before/after snippets for every changed repository file;
- red/green/refactor evidence;
- commands executed and results;
- OpenSpec and markdown-lint results;
- risks, pending work and final next step.

Do not include real credentials or patient data in the report.
