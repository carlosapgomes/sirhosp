# Slice DHRR-S2 Prompt: Historical Recovery Operator Documentation

## Handoff for a zero-context implementer

You are implementing only Slice DHRR-S2 of OpenSpec change
`dedicated-historical-recovery-runtime` in the SIRHOSP repository.

Slice DHRR-S1 should already have added the production `historical_recovery`
Compose service/runtime. This slice updates operator-facing documentation and
focused documentation tests so future operators know how to run, validate,
monitor and roll back historical recovery batches using the dedicated tmpfs
runtime.

The runtime is batch-only: it is used with manual `docker compose run --rm`
commands. It is not a long-running daemon, not a timer and not a queue worker.

Read these files completely before coding:

- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `openspec/changes/dedicated-historical-recovery-runtime/proposal.md`
- `openspec/changes/dedicated-historical-recovery-runtime/design.md`
- `openspec/changes/dedicated-historical-recovery-runtime/specs/production-historical-recovery-runtime/spec.md`
- `openspec/changes/dedicated-historical-recovery-runtime/specs/historical-recovery-command/spec.md`
- `openspec/changes/dedicated-historical-recovery-runtime/tasks.md`
- `compose.prod.yml`
- `deploy/README.md`
- `README.md`
- `tests/unit/test_deploy_worker_tmpfs_guidance.py`

## Scope

Implement only operator documentation and focused documentation tests.

Allowed repository files for this slice:

- `deploy/README.md`
- one focused unit test file under `tests/unit/`
- `README.md` only if it contains now-inaccurate production historical recovery
  commands after DHRR-S1
- `AGENTS.md` only if it contains now-inaccurate production historical recovery
  commands after DHRR-S1
- `openspec/changes/dedicated-historical-recovery-runtime/tasks.md`, only if
  you mark completed DHRR-S2 tasks after evidence exists

Do not modify Compose, systemd, Python code, tests from DHRR-S1, database code
or scraping code in this slice. If documentation exposes a missing runtime
requirement, stop and report the blocker instead of changing runtime files.

## Documentation intent

Update `deploy/README.md` so manual production historical recovery uses the
`historical_recovery` runtime, not the portal `web` container, for normal
batch operation.

The docs must cover:

- why the dedicated batch runtime exists;
- that it is manual/batch-only, not a daemon, loop, timer or Celery/Redis
  worker;
- how to run a `--dry-run` through the dedicated runtime;
- how to run a single-date real batch;
- how to run a date-range real batch;
- how to select one extractor with `--extractor`, for example `admissions`;
- how to select multiple extractors by repeating `--extractor`;
- the valid extractor names: `discharges`, `admissions`, `deaths` and
  `official_census`;
- that selected extractors still run in default deterministic order;
- how to validate tmpfs and `/dev/shm` inside the recovery container;
- how to check Docker status, logs, `docker stats`, host RAM and host disk
  writes with `iostat` or equivalent;
- all `HISTORICAL_RECOVERY_*` sizing variables and defaults;
- `ENOSPC` and Chromium shared-memory troubleshooting;
- warning not to run multiple heavy historical recovery batches in parallel
  without explicit operational approval;
- warning not to print, commit or paste real secrets from `docker compose
  config`;
- rollback/fallback: stop using the dedicated runtime and run the existing
  command path through `web` only for emergency diagnosis while fixing the
  runtime.

Keep the documentation concise. Prefer commands with synthetic dates and no
real credentials. Do not include patient data, real source URLs or secrets.

## Engineering methodology

Use TDD, clean code, DRY and YAGNI:

1. **Red:** add focused documentation tests that fail because deploy docs do not
   yet describe the dedicated historical recovery runtime.
2. **Green:** update only the documentation needed to satisfy the tests and
   specs.
3. **Refactor:** remove duplication and improve headings without broadening the
   scope.

The test may read Markdown as plain text, matching the style of
`tests/unit/test_deploy_worker_tmpfs_guidance.py`. Avoid brittle full-paragraph
assertions; check meaningful tokens, command fragments and section presence.

Suggested test coverage:

- docs mention `historical_recovery` and `--profile recovery`;
- docs show `docker compose ... run --rm historical_recovery`;
- docs show `recover_historical_data --dry-run`;
- docs show `--date`, `--start-date`, `--end-date` examples;
- docs show single and repeated `--extractor` usage;
- docs list all valid extractor names;
- docs mention tmpfs and `/dev/shm` validation;
- docs mention `docker stats`, logs, RAM and `iostat`/host write checks;
- docs list all five `HISTORICAL_RECOVERY_*` variables and defaults;
- docs mention `ENOSPC`, Chromium/shared memory, parallel-run warning,
  rollback/fallback and secret safety.

## Required validation

Run at least:

```bash
./scripts/test-in-container.sh unit
./scripts/markdown-lint.sh
openspec validate dedicated-historical-recovery-runtime --type change --strict
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
- `deploy/README.md` recommends `historical_recovery` for production manual
  historical recovery batches.
- Docs preserve single-date, date-range, `--dry-run`, single-extractor and
  multiple-extractor workflows.
- Docs include tmpfs, `/dev/shm`, Docker status/logs/stats, RAM and host
  disk-write validation guidance.
- Docs list `HISTORICAL_RECOVERY_SHM_SIZE` and the four
  `HISTORICAL_RECOVERY_TMPFS_*` variables.
- Docs include `ENOSPC`/Chromium troubleshooting, parallel-run warning,
  rollback/fallback instructions and secret-safety warning.
- Top-level docs are touched only if they were inaccurate.
- Markdown lint passes without `markdownlint-disable` comments.
- No credentials, patient data, PDFs, dumps or debug artifacts are committed.

## Required report

Create `/tmp/sirhosp-slice-DHRR-S2-report.md` with:

- summary of the slice;
- checklist of acceptance criteria;
- files changed;
- before/after snippets for every changed repository file;
- red/green/refactor evidence;
- commands executed and results;
- OpenSpec and markdown-lint results;
- risks, pending work and final next step.

Do not include real credentials or patient data in the report.
