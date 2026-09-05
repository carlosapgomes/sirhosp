# Slice RPSA-S12 — Systemd schedules, release assets and runbook

## Mission

Package disabled-by-default systemd scheduling for D-1 recovery, hourly
current-day discharge and stale-case safety sweep against the RPSA-S11
hospital runner. Anchor time in `America/Bahia`, retry only temporary
contention, ship immutable same-tag assets and document
activation/rollback. Do not enable timers or access production. This
slice also lands the documentation-routed deferred notes from RPSA-S5,
S8, S9, S10 and S11.

## Mandatory context-zero reading order

1. `AGENTS.md`, `PROJECT_CONTEXT.md`
2. Change proposal, design, tasks and ADR-0009
3. `specs/production-exit-reconciliation-runtime/spec.md` (scheduler,
   catch-up-bound, coordination and operational-guidance requirements)
   and the modified `specs/adaptive-census-orchestration/spec.md`
4. RPSA-S5, S8, S9, S10 and S11 reports (deferred notes routed here)
5. Entire `deploy/README.md`; legacy `deploy/discharges-scheduler.sh`
   and `deploy/systemd/sirhosp-discharges.{service,timer}` (the
   `/opt/sirhosp` 3x/day host-time pair this slice replaces)
6. Entire `.github/workflows/publish-release-image.yml` (release
   `UPGRADE_ASSET` mechanics; `tests/unit/test_release_hospital_deploy.py`
   pins `NEXT_RELEASE = v0.1.0-rc.12`)
7. `compose.hospital.yml` (the RPSA-S11 `historical_recovery`
   profile-gated one-shot runner), `run_exit_reconciliation_runtime`
   modes and `apps/census/management/commands/reconcile_stale_admissions.py`
   (the RPSA-S5 hourly bounded sweep with its own advisory lock)
8. Existing deploy contract-test conventions (YAML/text parse; no
   Docker/systemd CLI required)

## Ground truth (established; do not reinvent)

- **Three schedules, fixed distinct offsets (no RandomizedDelay —
  deterministic coordination):**
  - D-1 recovery: `OnCalendar=*-*-* 05:00:00 America/Bahia`,
    `Persistent=true` — runs the four extractors in canonical order
    for the previous Bahia date (runtime `--mode d1`).
  - Hourly discharge: `OnCalendar=*-*-* *:13:00 America/Bahia`,
    `Persistent=true` — current-day discharges (runtime `--mode
    hourly`), staggered 13 minutes past the hour.
  - Stale safety sweep: `OnCalendar=*-*-* *:47:00 America/Bahia`,
    `Persistent=true` — `reconcile_stale_admissions` (RPSA-S5 bounded
    sweep, own lock, enqueues ≤100; no Playwright).
  Offsets 05:00 / :13 / :47 keep scheduled Playwright launches apart;
  queue/lock guards remain the second line (S11).
- **Scheduler script** `deploy/exit-reconciliation-scheduler.sh` with
  three bounded explicit modes (`d1-recovery`, `hourly-discharges`,
  `stale-sweep`). Every mode resolves Docker Compose against
  `/srv/apps/prisma` with `.env` and `compose.hospital.yml`, invokes
  the RPSA-S11 one-shot runner via
  `--profile recovery run --rm historical_recovery …` (never `web`,
  never `process_discharge_pdf`, never `/opt/sirhosp`). Exit-code
  handling: code 75 retries at most six times with a 600-second sleep
  between attempts; ANY other nonzero exit fails immediately — no
  unbounded loop, no systemd-layer restart policy for failures.
- **Units** (`deploy/systemd/`): rewrite the legacy
  `sirhosp-discharges.{service,timer}` to the hourly Bahia contract
  above (they own the discharge schedule), add
  `sirhosp-historical-recovery.{service,timer}` (05:00 D-1) and
  `sirhosp-stale-reconciliation.{service,timer}` (:47 sweep). All are
  `Type=oneshot`, journal output, `SyslogIdentifier` per unit, no
  `Restart=`. Installation never enables or starts anything (no
  preset files; `[Install]` sections only document intent).
- **Release assets**: `publish-release-image.yml` gains the scheduler
  script and all six unit files as same-tag immutable release assets
  (alongside the existing Compose + upgrade-runbook mechanics — the
  per-tag runbook file itself is created by the release process, not
  by this slice; `deploy/README.md` is the operational source).
