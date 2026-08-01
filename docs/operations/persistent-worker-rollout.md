# Persistent-Session Ingestion Worker — Runtime Rollout and A/B Observability

> **⚠️ Status: NOT production rollout-ready (post-PSW-S11).**
>
> The persistent-session worker (`process_ingestion_runs_persistent_session`)
> is implemented and unit-tested, including persistent full-sync persistence,
> a ``RealHandleBridge`` that translates representative legacy DOM data into
> the adapter's synthetic container contract, a guarded real-legacy bootstrap
> and manual smoke path, and a persistent real evolution **PDF** extraction
> flow.
>
> **New live-validation finding:** the real legacy system is Java/JSP and does
> not expose reloadable patient/admission/evolution URLs. The PSW-S10 URL
> template assumption must be replaced by action-based Playwright navigation
> modeled after `automation/source_system/medical_evolution/path2.py` before
> guarded real smoke testing.
>
> **Progress:**
>
> 1. **PSW-S9 — real-handle container contract resolved in code** (not yet
>    production-validated). ``RealHandleBridge`` wraps the
>    ``PlaywrightSessionHandle`` and extracts admission data from the legacy
>    ``#tabelaInternacoes`` table rows and evolution data from
>    ``<script id="evolution-data-json">`` / ``<pre class="report-text">``
>    elements, rendering them inside ``<div id="admission-snapshot-data">``
>    and ``<div id="evolution-data">`` containers.
>
> 2. **PSW-S10 — real bootstrap and guarded manual smoke.** ``--real-handle``
>    now resolves credentials and real URL templates, bootstraps an
>    authenticated legacy session (navigate, login, and wait for
>    ``#tempoSessao``), and requires ``--run-id`` and ``--max-runs 1`` so a
>    manual smoke processes exactly one selected run and cannot drain the
>    queue or enter an idle loop.
>
> 3. **PSW-S11 — persistent real evolution PDF flow.** When the PSW-S9
>    lightweight fast paths (``evolution-data-json`` script,
>    ``pre.report-text``) yield no events, the adapter delegates to
>    ``RealHandleBridge.extract_evolutions_pdf``, which reuses the
>    already-open persistent page/context to apply the date window, generate
>    the report, download the PDF, extract text with PyMuPDF, and normalise
>    it into the evolution contract. No subprocess, no ``path2.py`` shell-out,
>    no fresh browser per job. This path has been validated with synthetic
>    PDF/text and fake Playwright objects only.
>
> 4. **Remaining prerequisites (blockers for production rollout):** replace
>    real-smoke URL-template navigation with action-based JSP/PrimeFaces
>    navigation (PSW-S12/PSW-S13), live validation of the bridge, bootstrap,
>    and PDF flow against the real legacy UI, and operational threshold tuning
>    (max-jobs, max-lifetime).
>
> 5. **PSW-S24-PRE — guarded real multi-run command surface (NOT
>    rollout-ready).** The `--real-handle` path now exposes a closed CLI mode
>    matrix: the single-run smoke is preserved; a bounded, ordered
>    `--validation-run-id` allow-list (two through four runs, one session,
>    restart before a later claim) is the intended PSW-S24 live-validation
>    surface; and the existing continuous real queue loop is reachable only
>    through an explicit default-off `--enable-real-queue` opt-in. Both real
>    multi-run modes stay disabled until authorized PSW-S24 live validation
>    succeeds.
>
> This document describes the **intended future rollout plan** and
> **controlled lab/staging experiment guidance**. Do not apply the scaling or
> side-by-side procedures in production until the prerequisites above are met.

---

## 1. Before you begin

### 1.1 Prerequisites (not yet fully met)

- ~~``PlaywrightSessionHandle`` able to extract real snapshot/evolution
  containers from the legacy UI.~~ **Implemented (PSW-S9)**:
  ``RealHandleBridge`` wraps the handle and translates legacy DOM data
  into the adapter's synthetic container contract.
- ~~Real-legacy bootstrap + guarded manual smoke.~~ **Implemented
  (PSW-S10)**: ``--real-handle`` resolves credentials and real URL
  templates, bootstraps an authenticated legacy session, and requires
  ``--run-id`` + ``--max-runs 1``.
- **Live validation against the real legacy UI** — not yet performed.
  The bridge, bootstrap, and PDF flow have been tested with representative
  HTML/PDF fakes and mocked Playwright only.
- ~~**PSW-S11: persistent real evolution PDF flow** — not yet implemented.~~
  **Implemented (PSW-S11)**: ``RealHandleBridge.extract_evolutions_pdf``
  reuses the already-open persistent page/context to download and normalise
  the real legacy evolution PDF, as a fallback after the PSW-S9 fast paths.
- **Operational threshold tuning** (max-jobs, max-lifetime) — pending.
- Containerized validation gate passing (`./scripts/test-in-container.sh quality-gate`).

Full-sync persistence is implemented through the shared
`apps.ingestion.evolution_ingestion.ingest_evolutions` service. Production
rollout remains blocked by the remaining prerequisites above (live
validation, threshold tuning).

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

To test with a real Chromium session (lab only, never production), use the
**guarded manual smoke** path added in PSW-S10. ``--real-handle`` requires
BOTH ``--run-id`` and ``--max-runs 1`` so a manual smoke processes exactly
one selected queued run and cannot drain the queue or enter an idle loop. It
also bootstraps a real authenticated legacy session (navigate + login + wait
for ``#tempoSessao``) before any run is claimed.

**Do not run the real-handle smoke against production yet.** Manual
validation confirmed that the real system does not support the URL-template
navigation assumed by PSW-S10. PSW-S12/PSW-S13 must first replace that path
with action-based Playwright navigation modeled after `path2.py`.

After PSW-S12/PSW-S13, the operator will configure only the real credentials
and any remaining safe-renewal setting required by the implemented path, then
run a single selected queued `IngestionRun` with:

```bash
# MANUAL SMOKE ONLY AFTER PSW-S12/PSW-S13 (placeholders only):
uv run python manage.py process_ingestion_runs_persistent_session \
    --real-handle --run-id <INGESTION_RUN_ID> --max-runs 1
```

> This remains a **manual smoke only** path, NOT production rollout. Credentials
> and passwords must never be logged. Bootstrap, navigation, and PDF-flow
> failures must be sanitized. The bridge/PDF flow still require live validation
> against the real legacy UI before any continuous worker rollout.

### 1.3 Real-handle CLI mode matrix (PSW-S24-PRE)

The `--real-handle` path now exposes a CLOSED CLI mode matrix, validated before
any adapter/browser creation or run mutation. None of the real modes is
rollout-ready; all stay disabled until authorized PSW-S24 live validation
succeeds.

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
# BOUNDED LIVE VALIDATION ONLY (placeholders; NOT rollout-ready):
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

> Bounded and continuous real modes are command surface only. They do NOT
declare production rollout readiness. Real IDs, patient identifiers, clinical
content, URLs, credentials, and cookies must never be logged.

---

## 2. Future production rollout plan

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

### 2.2 Side-by-side experiment (future, after prerequisites)

After the remaining prerequisites are met (live validation against the real
legacy UI and threshold tuning), deploy an initial controlled experiment:

```bash
cd /opt/sirhosp

# Current workers (6 replicas, already in production)
docker compose -f compose.yml -f compose.prod.yml up -d --scale worker=6

# Persistent workers (6 replicas) — EXAMPLE ONLY, not yet rollout-ready
# (blocked by live validation, PSW-S11, and threshold tuning).
# docker compose -f compose.yml -f compose.persistent-worker.yml up -d \
#   --scale persistent_worker=6
```

> A dedicated `compose.persistent-worker.yml` override is **not yet provided**
> because the worker is not rollout-ready. When the blockers are resolved
> (live validation, threshold tuning), create the override following
> the same tmpfs/isolation patterns as the current `worker` service in
> `compose.prod.yml`.

#### 2.2.1 Disabled example: `compose.persistent-worker.yml` (future reference)

When prerequisites are met, the override would look like:

```yaml
# compose.persistent-worker.yml — DISABLED EXAMPLE
# DO NOT DEPLOY until live validation and threshold tuning are done.
services:
  persistent_worker:
    build:
      context: .
      dockerfile: Dockerfile
      target: prod
    init: true
    environment:
      - DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY:?required}
      - DJANGO_DEBUG=false
      - DJANGO_ALLOWED_HOSTS=${DJANGO_ALLOWED_HOSTS:-localhost}
      - POSTGRES_DB=${POSTGRES_DB:-sirhosp}
      - POSTGRES_USER=${POSTGRES_USER:-sirhosp}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?required}
      - POSTGRES_HOST=db
      - POSTGRES_PORT=${POSTGRES_INTERNAL_PORT:-5432}
      - SOURCE_SYSTEM_URL=${SOURCE_SYSTEM_URL:-}
      - SOURCE_SYSTEM_USERNAME=${SOURCE_SYSTEM_USERNAME:-}
      - SOURCE_SYSTEM_PASSWORD=${SOURCE_SYSTEM_PASSWORD:-}
      - UV_PROJECT_ENVIRONMENT=/opt/venv
      - UV_CACHE_DIR=/opt/.uv_cache
      - UV_NO_CACHE=1
      - PLAYWRIGHT_PROXY_SERVER=${PLAYWRIGHT_PROXY_SERVER:-socks5://sirhosp-tailscale-proxy:1055}
      - TMPDIR=/tmp
      - TEMP=/tmp
      - TMP=/tmp
      - XDG_CACHE_HOME=/tmp/xdg-cache
      - XDG_CONFIG_HOME=/tmp/xdg-config
      - SIRHOSP_WORKER_LABEL=persistent-worker
    depends_on:
      db:
        condition: service_healthy
    networks:
      default:
      hospital_edge:
    command:
      - uv
      - run
      - --no-sync
      - python
      - manage.py
      - process_ingestion_runs_persistent_session
      - --real-handle
      - --loop
      - --sleep-seconds
      - "5"
    restart: unless-stopped
    shm_size: "${PERSISTENT_WORKER_SHM_SIZE:-512m}"
    tmpfs:
      - "/tmp:size=${PERSISTENT_WORKER_TMPFS_TMP_SIZE:-1g},mode=1777"
      - "/var/tmp:size=${PERSISTENT_WORKER_TMPFS_VAR_TMP_SIZE:-128m},mode=1777"
      - "/home/10001/.cache:size=${PERSISTENT_WORKER_TMPFS_CACHE_SIZE:-256m},uid=10001,gid=10001,mode=700"
      - "/home/10001/.config:size=${PERSISTENT_WORKER_TMPFS_CONFIG_SIZE:-64m},uid=10001,gid=10001,mode=700"
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

> This example uses **distinct** `PERSISTENT_WORKER_*` sizing variables to
> avoid collisions with the existing `WORKER_*` variables used by the legacy
> worker. All tmpfs mounts are exclusive per container replica.

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

# Persistent worker logs (when deployed)
# docker compose -f compose.yml \
#   -f compose.persistent-worker.yml \
#   logs --tail 100 persistent_worker

# Follow logs in real time
docker compose -f compose.yml -f compose.prod.yml logs -f worker
```

### 4.4 Log growth monitoring

```bash
# Check log sizes on disk
docker compose -f compose.yml -f compose.prod.yml exec worker \
  du -sh /proc/1/fd/1 2>/dev/null || true

# Docker log driver rotation (configured in Compose)
# max-size: 10m, max-file: 3 per container
```

---

## 5. Rollback

### 5.1 Stop persistent workers

If persistent workers were deployed under a dedicated Compose override:

```bash
cd /opt/sirhosp

# Stop and remove persistent worker containers
docker compose -f compose.yml -f compose.persistent-worker.yml down

# Verify only legacy workers remain
docker compose -f compose.yml -f compose.prod.yml ps
```

If integrated into `compose.prod.yml` as a disabled service, simply ensure
`--scale persistent_worker=0`.

### 5.2 Scale legacy workers back

```bash
# Restore legacy worker count to pre-experiment level
docker compose -f compose.yml -f compose.prod.yml up -d --scale worker=6
```

### 5.3 Verify rollback

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
    created_at__gte=cutoff,
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
