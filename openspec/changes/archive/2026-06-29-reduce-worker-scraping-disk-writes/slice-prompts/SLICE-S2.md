# Slice S2 Prompt: Operator Validation Guidance

## Handoff for a zero-context implementer

You are implementing only Slice S2 of OpenSpec change
`reduce-worker-scraping-disk-writes` in the SIRHOSP repository.

Slice S1 should already have configured the production `worker` service with
`tmpfs`, `shm_size`, temp/cache environment variables and Docker log rotation.
This slice adds concise operator guidance for running and validating that setup
in production.

Read these files before coding:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/reduce-worker-scraping-disk-writes/proposal.md`
- `openspec/changes/reduce-worker-scraping-disk-writes/design.md`
- `openspec/changes/reduce-worker-scraping-disk-writes/specs/production-worker-runtime-io-control/spec.md`
- `openspec/changes/reduce-worker-scraping-disk-writes/tasks.md`
- `/tmp/sirhosp-slice-RWSDW-S1-report.md`, if present

## Scope

Implement only operator guidance for the production worker tmpfs setup.

Allowed repository files for this slice:

- `deploy/README.md`
- one focused unit test file under `tests/unit/`
- `openspec/changes/reduce-worker-scraping-disk-writes/tasks.md`, only if you
  mark completed S2 tasks after evidence exists

Do not modify Compose files, scraper Python code, Dockerfile, database code,
summary worker, web service or Tailscale service in this slice.

If S1 was not implemented or the needed runtime config is absent, stop and
report the blocker instead of compensating in this slice.

## Documentation intent

Update the worker section of `deploy/README.md` with concise guidance covering:

- the fact that production `worker` uses tmpfs for Playwright/Python temporary
  files and cache/config directories;
- default sizing for `/tmp`, `/var/tmp`, cache, config and `/dev/shm`;
- `.env` override variables for operators;
- how to run up to 15 workers;
- how to inspect `/tmp`, `/dev/shm`, Docker `BlockIO`, RAM and swap;
- what to do if `/tmp` fills or Chromium needs more shared memory;
- rollback at a high level;
- warning not to print or commit real secrets from `docker compose config`.

Keep the documentation short. Do not add a large operations manual.

## Engineering methodology

Use TDD, clean code, DRY and YAGNI:

1. Red: add a focused unit test that fails because `deploy/README.md` does not
   yet include the required tmpfs validation guidance.
2. Green: make the smallest documentation update that satisfies the test and
   spec.
3. Refactor: simplify wording or the test without broadening scope.

The test should avoid new dependencies and should check meaningful tokens or
sections rather than brittle full paragraphs.

## Required validation

Run at least:

```bash
./scripts/test-in-container.sh unit
./scripts/markdown-lint.sh
```

If time and environment allow, also run:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

If a command cannot run, document the reason clearly.

## Acceptance criteria

- The focused test fails before the docs change and passes after it.
- `deploy/README.md` documents tmpfs behavior for production `worker`.
- The docs list the override variables: `WORKER_SHM_SIZE`,
  `WORKER_TMPFS_TMP_SIZE`, `WORKER_TMPFS_VAR_TMP_SIZE`,
  `WORKER_TMPFS_CACHE_SIZE` and `WORKER_TMPFS_CONFIG_SIZE`.
- The docs include validation commands for `/tmp`, `/dev/shm`, Docker
  `BlockIO`, RAM and swap.
- The docs include what to do for `ENOSPC` or Chromium shared-memory issues.
- Markdown lint passes without disabling rules.
- No credentials, patient data, PDFs, dumps or debug artifacts are committed.

## Required report

Create `/tmp/sirhosp-slice-RWSDW-S2-report.md` with:

- summary of the slice;
- checklist of acceptance criteria;
- files changed;
- before/after snippets for every changed repository file;
- red/green/refactor evidence;
- commands executed and results;
- risks, pending work and suggested next step.

Do not include real credentials or patient data in the report.