- **`deploy/README.md`** (rewritten sections):
  - activation baseline: timers installed disabled-by-default, manual
    all-four-extractor D-1 smoke test, then enablement;
  - benchmark gates: hourly approval and seven-date catch-up approval
    are INDEPENDENT; catch-up automation only after catch-up
    benchmark approval; automatic planning stays D-1 until then;
    benchmark thresholds are documented safe defaults pending
    calibration (RPSA-S11 note), with a calibration section (including
    the residual-vs-peak queue-depth caveat);
  - contention: exit 75 semantics, the six-attempt/10-minute bound,
    queue/open-batch and advisory-lock guards, how to inspect;
  - monitoring: `check_ingestion_pipeline_health` with its FOUR new
    RPSA-S10 options and defaults and the daily
    `report_admission_reconciliation_integrity` command (RPSA-S10
    deferred doc gap);
  - authorized backfill runbook (RPSA-S9): backup reference, label,
    canary 50 then max 100, duplicate-cohort gating (prior
    admissions-only freshness sync and/or per-pair operator review —
    derived-confirmation limitation), rollback asymmetry note
    (evidence rows stay reconciled; a replay re-closes), batch
    post-rollback cap behavior, dry-run above-cap preview caveat;
  - disablement and rollback of timers; explicit statement that cron
    must not duplicate any schedule and the PDF command is never
    scheduled; legacy `discharges-scheduler.sh` and the old
    3x/day contract are marked deprecated;
  - sweep-vs-orchestrator window note (RPSA-S5): the :47 sweep and
    adaptive census orchestration coordinate through distinct locks;
    the summary-series axis note (RPSA-S8): the second chart series
    renders where aggregate rows exist (transitional).
- **Authorized exception (12th file)**:
  `apps/ingestion/pipeline_health.py` — exactly the threshold
  doc-comment at lines ~84-92 (RPSA-S10 deferred P2): stop claiming
  "documented in deploy/README.md" until the README section exists;
  after this slice it may reference the real section. Comment-only
  change; no behavior change.
- No application reconciliation logic, Compose file or release
  workflow logic beyond asset packaging changes here. No production
  access; no timer is installed, enabled or started.

## Scope and file limit

Maximum **12 repository files changed** — 11 core plus 1 authorized
exception:

- `deploy/exit-reconciliation-scheduler.sh` (new)
- `deploy/systemd/sirhosp-discharges.service` (rewrite)
- `deploy/systemd/sirhosp-discharges.timer` (rewrite)
- `deploy/systemd/sirhosp-historical-recovery.service` (new)
- `deploy/systemd/sirhosp-historical-recovery.timer` (new)
- `deploy/systemd/sirhosp-stale-reconciliation.service` (new)
- `deploy/systemd/sirhosp-stale-reconciliation.timer` (new)
- `deploy/README.md`
- `.github/workflows/publish-release-image.yml`
- `tests/unit/test_deploy_exit_reconciliation_runtime.py` (new)
- this change's `tasks.md`

Authorized exception:

- `apps/ingestion/pipeline_health.py` — comment-only fix at the
  threshold doc-comment (~lines 84-92).

Any other file means stop and escalate.

## Contract matrix

| Contract | Required proof |
| --- | --- |
| D-1 calendar | exact `05:00:00 America/Bahia`, host-tz independent, Persistent |
| D-1 command | runtime `--mode d1`, four extractors canonical order |
| discharge calendar | hourly `*:13:00 America/Bahia` staggered from D-1/sweep |
| stale calendar | hourly `*:47:00`, `reconcile_stale_admissions`, own lock |
| execution target | `/srv/apps/prisma`, `.env`, `compose.hospital.yml`, `--profile recovery run --rm` |
| code 75 handling | 6 attempts max, 600s apart, script-level |
| final extractor error | immediate failure; no retry escalation |
| activation defaults | no unit enables/starts on install |
| benchmark gates | hourly and catch-up approvals independent in docs |
| catch-up bound | automatic max seven only after catch-up approval |
| release assets | script + 6 units same-tag immutable; no-clone deployment |
| privacy | aggregate-only logs; no credentials or patient identity |
| deprecated legacy | old 3x/day contract marked deprecated, not deleted |
| RPSA-S10 doc fix | README documents 4 options + daily command; pipeline_health comment consistent |

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) | Teste/check |
| --- | --- | --- |
| calendários Bahia + offsets distintos | 3 timers | unit (parse OnCalendar literal) |
| D-1 4 extratores ordem canônica | scheduler script | unit (mode → comando literal) |
| runner one-shot, nunca web/PDF | scheduler script | unit (strings negativas) |
| 75: 6×600s no script; outra falha imediata | scheduler script | unit (stub sleep/docker; matriz de exits) |
| oneshot sem Restart; disabled default | 3 services | unit (parse) |
| assets same-tag no workflow | workflow | unit (asset list) |
| README: gates independentes/canário/rollback | `deploy/README.md` | unit (seções-chave por texto) |
| README: 4 options + comando diário S10 | `deploy/README.md` | unit (texto) |
| comentário pipeline_health consistente | exceção | inspeção rg |
| sweep/orquestrador + eixo série notas | `deploy/README.md` | unit (texto) |
| `systemd-analyze verify` + `bash -n` | units + script | comando best-effort documentado |

