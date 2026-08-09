# Persistent-Session Ingestion Worker — Runtime Rollout and A/B Observability

> **Status: ACTIVE WITH ONE PRODUCTION REPLICA (PSW-S24-PROD-C12-R1).**
>
> The operator accepted the persistent-session worker as the production path
> after the guarded PSW-S24 proof. One corrected replica is now running; the
> legacy consumer remains stopped. A rollback rehearsal is not a cutover gate,
> and the authorized path is forward operation plus production tuning.
>
> Completed production evidence covers:
>
> 1. real authentication and action-based JSP/PrimeFaces navigation;
> 2. admissions, demographics, full-sync, and evolution/PDF extraction;
> 3. four ordered jobs through one session, including cleanup after each job;
> 4. controlled restart and rebootstrap before a later claim;
> 5. a 30-minute idle session, popup-scoped renewal, popup clearance, and
>    countdown advancement;
> 6. terminal disposal of the 12 abandoned `running` rows, leaving zero stale
>    or running rows before cutover;
> 7. an initial continuous canary that exposed run primary keys in inherited
>    command messages and was stopped by the output-safety guard; and
> 8. the C12-R1 correction, followed by 11 successful jobs through one restarted
>    replica with sanitized logs, no timeout, retry, restart, or OOM.
>
> Continuous real execution still requires two independent guards:
>
> - the production Compose service is behind the explicit
>   `persistent-worker` profile; and
> - the command requires `--real-handle --loop --enable-real-queue`.
>
> Start with one replica. Measure aggregate queue progress, status, attempts,
> duration, queue latency, RSS/CPU, shared memory, tmpfs/profile use, and log
> growth. Do not expose run IDs, patient identifiers, source URLs, credentials,
> cookies, HTML, PDFs, or clinical text.
>
> Latest C12-R1 observation: 22 successes (11 admissions and 11 demographics),
> 12.68-second mean and 15.31-second maximum processing time, one attempt
> maximum, zero timeouts, 251.1 MiB final RSS (309.1 MiB earlier observation),
> 7 MiB final `/tmp`, empty profile/cache tmpfs, and zero container restarts.
> The replica remained running; the queue moved from 1,332 to 1,329 while
> admissions follow-ups were enqueued.

---

## 1. Before you begin

### 1.1 Satisfied prerequisites

- `RealHandleBridge` translates the real legacy UI into the persistent
  adapter contract.
- Real bootstrap, authentication, action navigation, PDF download, and
  extraction passed guarded production validation.
- Admissions, demographics, full-sync, and evolutions passed through one
  authenticated session.
- Restart/rebootstrap, cleanup, renewal, and sanitized failure boundaries were
  observed in production.
- The official containerized quality gates passed for the committed runtime
  corrections.
- The operator explicitly authorized forward cutover and accepted production
  tuning without a rollback rehearsal.

Full-sync persistence uses the shared
`apps.ingestion.evolution_ingestion.ingest_evolutions` service. Runtime
thresholds begin at the tested defaults and may be adjusted from sanitized
production measurements.

### 1.2 Lab/staging experiment (available now)

You can run the persistent worker in a **controlled lab/staging environment**
with zero production DB impact:

```bash
# Single pass (uses safe stub — no Chromium, no real DB mutations unless
# pointed at a lab DB)
uv run python manage.py process_ingestion_runs_persistent_session

# Continuous loop with stub (safe — only processes runs manually enqueued
# in lab)
uv run python manage.py process_ingestion_runs_persistent_session \
    --loop --sleep-seconds 5
```

The worker defaults to the `_StubSessionHandle`, which returns empty results
and never launches a browser. It is safe for integration experiments and
command-line validation.

The real Chromium path is production-authorized. For a single selected smoke,
use `--real-handle --run-id ID --max-runs 1`. For an ordered two-to-four-row
proof, repeat `--validation-run-id` and set `--max-runs` to the exact count.
The continuous service uses the separately guarded command documented below.

