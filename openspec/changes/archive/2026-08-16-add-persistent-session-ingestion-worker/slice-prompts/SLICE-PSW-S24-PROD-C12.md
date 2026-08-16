# Slice Prompt - PSW-S24-PROD-C12 Authorized Persistent Cutover

## Handoff

Start from zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the active
`add-persistent-session-ingestion-worker` OpenSpec change, the canonical PSW-S24
production reports, and this prompt. The operator explicitly accepts the
persistent-session implementation as the production path and does not require
a rollback rehearsal. Preserve the legacy service definition, but do not make
rollback readiness a gate for this slice.

## Scope

Implement and execute the first continuous persistent-session production
replica. The service must remain absent from default Compose startup and require
an explicit profile plus the command's existing `--enable-real-queue` opt-in.
Start one replica, collect only aggregate/sanitized evidence, tune parameters
only from observed behavior, and leave the persistent replica running if its
health is acceptable.

Maximum versioned files changed: six.

Allowed versioned files:

1. `compose.prod.yml`;
2. `tests/unit/test_prod_persistent_worker_runtime.py`;
3. `docs/operations/persistent-worker-rollout.md`;
4. `openspec/changes/add-persistent-session-ingestion-worker/design.md`;
5. `openspec/changes/add-persistent-session-ingestion-worker/tasks.md`;
6. this prompt.

Create `/tmp/sirhosp-slice-PSW-S24-PROD-C12-report.md`. Do not alter source
extractors, queue semantics, models, migrations, the legacy worker command, or
patient data.

## Implementation Contract

Use TDD:

1. Add a failing characterization test for a default-off
   `persistent_worker` production Compose service.
2. Require the exact continuous real command:
   `process_ingestion_runs_persistent_session --loop --sleep-seconds 5
   --real-handle --enable-real-queue`.
3. Require a distinct `persistent-worker` label, source credentials and proxy,
   exclusive volatile runtime paths, bounded log rotation, `init: true`, and
   production restart behavior.
4. Use distinct `PERSISTENT_WORKER_*` sizing variables. Do not share mutable
   Chromium profile directories.
5. Reconcile the rollout runbook and OpenSpec design/tasks with the authorized
   cutover and the already-completed real admissions, demographics, full-sync,
   evolutions/PDF, restart/rebootstrap, renewal, cleanup, and stale-disposal
   proofs.
6. Keep the Compose service behind an explicit profile so ordinary production
   `up` commands do not start it accidentally.

## Production Execution

After tests and official gates pass, commit and push before production action.
On the authorized production host:

1. deploy the committed revision;
2. build the production image;
3. start exactly one `persistent_worker` replica through its explicit profile;
4. verify only one replica exists and the legacy worker remains stopped;
5. observe aggregate queue movement, status/success counts, attempts, duration,
   queue latency, worker heartbeat, restart/renewal/authentication messages,
   container RSS/CPU, `/dev/shm`, tmpfs/profile use, and Docker log size;
6. never print run IDs, patient identifiers, source URLs, credentials, cookies,
   HTML, PDFs, or clinical text;
7. stop and diagnose on authentication loops, stale heartbeat, repeated
   restart, cleanup failures, runaway retries, resource exhaustion, or
   unsanitized output.

One replica is sufficient for this slice. Scale only when the first replica has
observable healthy throughput and resource headroom.

## Acceptance

- The characterization test is recorded RED before implementation and GREEN
  after it.
- Official Django check, unit, lint, and typecheck gates pass.
- Strict OpenSpec validation and Markdown lint pass.
- The branch is committed, pushed, and clean before production deployment.
- Production runs the committed persistent service with exactly one replica.
- Aggregate evidence proves queue progress and healthy process/session state,
  or the report is `INCOMPLETE/BLOCKED` with the replica stopped.
- The report contains literal before/after fragments for every changed file,
  commands and results, sanitized measurements, risks, and next action.
