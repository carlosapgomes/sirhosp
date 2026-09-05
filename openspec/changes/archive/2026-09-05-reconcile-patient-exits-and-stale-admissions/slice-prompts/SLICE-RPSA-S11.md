# Slice RPSA-S11 — Hospital recovery runner, coordination and benchmarks

## Mission

Create the safe execution substrate used later by systemd: a profile-gated
Playwright-capable one-shot runner in `compose.hospital.yml`, runtime
eligibility and job locks, plus independent bounded benchmarks for hourly
discharge and the maximum historical catch-up. Do not create/enable timers
or access production.

## Mandatory context-zero reading order

1. `AGENTS.md`, `PROJECT_CONTEXT.md`
2. Change proposal, design, tasks and ADR-0009
3. `specs/production-exit-reconciliation-runtime/spec.md` (all ADDED
   requirements — the S11 scope covers the Compose runner, coordination
   locks/eligibility/code 75, the ≤7-date catch-up bound and the two
   benchmarks; systemd timers, release assets and runbook are RPSA-S12)
4. RPSA-S5, S7A and S10 reports/diffs
5. Entire `compose.hospital.yml` (release image line 59, `db` healthcheck,
   `x-playwright-service` anchor at line 75 with `shm_size`/`tmpfs`,
   internal networks, credential environment anchors) AND the existing
   `historical_recovery` service in `compose.prod.yml:296-299` (the
   reference pattern: `run --rm` one-shot)
6. `apps/ingestion/management/commands/recover_historical_data.py`
   (`--extractors` with `validate_extractors`, RecoveryPlan, canonical
   extractor order) and `apps/ingestion/historical_recovery.py`
7. `apps/census/orchestration.py` — advisory-lock pattern
   (`pg_try_advisory_lock`, `ADVISORY_LOCK_KEY`), queue-drained/open-batch
   eligibility helpers; the RPSA-S5 distinct lock key (31082025)
8. `apps/ingestion/pipeline_health.py` — the S10 durable coverage/gap
   evaluation (reusable read-only for missing-date detection)
9. `tests/unit/test_release_hospital_deploy.py` (7 existing tests) and
   existing Compose contract-test patterns

## Ground truth (established; do not reinvent)

- **Compose contract**: add to `compose.hospital.yml` a service named
  `historical_recovery` gated behind the `recovery` profile, extending
  `x-playwright-service` (inherits tmpfs, `/dev/shm`, init, credential
  environment anchors) and the exact release image; depends on the
  healthy `db`; internal networks only; `docker compose run --rm` one-shot
  semantics with no daemon/restart loop. Normal `up` (no profile) MUST
  NOT resolve the service. Invocation shape:
  `docker compose -f compose.hospital.yml --profile recovery run --rm
  historical_recovery <runtime command>`. The runner never routes
  source automation through `web`.
- **Runtime command** (`run_exit_reconciliation_runtime`, new): three
  mutually exclusive modes (controller amendment 2026-09-05 — the
  original "two modes" wording contradicted the contract matrix's
  catch-up proof).
  - `--mode hourly`: extract the CURRENT `America/Bahia` date's
    discharges by invoking the existing recovery pipeline for that
    single date and extractor (`discharges` only) — reuse, do not fork,
    the extraction/reconciliation/refresh path.
  - `--mode d1`: previous `America/Bahia` date with the four extractors
    in the canonical order `discharges, admissions, deaths,
    official_census`. `process_discharge_pdf` is never invoked in any
    mode.
  - `--mode catchup` (operator-explicit, never scheduled): plan
    missing/failed dates from the durable S10 discharge-extraction
    coverage semantics (reuse the read-only helper; do not duplicate
    logic), deterministically capped at seven dates, executing the four
    extractors per planned date through the existing recovery pipeline
    under the `recovery` advisory lock with the same ordering
    (lock → eligibility → 75). Known limitation to document in the
    report: dates where only a non-discharge extractor failed are not
    planned (covered by D-1 and the S10 health report).
- **Exit-code semantics (controller clarification 2026-09-05)**: code
  75 maps ONLY to temporary contention — active queued/running
  `IngestionRun` or open census batch. Cooldown/stale-only
  ineligibility is business state and never produces 75; the lock-conflict
  skip stays exit 0; extractor failures keep normal nonzero semantics.
- **Coordination locks**: two NEW named PostgreSQL advisory-lock keys,
  one per mode (hourly, recovery), distinct from each other and from
  every existing key (census orchestrator `ADVISORY_LOCK_KEY` and the
  RPSA-S5 key). Before launching, the runtime tries `pg_try_advisory_lock`
  on its mode key: on conflict it exits 0 with an aggregate "equivalent
  runtime active" skip message — before any subprocess/Playwright call.
  Session-scoped locks (no explicit unlock requirement) so process exit
  always releases.