All real modes bootstrap authentication before any claim. Credentials and
passwords must never be logged. Bootstrap, navigation, renewal, and PDF-flow
failures use sanitized messages.

### 1.3 Real-handle CLI mode matrix (PSW-S24-PRE)

The `--real-handle` path exposes a closed CLI mode matrix validated before any
adapter/browser creation or run mutation. Guarded and continuous modes passed
authorized PSW-S24 validation; the continuous mode additionally requires the
explicit Compose profile and command opt-in.

| Mode | Flags | Owns |
| --- | --- | --- |
| stub | (no `--real-handle`) | all eligible |
| single smoke | `--real-handle --run-id ID --max-runs 1` | one ID |
| bounded | `--real-handle` + `--validation-run-id` x2-4 + cap | listed only |
| continuous | `--real-handle --loop --enable-real-queue` | enabled |

Bounded validation is the intended PSW-S24 live-validation surface: an operator
lists two through four queued run IDs in operator order WITH `--real-handle`
and an exact `--max-runs` cap. Every listed row is preflichted (queued,
retry-due, supported intent) before one real adapter/bootstrap; the listed jobs
reuse the same authenticated session; processing never falls through to an
unlisted row; and a claim race, a job that does not finish as `succeeded`, or a
restart/rebootstrap failure leaves every later selected row queued and
untouched. Bounded output carries no run IDs or source data — only ordinal,
count, stage, and normalized-reason information.

```bash
# Bounded production diagnostic with operator-approved queued IDs:
uv run python manage.py process_ingestion_runs_persistent_session \
    --real-handle \
    --validation-run-id <ID_1> --validation-run-id <ID_2> \
    --max-runs 2
```

`--real-handle --loop` without the explicit `--enable-real-queue` opt-in fails
before adapter/browser creation. The opt-in is forbidden with `--run-id`,
`--validation-run-id`, or `--max-runs`, and it reuses the existing queue,
locking, readiness, and shutdown paths without creating a new worker, queue, or
deployment default.

> Real IDs, patient identifiers, clinical content, URLs, credentials, cookies,
> HTML, and PDFs must never be logged in any mode.

---

## 2. Production cutover

### 2.1 Worker identity and labels

Each worker group must use distinct `SIRHOSP_WORKER_LABEL` prefixes so
operators can group runs in metrics queries:

| Worker group | Label prefix | Command |
| --- | --- | --- |
| Legacy | `legacy-worker` | `process_ingestion_runs` |
| Persistent | `persistent-worker` | `...persistent_session` |

> Full persistent command: `process_ingestion_runs_persistent_session`

Labels are set via the `SIRHOSP_WORKER_LABEL` environment variable. Each
process appends its PID (`:<pid>`) for uniqueness:

```bash
# Legacy worker
SIRHOSP_WORKER_LABEL=legacy-worker

# Persistent worker
SIRHOSP_WORKER_LABEL=persistent-worker
```

When `SIRHOSP_WORKER_LABEL` is not set, the current worker uses the
built-in default and the persistent worker falls back to `persistent-worker`
as its prefix.

### 2.2 Authorized one-replica start

The versioned `persistent_worker` service is part of `compose.prod.yml` but is
excluded from normal startup by the `persistent-worker` profile. Starting it
also passes the command-level `--enable-real-queue` opt-in.

```bash
cd /opt/sirhosp

# Keep the legacy consumer stopped during the forward cutover.
docker compose -f compose.yml -f compose.prod.yml stop worker

# Build and start exactly one persistent replica.
docker compose -f compose.yml -f compose.prod.yml \
  --profile persistent-worker up -d --build \
  --scale persistent_worker=1 persistent_worker

# Confirm service cardinality and health.
docker compose -f compose.yml -f compose.prod.yml \
  --profile persistent-worker ps
```

The C12-R1 production start completed this exact one-replica procedure. The
legacy consumer remained stopped. Do not start it concurrently unless an
explicit operational decision changes the active consumer.

The service executes:

