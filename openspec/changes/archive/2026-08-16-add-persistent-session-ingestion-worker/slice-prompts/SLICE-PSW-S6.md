# SLICE PSW-S6: Runtime Rollout Guidance and A/B Observability

## Handoff for Context-Zero Executor

You are implementing only slice PSW-S6 for OpenSpec change
`add-persistent-session-ingestion-worker` in SIRHOSP.

## Branch Isolation

This feature MUST be implemented only on branch
`feature/add-persistent-session-ingestion-worker`.

Before coding, verify:

```bash
git branch --show-current
git status --short
```

If not already on that branch, stop when unrelated changes are present. If the
tree is clean or contains only this change's planning artifacts, switch or
create the branch:

```bash
git switch feature/add-persistent-session-ingestion-worker || \
  git switch -c feature/add-persistent-session-ingestion-worker
```

Do not mix this feature with other OpenSpec changes, unrelated fixes, or
opportunistic refactors. Include the active branch and `git status --short` in
the required report.

Active OpenSpec change directories are ignored by `.gitignore` here. If the
branch must carry planning artifacts, force-add this change directory
explicitly on the feature branch.

Read first:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md` if present
3. `openspec/changes/add-persistent-session-ingestion-worker/proposal.md`
4. `openspec/changes/add-persistent-session-ingestion-worker/design.md`
5. All specs under
   `openspec/changes/add-persistent-session-ingestion-worker/specs/`
6. The code and reports from PSW-S1 through PSW-S5
7. `deploy/README.md`
8. `compose.prod.yml` and `compose.dev.yml` if Compose examples are needed

Implement rollout guidance and A/B observability only. Do not add new scraping
behavior in this slice.

## PSW-S5 Verification Notes to Address

The PSW-S5 verifier documented that the persistent worker is **not
rollout-ready** yet:

- full-sync persistence is not implemented; `full_sync` runs fail terminally
  with `full_sync_not_implemented`;
- real `PlaywrightSessionHandle` exists only as an opt-in integration boundary
  and cannot yet satisfy the adapter's synthetic snapshot/evolution container
  contract against the real legacy UI;
- `_create_session_handle()` returns the stub by default, and `--real-handle`
  is for controlled integration experiments only.

Therefore PSW-S6 must not publish production instructions that imply the
persistent worker can already replace or share production load with the current
worker. The docs may describe the intended A/B plan as a **future rollout plan**
or a **lab/staging experiment**, but must prominently list blocker 5.8 and the
real-handle container contract as prerequisites for production rollout.

## Scope

Target maximum changed files: 6.

Expected files:

- deployment or operations documentation updates;
- optional Compose/systemd examples only if clearly disabled or marked as
  lab/staging examples until blocker 5.8 is resolved;
- optional tests for rendered Compose/runtime configuration if existing project
  patterns support that;
- OpenSpec task/spec checkbox updates only if appropriate.

Every changed Markdown file must pass project markdown lint. Do not use
`markdownlint-disable` comments.

If you need more than 6 files, stop and report a blocker.

## Development Method

Use TDD/verification-first where applicable:

1. If changing Compose/systemd, add or update tests/checks first when existing
   patterns exist.
2. Make the smallest documentation/runtime update needed.
3. Run markdown format/lint and relevant project gates.

Follow clean code, DRY, and YAGNI:

- document only operations that are supported by implemented code;
- clearly separate current non-rollout-ready status from future rollout plan;
- do not invent dashboards or admin UI unless already implemented;
- prefer concise SQL/Django shell examples over new UI work;
- keep rollback simple.

## Required Behavior

Document how to:

- identify the current status: persistent worker is not production rollout-ready
  until blocker 5.8 and the real-handle container contract are resolved;
- run current and persistent-session workers side-by-side only as future
  production rollout guidance or controlled lab/staging experiment;
- set distinct labels, for example current workers with a legacy prefix and
  persistent workers with a persistent-session prefix;
- scale worker groups without sharing browser profile directories, but only
  after rollout prerequisites are met;
- compare metrics by worker group:
  - run count;
  - success rate;
  - failure rate;
  - timeout rate;
  - queue latency;
  - processing duration mean/p50/p95;
  - attempts;
  - stale recovery indicators;
- inspect runtime resources:
  - temporary/profile/cache directories;
  - `/dev/shm`;
  - RAM and swap;
  - Docker logs;
  - tmpfs limits;
- roll back by stopping persistent-session workers and scaling current workers
  back to the previous count;
- keep current production workers as the supported production path until the
  documented blockers are resolved.

## Acceptance Criteria

- Docs state prominently that the persistent worker is not production
  rollout-ready while full-sync persistence and the real-handle container
  contract remain unresolved.
- Operators can follow docs for a future initial 6 legacy plus 6 persistent
  worker experiment, or a controlled lab/staging experiment now, without
  confusing it for current production guidance.
- Docs warn that faster workers may consume more than half of jobs, so analysis
  must compare per-group rates and durations.
- Docs state that profile/user-data directories must be exclusive per worker.
- Docs include rollback steps.
- Docs do not add enabled production Compose/systemd services for the persistent
  worker unless they are clearly disabled and guarded as examples.
- Markdown lint passes without disable comments.
- No real patient data, credentials, cookies, screenshots, PDFs, debug HTML, or
  source-system secrets are documented.

## Validation Commands

Run at minimum:

```bash
./scripts/markdown-format.sh
./scripts/markdown-lint.sh
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

If code/runtime config changed, also run relevant unit or integration tests. If
container validation is unavailable, run the closest diagnostic command and
explain the limitation in the report.

## Required Report

Create `/tmp/sirhosp-slice-PSW-S6-report.md` with:

- slice summary;
- acceptance checklist;
- files changed;
- before/after snippets for each changed file;
- commands executed and results;
- active branch and `git status --short` summary;
- risks, pending items, and suggested next step.

Stop after this slice.