- **Eligibility before Playwright** (source-running modes): reuse the
  read-only orchestration eligibility semantics without weakening them
  — if any `IngestionRun` is queued/running or a census batch is open,
  exit with FIXED code `75` (`EX_TEMPFAIL`) BEFORE any Playwright/
  subprocess launch, printing an aggregate-safe busy reason. Code 75 is
  reserved for this contention; extractor failures keep their normal
  nonzero semantics (never mapped to 75).
- **Catch-up bound**: any multi-date planning is capped at seven dates
  read from the RPSA-S7/S10 durable coverage metadata (missing or
  failed dates); more than seven stops BEFORE extraction and reports
  only aggregate gap count and bounds. Automatic/scheduled planning
  remains D-1 only — multi-date catch-up always requires explicit
  operator execution (`--mode catchup` style invocation is explicit;
  nothing here schedules it).
- **Benchmark command** (`benchmark_exit_reconciliation_runtime`, new):
  two SEPARATE bounded modes, never combined in one run:
  - `--mode hourly`: bounded repetitions (default 3, `--repetitions`
    override) of the hourly single-date discharge path with all source
    calls mocked; measures wall latency, error rate, database duration
    and queue impact; evaluates PASS/FAIL against named thresholds with
    safe defaults (e.g. `max_latency_seconds`, `max_error_rate`,
    `max_db_seconds`, `max_queue_depth` — exact defaults documented in
    the report).
  - `--mode catchup`: covers the four extractors across at most seven
    synthetic dates (mocked), evaluating the same threshold families
    for the catch-up shape.
  Benchmark results are aggregate-only (counts, durations, rates) and
  mock every source call; no benchmark enables anything automatically —
  approval is an operator decision recorded outside code (runbook, S12).
- **Output identity-safety**: aggregate counters, statuses, dates and
  safe failure reasons only; never patient identity, clinical text, CSV
  bodies or credential values (credentials arrive via the S7A scoped
  environment and are never echoed).
- Synthetic fixtures only; no production access; no timer creation.

## Scope and file limit

Maximum **6 repository files changed**:

- `compose.hospital.yml`
- `apps/ingestion/management/commands/run_exit_reconciliation_runtime.py`
  (new)
- `apps/ingestion/management/commands/benchmark_exit_reconciliation_runtime.py`
  (new)
- `tests/integration/test_exit_reconciliation_runtime_commands.py` (new)
- `tests/unit/test_release_hospital_deploy.py` (extend; existing 7
  tests preserved)
- this change's `tasks.md`

No systemd, cron, release workflow or deploy documentation change
belongs here (the RPSA-S10 deferred doc/comment fixes route to S12).
Any other file means stop and escalate.

## Contract matrix

| Contract | Required proof |
| --- | --- |
| `recovery` profile gating | normal `up` does not resolve the service; profile does |
| one-shot runner | release image, healthy DB dependency, internal networks, no restart loop |
| Playwright safety | inherits tmpfs, `/dev/shm`, init and credential env anchors via the anchor |
| hourly mode | current Bahia date, discharges only, via existing pipeline |
| D-1 mode | previous Bahia date, four extractors, canonical order |
| distinct advisory locks | hourly ≠ recovery ≠ orchestrator ≠ S5; busy ⇒ skip 0 before subprocess |
| queue/open-batch contention | fixed exit 75 before Playwright, aggregate reason |
| code 75 semantics | extractor failure NOT 75; contention NOT other codes |
| catch-up cap | ≤7 dates from durable coverage; >7 stops pre-extraction, count+bounds only |
| auto planning stays D-1 | no multi-date path without explicit invocation |
| hourly benchmark | bounded reps, named thresholds, PASS/FAIL, all source mocked |
| catch-up benchmark | 4 extractors × ≤7 synthetic dates, separate invocation |
| output | aggregate-safe; no identity or credentials |
| `process_discharge_pdf` | never invoked by any mode |

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) | Teste/check |
| --- | --- | --- |
| profile gating + never on `up` | `compose.hospital.yml` | unit (deploy contract, YAML/profile parse) |
| Playwright/db/network inheritance | `compose.hospital.yml` | unit (anchor merge assertions) + `compose config --quiet` run |
| hourly/D-1 modos + ordem canônica | comando runtime | integração (args do pipeline chamado, datas Bahia) |
| locks distintos + skip | comando runtime | integração (lock held ⇒ exit 0, zero subprocess) |
| eligibility ⇒ 75 pré-Playwright | comando runtime | integração (queued run / open batch ⇒ 75) |
| 75 ≠ falha de extrator | comando runtime | integração (falha ⇒ nonzero ≠ 75) |
| cap 7 datas + bounds agregados | comando runtime | integração (7 ok / 8 para antes de extrair) |
| planning D-1 only | comando runtime | integração (sem path multi-date automático) |
| benchmarks separados e limitados | comando benchmark | integração (2 modos, reps default, thresholds, mocks) |
| output identity-safe | ambos comandos | unit (sentinels ausentes de stdout) |
| regressão dos 7 testes deploy | teste existente | suíte existente verde |