```text
process_ingestion_runs_persistent_session --loop --sleep-seconds 5
--real-handle --enable-real-queue
```

It uses `SIRHOSP_WORKER_LABEL=persistent-worker`, isolated tmpfs mounts,
bounded Docker log rotation, and a unique Chromium profile owned by the worker
process. Default lifecycle parameters are:

| Parameter | Initial value |
| --- | ---: |
| Maximum jobs per browser | 50 |
| Maximum browser lifetime | 3,600 seconds |
| Consecutive session failures | 3 |
| Renewal threshold | 600 seconds |
| Shared memory | 512 MiB |
| `/tmp` limit | 1 GiB |
| Cache limit | 256 MiB |

Do not scale beyond one replica until aggregate evidence shows healthy queue
progress, current heartbeats, bounded retries, no authentication/restart loop,
and resource headroom. Scaling remains explicit:

```bash
docker compose -f compose.yml -f compose.prod.yml \
  --profile persistent-worker up -d \
  --scale persistent_worker=2 persistent_worker
```

Every replica owns a separate container tmpfs and Chromium profile. Never share
a mutable `user-data-dir` across replicas.

### 2.3 Profile isolation rules

Each persistent worker process uses `ExclusiveBrowserProfile`, which creates
a unique temporary directory per browser lifetime:

- No two workers share a mutable Chromium `user-data-dir`.
- The profile is released on `shutdown()`.
- Host-level cleanup happens on container restart (tmpfs is volatile).

**Never** attempt to share browser profile directories across containers or
processes — this corrupts Chromium state and causes non-deterministic failures.

### 2.4 Faster worker caveat

Persistent workers skip the browser-startup and login cost per job. During
high-load periods, they may consume a disproportionate share of the queue.
Analysis must compare:

- **Per-group run count** (not just total throughput).
- **Per-group mean/p50/p95 duration** (persistent workers may be faster
  per run).
- **Per-group success rate** (persistent workers may encounter different
  failure modes).

Do not assume 6 + 6 means 50/50 workload distribution.

---

## 3. Observability queries

After side-by-side operation begins, use these queries to compare worker
groups. All queries group by the label prefix (before `:`) and expose no
patient data, clinical text, or credentials.

### 3.1 Django shell queries

```bash
# Open Django shell via web container
docker compose -f compose.yml -f compose.prod.yml exec web \
  uv run --no-sync python manage.py shell
```

```python
from django.db.models import Count, Avg, Q, F, Max, Min, Value
from django.db.models.functions import StrIndex, Left
from apps.ingestion.models import IngestionRun

# Group by label prefix (everything before the ':<pid>' suffix).
# e.g. 'legacy-worker:1234' -> 'legacy-worker'
prefix_expr = Left(
    "worker_label",
    StrIndex("worker_label", Value(":")) - 1,
)

# --- Run count and status distribution by group ---
(
    IngestionRun.objects
    .filter(worker_label__isnull=False)
    .annotate(group=prefix_expr)
    .values("group", "status")
    .annotate(count=Count("id"))
    .order_by("group", "status")
)
```

```python
# --- Success rate by group ---
from django.db.models import Case, When, IntegerField

(
    IngestionRun.objects
    .filter(worker_label__isnull=False, status__in=["succeeded", "failed"])
    .annotate(group=prefix_expr)
    .values("group")
    .annotate(
        total=Count("id"),
        succeeded=Count(Case(When(status="succeeded", then=1))),
    )
    .order_by("group")
)
```

```python
# --- Processing duration by group (mean, p50, p95) ---
(
    IngestionRun.objects
    .filter(
        worker_label__isnull=False,
        status="succeeded",
        processing_started_at__isnull=False,
        finished_at__isnull=False,
    )
    .annotate(
        group=prefix_expr,
        duration=F("finished_at") - F("processing_started_at"),
    )
    .values("group")
    .annotate(
        count=Count("id"),
        avg_duration=Avg("duration"),
        min_duration=Min("duration"),
        max_duration=Max("duration"),
    )
    .order_by("group")
)
```