## Bootstrap and baseline

```bash
git status --short          # must be clean
git rev-parse HEAD          # record BASE_REF (expected 082839f)
./scripts/test-in-container.sh check
```

Reference baseline at `082839f`: 3498 unit / 656 integration
(post-S11). This slice touches no application code path (one
comment-only exception); unit suite plus lint/typecheck suffice — run
integration only if application files beyond the exception change
(escalate first). Escalate via contact_supervisor on any mismatch.

## TDD RED → GREEN → REFACTOR

RED first:

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml up -d db
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/unit/test_deploy_exit_reconciliation_runtime.py"
```

Expected assertion-level failures: scheduler script file absent
(`FileNotFoundError`/text assertions fail); three new unit pairs
absent; rewritten `sirhosp-discharges` still containing the legacy
`/opt/sirhosp`/3x/day/host-time strings (assert-not fails); workflow
lacking the new asset entries; README missing the activation/benchmark/
S10-options/backfill-runbook sections; pipeline_health comment still
claiming nonexistent documentation (text assertion).

GREEN: write the scheduler script, six units, workflow asset block,
README sections and the comment fix with the smallest change.
Refactor only shared shell/unit values; no package manager or
deployment framework.

## Mandatory inspections

```bash
rg -n "OnCalendar|America/Bahia|Persistent|RandomizedDelay" deploy/systemd
rg -n "05:00:00|\*:13:00|\*:47:00|75|600|historical_recovery|compose.hospital.yml|/srv/apps/prisma" deploy .github/workflows tests/unit/test_deploy_exit_reconciliation_runtime.py
rg -n "discharges, admissions, deaths, official_census" deploy
rg -n "process_discharge_pdf|/opt/sirhosp|compose.prod.yml|\bweb\b" deploy/exit-reconciliation-scheduler.sh deploy/systemd/sirhosp-historical-recovery.service deploy/systemd/sirhosp-stale-reconciliation.service
rg -n "documented in deploy/README" apps/ingestion/pipeline_health.py
rg -n "release|upload|deploy/systemd|exit-reconciliation-scheduler|compose.hospital" .github/workflows/publish-release-image.yml
```

Interpretation: calendars are Bahia-literal with the three distinct
offsets and no RandomizedDelay; the 75/600/6 constants live only in
the script; the canonical extractor order appears once; the fourth
returns nothing (no PDF, no `/opt/sirhosp`, no `web` in the new
runtime path — the deprecated legacy discharges pair may retain only
historical references in comments, not in `ExecStart`); the fifth
shows the pipeline_health comment now consistent with a README section
that exists; the sixth shows every runtime asset in the release.

Run `bash -n deploy/exit-reconciliation-scheduler.sh` and, IF available
in the environment, `systemd-analyze verify` on all six units
(document any container limitation; unit-text contract tests are the
authoritative proof). Inspect rendered release asset contents locally
without publishing.

## Gates and completion

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate reconcile-patient-exits-and-stale-admissions --strict
./scripts/markdown-lint.sh
git diff --check
```

Review all diffs against `BASE_REF`. Only then mark RPSA-S12 and create
one commit. Stop before final verification. Never install/enable
units, publish a release, call source systems or run production
backfill.

## Automatic `INCOMPLETO`

Leave the task unchecked and commit nothing if baseline/dependency/RED
fails, a calendar relies on host timezone or collides with another
offset, recovery omits/reorders an extractor, code 75 can retry more
than six times or any other failure is retried, timers could enable on
install, hourly and catch-up gates are coupled in the docs, units call
`web` or the PDF command, the release lacks any runtime asset, the
RPSA-S10 documentation gap remains, identity/credentials leak,
`systemd-analyze` shows an unexplained unit error, a gate fails or
more than 12 files are needed.

## Required report

Write `/tmp/sirhosp-slice-RPSA-S12-report.md` even if incomplete.
Include status, base/commit, contract and requirement→file→test
matrices, every changed file with before/after snippets, RED/GREEN,
calendar/timezone evidence, the exact retry matrix (75 vs other
exits), `bash -n`/`systemd-analyze` results, the rendered release
asset manifest, the landed deferred-notes checklist (S5/S8/S9/S10/S11)
with README section references, no-enable/no-caller inspections, all
commands/gates, diff check, risks and next step. Use valid Markdown
and synthetic values only.