## Bootstrap and baseline

```bash
git status --short          # must be clean
git rev-parse HEAD          # record BASE_REF (expected f637f09)
./scripts/test-in-container.sh check
```

Reference baseline at `f637f09`: 3495 unit / 620 integration
(post-S10). Do not re-run full suites as a pre-baseline; report deltas
against these numbers. Escalate via contact_supervisor on any baseline
mismatch.

## TDD RED → GREEN → REFACTOR

RED first, focused:

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml up -d db
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/unit/test_release_hospital_deploy.py"
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/integration/test_exit_reconciliation_runtime_commands.py"
```

Expected assertion-level failures: deploy-contract tests asserting the
`historical_recovery` service/profile/yaml shape fail (service absent);
`call_command` with both unknown runtime commands raising
`CommandError`; mode/date/order assertions failing (no such options);
lock-held test expecting exit-0 skip observing the command error out or
launch subprocess; contention test expecting code 75 getting normal
exit; catch-up cap test expecting a pre-extraction stop observing
attempts to run; benchmark mode/threshold assertions unfulfilled.

GREEN: add the profile-gated service extending `x-playwright-service`,
the thin runtime orchestrator (lock → eligibility → invoke existing
pipeline), the catch-up cap and the two benchmark modes with pure
threshold evaluation. Refactor only shared lock/result formatting; no
queue framework, daemon or dependency. Clean code, DRY, YAGNI.

## Mandatory inspections

```bash
rg -n "historical_recovery|profiles|x-playwright-service|shm_size|tmpfs" compose.hospital.yml tests/unit/test_release_hospital_deploy.py
rg -n "EX_TEMPFAIL|75|pg_try_advisory_lock|queued|running|open.*batch" apps/ingestion/management/commands/run_exit_reconciliation_runtime.py tests/integration/test_exit_reconciliation_runtime_commands.py
rg -n "discharges, admissions, deaths, official_census|America/Bahia|seven|<= ?7" apps/ingestion/management/commands/run_exit_reconciliation_runtime.py apps/ingestion/management/commands/benchmark_exit_reconciliation_runtime.py
rg -n "password|username|prontuario|nome|csv" apps/ingestion/management/commands/run_exit_reconciliation_runtime.py apps/ingestion/management/commands/benchmark_exit_reconciliation_runtime.py
rg -n "process_discharge_pdf" apps/ingestion/management/commands tests/integration/test_exit_reconciliation_runtime_commands.py
```

Interpretation: the first shows the gated service and its inherited
anchor keys; the second shows the advisory-lock/eligibility/code-75
wiring; the third pins the canonical order, Bahia literal and the
seven-date bound; the fourth returns no credential/identity output
fields; the fifth shows the PDF command appearing ONLY as a
never-invoked negative assertion (or not at all).

Compose validation (never print rendered config):

```bash
SIRHOSP_VERSION=test-tag docker compose -f compose.hospital.yml \
  --profile recovery config --quiet
```

Compose validation: the authoritative proof is the YAML contract
assertion in `tests/unit/test_release_hospital_deploy.py` (regex/text
parse, matching the existing conventions there — no Docker CLI
required). If a Docker daemon is available in the environment, the
quiet check above with synthetic required values is a welcome
additional check; never print rendered configuration. The
profile-absent case is proven by the unit test asserting normal
enumeration does not resolve `historical_recovery`.

## Gates and completion

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate reconcile-patient-exits-and-stale-admissions --strict
./scripts/markdown-lint.sh
git diff --check
```

Inspect every diff against `BASE_REF`. Mark only RPSA-S11, create one
commit and stop. No source call, production command or timer activation
is permitted.

## Automatic `INCOMPLETO`

Leave the task unchecked and make no commit if tree/baseline/dependency
fails, RED is not assertion-level, the one-shot runner starts under
normal `up`, lacks Playwright safeguards or the healthy-DB dependency,
routes automation through `web`, launches Playwright while queue/batch
is active or an equivalent lock is held, conflates code 75 with
extractor failure, shares a lock key with an existing runtime, exceeds
seven catch-up dates, combines or unbounds the benchmarks, lets any
benchmark enable scheduling automatically, invokes
`process_discharge_pdf`, leaks identity or credentials, a gate fails
or more than 6 files are needed.

## Required report

Write `/tmp/sirhosp-slice-RPSA-S11-report.md` with status, base/commit,
acceptance and requirement→file→test matrices, changed-file before/
after snippets, RED/GREEN (quoted assertions), profile enumeration and
Compose validation output (quiet checks only), lock/eligibility proof
matrix, both benchmark threshold tables with defaults and mocked
results, output-safety inspections, all commands/gates, diff check,
risks and next step. Valid Markdown and synthetic data only.