```python
# --- Timeout rate by group ---
(
    IngestionRun.objects
    .filter(worker_label__isnull=False)
    .annotate(group=prefix_expr)
    .values("group")
    .annotate(
        total=Count("id"),
        timed_out=Count(Case(When(timed_out=True, then=1))),
    )
    .order_by("group")
)
```

```python
# --- Attempt distribution by group ---
(
    IngestionRun.objects
    .filter(worker_label__isnull=False)
    .annotate(group=prefix_expr)
    .values("group")
    .annotate(
        total=Count("id"),
        avg_attempts=Avg("attempt_count"),
        max_attempts=Max("attempt_count"),
    )
    .order_by("group")
)
```

```python
# --- Queue latency: time from created_at to processing_started_at ---
(
    IngestionRun.objects
    .filter(
        worker_label__isnull=False,
        processing_started_at__isnull=False,
    )
    .annotate(
        group=prefix_expr,
        latency=F("processing_started_at") - F("created_at"),
    )
    .values("group")
    .annotate(
        count=Count("id"),
        avg_latency=Avg("latency"),
        max_latency=Max("latency"),
    )
    .order_by("group")
)
```

### 3.2 Raw SQL queries

```sql
-- Run count and status by label prefix
SELECT
  SPLIT_PART(worker_label, ':', 1) AS worker_group,
  status,
  COUNT(*) AS run_count
FROM ingestion_ingestionrun
WHERE worker_label IS NOT NULL
GROUP BY 1, 2
ORDER BY 1, 2;

-- Success rate by worker group
SELECT
  SPLIT_PART(worker_label, ':', 1) AS worker_group,
  COUNT(*) AS total,
  SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded,
  ROUND(
    100.0 * SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) / COUNT(*),
    1
  ) AS success_pct
FROM ingestion_ingestionrun
WHERE worker_label IS NOT NULL
  AND status IN ('succeeded', 'failed')
GROUP BY 1
ORDER BY 1;

-- Processing duration percentiles (approximate with NTILE)
SELECT
  SPLIT_PART(worker_label, ':', 1) AS worker_group,
  COUNT(*) AS count,
  AVG(EXTRACT(EPOCH FROM (finished_at - processing_started_at))) AS avg_duration_s,
  MIN(EXTRACT(EPOCH FROM (finished_at - processing_started_at))) AS min_duration_s,
  MAX(EXTRACT(EPOCH FROM (finished_at - processing_started_at))) AS max_duration_s
FROM ingestion_ingestionrun
WHERE worker_label IS NOT NULL
  AND status = 'succeeded'
  AND processing_started_at IS NOT NULL
  AND finished_at IS NOT NULL
GROUP BY 1
ORDER BY 1;

-- Timeout rate by worker group
SELECT
  SPLIT_PART(worker_label, ':', 1) AS worker_group,
  COUNT(*) AS total,
  SUM(CASE WHEN timed_out THEN 1 ELSE 0 END) AS timed_out,
  ROUND(
    100.0 * SUM(CASE WHEN timed_out THEN 1 ELSE 0 END) / COUNT(*),
    1
  ) AS timeout_pct
FROM ingestion_ingestionrun
WHERE worker_label IS NOT NULL
GROUP BY 1
ORDER BY 1;

-- Stale recovery indicators: runs in 'running' state with stale heartbeat
SELECT
  SPLIT_PART(worker_label, ':', 1) AS worker_group,
  COUNT(*) AS stale_runs
FROM ingestion_ingestionrun
WHERE status = 'running'
  AND (
    worker_heartbeat_at IS NULL
    OR worker_heartbeat_at < NOW() - INTERVAL '10 minutes'
  )
GROUP BY 1
ORDER BY 1;
```

---

## 4. Resource inspection

### 4.1 Temporary files and profile directories

