# Tasks: Reduce Worker Scraping Disk Writes

## 1. Slice S1: Production worker runtime config

- [x] 1.1 Read `AGENTS.md`, `PROJECT_CONTEXT.md`, proposal, design, specs
  and `slice-prompts/SLICE-S1.md`.
- [x] 1.2 Add a focused failing unit test that characterizes the required
  `worker` settings in `compose.prod.yml`.
- [x] 1.3 Update only the production `worker` service with `tmpfs`, `shm_size`,
  temp/cache environment variables and Docker log rotation.
- [x] 1.4 Run the focused unit test, `docker compose config` with synthetic
  required environment variables, and relevant official validation commands.
- [x] 1.5 Write `/tmp/sirhosp-slice-RWSDW-S1-report.md` with before/after
  snippets, commands, results, risks and next-step recommendation.

## 2. Slice S2: Operator validation guidance

- [x] 2.1 Read `AGENTS.md`, `PROJECT_CONTEXT.md`, proposal, design, specs,
  current S1 report and `slice-prompts/SLICE-S2.md`.
- [x] 2.2 Add a focused failing unit test that requires concise deploy guidance
  for worker tmpfs validation in `deploy/README.md`.
- [x] 2.3 Update `deploy/README.md` with scaled-worker tmpfs configuration,
  override variables, validation commands and rollback notes.
- [x] 2.4 Run the focused unit test, markdown lint, and relevant official
  validation commands.
- [x] 2.5 Write `/tmp/sirhosp-slice-RWSDW-S2-report.md` with before/after
  snippets, commands, results, risks and next-step recommendation.

## 3. Final review

- [x] 3.1 Confirm all requirements in
  `specs/production-worker-runtime-io-control/spec.md` are satisfied.
- [x] 3.2 Confirm OpenSpec tasks are checked only after implementation evidence
  exists in the slice reports.
- [x] 3.3 Confirm no credentials, patient data, real PDFs, dumps or debug
  artifacts are included in the diff.
