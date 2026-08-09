# Slice Prompt - PSW-S24-PROD-C12-R1 Continuous Output Sanitization

## Handoff

Start from zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the active
OpenSpec change, `/tmp/sirhosp-slice-PSW-S24-PROD-C12-report.md`, and this
prompt. C12 started one production persistent replica and proved healthy initial
throughput and resource use, but the continuous command emitted database run
primary keys in ordinary success and auto-follow-up messages. The safety guard
stopped the replica. Implement the forward correction and restart one replica.

## Scope

Maximum versioned files changed: five.

1. `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py`
2. `tests/unit/test_persistent_worker_command.py`
3. `openspec/changes/add-persistent-session-ingestion-worker/specs/persistent-session-ingestion-worker/spec.md`
4. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`
5. this prompt.

Create `/tmp/sirhosp-slice-PSW-S24-PROD-C12-R1-report.md`. Do not alter queue
semantics, models, migrations, source actions, clinical persistence, Compose,
or the single-smoke operator diagnostic.

## TDD Contract

1. Add a failing regression proving real continuous mode emits no `Run #<pk>`,
   `run #<pk>`, selected primary key, or auto-enqueued follow-up primary key on
   stdout or stderr.
2. Exercise at least admissions success and its auto-enqueued follow-ups through
   the real continuous command path.
3. Implement the smallest source fix at the shared output-label boundary.
4. Preserve bounded sanitized ordinals.
5. Preserve stub and selected single-smoke labels because the latter is an
   explicit operator-selected diagnostic.
6. Continuous labels may state `Continuous run` and `follow-up`; they must not
   contain source or patient identifiers.

## Verification and Production

Run the focused RED and GREEN tests, official quality gate, strict OpenSpec
validation, and Markdown lint. Commit and push before rebuilding production.
Then rebuild and restart exactly one `persistent_worker` replica. Observe
aggregate outcomes/resources and inspect logs only for structural sanitation;
do not copy any identifier into reports or chat. Stop immediately if any
primary key, source identifier, credential, URL, cookie, HTML, PDF, or clinical
text appears.

## Acceptance

- RED fails because continuous output contains primary keys.
- GREEN proves continuous output is sanitized across success and follow-up
  messages.
- Official gates pass and the correction is pushed.
- Production runs the corrected commit with exactly one persistent replica.
- At least one corrected terminal success is observed with no new failures,
  timeout, restart, OOM, or identifier-bearing output.
- The final report contains literal before/after fragments, commands/results,
  aggregate measurements, and current service state.