```bash
# Inspect tmpfs inside a worker container
docker compose -f compose.yml -f compose.prod.yml exec worker \
  sh -c 'df -h /tmp /var/tmp /dev/shm && ls -ld /tmp/xdg-cache /tmp/xdg-config'

# Check for leftover Chromium profiles in /tmp
docker compose -f compose.yml -f compose.prod.yml exec worker \
  sh -c 'find /tmp -maxdepth 2 -name "playwright_chromiumdev_profile-*" \
  -type d 2>/dev/null | head -20'
```

For persistent workers (when deployed), use the appropriate service name.

### 4.2 RAM, swap, and Docker stats

```bash
# Host RAM and swap
free -h
swapon --show

# Per-container CPU, memory, and Block I/O
docker stats --no-stream

# Filter for ingestion workers
docker stats --no-stream --format \
  "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.BlockIO}}" \
  | grep -E "NAME|ingestion|worker"
```

### 4.3 Docker logs

```bash
# Legacy worker logs (last 100 lines)
docker compose -f compose.yml -f compose.prod.yml logs --tail 100 worker

# Persistent worker logs
docker compose -f compose.yml -f compose.prod.yml \
  --profile persistent-worker logs --tail 100 persistent_worker

# Follow persistent logs in real time
docker compose -f compose.yml -f compose.prod.yml \
  --profile persistent-worker logs -f persistent_worker

### 4.4 Log growth monitoring

```bash
# Check log sizes on disk
docker compose -f compose.yml -f compose.prod.yml exec worker \
  du -sh /proc/1/fd/1 2>/dev/null || true

# Docker log driver rotation (configured in Compose)
# max-size: 10m, max-file: 3 per container
```

---

## 5. Emergency stop

Stopping the persistent consumer is an operational safety action, not a
required rollback rehearsal or cutover gate.

```bash
cd /opt/sirhosp

# Stop only the persistent consumer; keep web and database running.
docker compose -f compose.yml -f compose.prod.yml \
  --profile persistent-worker stop persistent_worker

# Confirm no persistent replica remains active.
docker compose -f compose.yml -f compose.prod.yml \
  --profile persistent-worker ps
```

### 5.2 Optional legacy fallback

The operator accepted forward cutover without requiring this path. The legacy
service definition remains available for an explicit operational decision:

```bash
docker compose -f compose.yml -f compose.prod.yml up -d --scale worker=1 worker
```

### 5.3 Verify fallback

```bash
# Confirm only legacy labels appear in recent runs
docker compose -f compose.yml -f compose.prod.yml exec web \
  uv run --no-sync python -c "
from apps.ingestion.models import IngestionRun
from django.utils import timezone
from datetime import timedelta
cutoff = timezone.now() - timedelta(hours=1)
runs = IngestionRun.objects.filter(
    worker_label__isnull=False,
    processing_started_at__gte=cutoff,
).values_list('worker_label', flat=True).distinct()
for label in runs:
    print(label)
"
```

All labels should start with `legacy-worker` (or the configured legacy
prefix). If any `persistent-worker` labels appear, persistent workers
are still running and must be stopped.

### 5.4 No data loss

Rollback does not affect PostgreSQL data. The persistent worker writes to the
same `IngestionRun`, `IngestionRunAttempt`, and `IngestionRunStageMetric`
tables as the legacy worker. Stopping persistent workers simply means those
workers stop claiming new runs; already-completed runs are durable.

---

## 6. Troubleshooting

| Problem | Likely cause | Action |
| --- | --- | --- |
| Synthetic container error | Handle contract | Add bridge layer |
| No runs claimed | Queue empty or stale | Check queued count via shell |
| Profile collision | Workers sharing tmpfs | Use unique paths per process |
| `ENOSPC` on `/tmp` | tmpfs too small | Increase TMPFS size |
| `SIGABRT` in `/dev/shm` | shm exhausted | Increase SHM size |
| Wrong label prefix | Env var not set | Set per-service env var |
| All jobs consumed | Faster throughput | Reduce scale or compare |
