# Slice RPSA-S8 — Effective-exit aggregates and separate summary indicators

## Mission

Implement only operational indicators: rebuild the daily hospital-exit
aggregate from canonical effective exits (`saida_em`-derived
`discharge_date`) in `America/Bahia`, keep medical summaries by `alta_em`
as a separate indicator, and expose both as two dashboard cards and two
chart series. Death exits are not hospital discharges. No production
rebuild is executed by this slice.

## Mandatory context-zero reading order

1. `AGENTS.md`, `PROJECT_CONTEXT.md`
2. Change proposal, design, tasks and ADR-0009
3. Delta spec `specs/daily-discharge-tracking/spec.md` — every modified,
   added and renamed requirement ("dedicated tracking table", "triggers
   count refresh automatically", "Dashboard shows discharges today",
   "card navigates", "daily bars with moving averages",
   "America/Bahia timezone", ADDED "rebuild reports aggregate
   provenance")
4. RPSA-S2, S7 and S7A reports (HEAD `607ef97`; the automatic
   post-reconciliation refresh invoked without args at
   `apps/discharges/extraction_service.py` must keep working unchanged)
5. `apps/discharges/models.py` (`DailyDischargeCount.raw_data`,
   `DischargeRecord.saida_em/alta_em`) and
   `apps/patients/models.py` (`Admission.discharge_date`,
   `Admission.merged_into`, `ReconciliationEvent` append-only audit with
   `exit_type`, `EXIT_HOSPITAL_DISCHARGE`/death taxonomy,
   `RECONCILIATION_STATUS_RECONCILED`)
6. `apps/discharges/management/commands/refresh_daily_discharge_counts.py`
   (current implementation: distinct-patient count over
   `discharge_date`, default timezone, no preview, raw_data untouched)
7. `apps/services_portal/views.py` — `dashboard` (lines ~110-160:
   `altas_hoje` currently reads the aggregate; `altas`/`altas_date` are
   the retro-latest stats) and `discharge_chart` (lines ~459-595:
   single exit series, `_moving_average`/`_exponential_moving_average`,
   weekend flags, 90-day default through yesterday, hourly
   specialty table) plus `_weekday_average`
8. `dashboard.html` and `discharge_chart.html` templates
9. `tests/unit/test_daily_discharge_count.py` (including the RPSA-S7
   guard: source-scan pinning the single automatic `call_command` in
   `extraction_service.py` — this slice must not weaken it),
   `tests/unit/test_services_portal_dashboard.py` (77 tests; card
   fixtures live here)

## Ground truth (established; do not reinvent)

- **Apply is the command default; `--dry-run` is opt-in** (controller
  decision documented here). Rationale: the spec's automatic
  post-extraction refresh calls `refresh_daily_discharge_counts` with
  no arguments and must keep applying; `extraction_service.py` is out
  of scope; the ADDED "operator previews" scenario is satisfied by the
  explicit flag. Both modes emit aggregate before/after output (dates,
  per-date counts as totals only — never patient identity, name or
  prontuário). `--dry-run` mutates nothing.
- **Canonical hospital-exit classification**: group canonical episodes
  only — `Admission.merged_into IS NULL`, `discharge_date` set — whose
  latest `ReconciliationEvent` with status `reconciled` has
  `exit_type = EXIT_HOSPITAL_DISCHARGE`. Death exits (exit_type death
  from RPSA-S3) are excluded from hospital counts. Materialize as one
  efficient query path (e.g. Subquery latest-event exit_type); no new
  field, no migration. Counting distinct patients instead of canonical
  episodes is a prohibited workaround.
- **Timezone is literal, not inherited**: `ZoneInfo("America/Bahia")`
  named explicitly in the command and in the dashboard/chart views
  (e.g. `localdate(value, tz=BAHIA)` / `astimezone(BAHIA)` /
  `TruncDate(..., tzinfo=ZoneInfo("America/Bahia"))`), even though
  `TIME_ZONE` is currently `America/Bahia`. `timezone.get_default_timezone()`
  must not remain in the touched paths.
- **Dashboard cards (primary behavior change)**: the primary card
  `Saídas hospitalares no dia` counts canonical hospital exits with
  `discharge_date` on the current `America/Bahia` local date via a
  direct Admission query with the classification above — not the
  aggregate table (which may be stale and excludes today in the chart).
  The second card `Sumários de alta registrados` counts
  `DischargeRecord` rows with `alta_em` on the current local date.
  Zero is a valid, independent value for each card. Both cards link to
  `/painel/altas/` (`services_portal:discharge_chart`). The existing
  retro-latest `altas`/`altas_date` stats and the death card are not
  removed and not relabeled as exits.
- **Chart**: keep the exit series as the primary series sourced from
  `DailyDischargeCount` (default 90 days through yesterday, SMA-7,
  EMA-7, SMA-30 overlays, weekend tones/legend unchanged) and add a
  second daily series of medical summaries derived on request from
  `DischargeRecord.alta_em` over the same window, same `America/Bahia`
  grouping and same today-excluded boundary. Series are labeled
  distinctly (hospital exits by `saida_em` vs medical summaries by
  `alta_em`); neither relabels the other; moving averages stay on the
  exit series only. The hourly specialty table and `?dias`/`h_start`/
  `h_end` parameters are unchanged.
- **Sole-writer invariant**: `refresh_daily_discharge_counts` remains
  the only writer of `DailyDischargeCount`; views, ingestion and census
  only read. Extraction evidence persistence never writes the aggregate
  (already guarded by the S7 source-scan test).
- **Legacy `raw_data` cleanup**: on apply, affected dates are upserted
  with `raw_data=[]` (the JSONField default) so patient-bearing rows
  disappear from aggregate storage; dry-run leaves rows untouched. No
  schema change, no migration, no new persisted audit model.
- Synthetic fixtures only: timestamps like 23:55/00:05 around midnight
  in `America/Bahia`, cross-midnight `alta_em`/`saida_em` pairs, a
  death-closed episode, and a merged duplicate. No real patient data.

## Scope and file limit

Maximum **9 repository files changed** — 8 core plus 1 authorized
exception:

- `apps/discharges/management/commands/refresh_daily_discharge_counts.py`
- `apps/services_portal/views.py`
- `apps/services_portal/templates/services_portal/dashboard.html`
- `apps/services_portal/templates/services_portal/discharge_chart.html`
- `tests/unit/test_daily_discharge_count.py` (existing fixtures may be
  adapted to the new classification; S7 guard untouched)
- `tests/unit/test_services_portal_dashboard.py` (card fixtures updated
  to the new sources; unrelated tests preserved)
- `tests/integration/test_discharge_indicators.py` (**new** — chart
  series, navigation, dashboard integration)
- this change's `tasks.md`

Authorized exception (controller amendment, 2026-09-05, runtime):

- `tests/unit/test_discharge_persistence_hardening.py` — ONLY the two
  `TestServiceDischargeExtractionIdempotency` empty-output/empty-xls
  tests, adapted assertively to full-rebuild semantics: the seeded
  orphan aggregate row is rebuilt to canonical truth (count 0,
  `raw_data=[]`) by the authorized automatic refresh, while the S2
  intent (evidence persistence never writes the aggregate) and the S7
  source-scan guard remain intact. No other test in that file changes.

Full-rebuild semantics (decided by controller, documented here): the
affected set on apply is canonical-result dates ∪ all existing
`DailyDischargeCount` rows; rows without canonical backing are zeroed
(`count=0`, `raw_data=[]`), never deleted — the aggregate must reflect
canonical exits, so phantom counts from the pre-S8 semantics cannot
persist and reconciliation corrections moving exits across dates
self-heal.

No schema change is authorized. Any other file (including
`extraction_service.py`, `models.py`, `settings`, chart JS asset files
or new templates) means stop and escalate. Template-only additions stay
inside the two listed templates (inline scripts allowed, matching
existing patterns).

## Contract matrix

| Contract | Required assertion |
| --- | --- |
| dry-run (`--dry-run`) | reports before/after aggregates, zero mutation |
| apply default | upserts canonical counts; automatic S7 refresh keeps working |
| grouping by Bahia local date | 23:55 on D stays D; 00:05 moves to E |
| death exit excluded | death-closed episode absent from hospital counts |
| merged duplicate excluded | only canonical episode counted |
| `alta_em` does not alter exit aggregate | cross-midnight pair counted on `saida_em` date only |
| apply reports aggregate provenance | before/after range/counts in output, no identity |
| apply clears legacy `raw_data` | affected dates end with `raw_data == []` |
| sole-writer invariant | inspection finds no writer outside refresh command |
| primary card = today's effective exits | direct canonical query, local today, not latest/24h |
| second card = today's medical summaries | `DischargeRecord.alta_em` count, independent zero |
| both cards navigate to `/painel/altas/` | template links to discharge chart |
| chart has two labeled series | exit vs summary labels/data distinct |
| moving averages remain on exit series | SMA-7, EMA-7, SMA-30 regression |
| weekend differentiation and empty state | tones/legend kept; empty period renders |

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) | Teste/check |
| --- | --- | --- |
| dry-run sem mutação + output | comando | unit `test_daily_discharge_count.py` |
| apply canônico (death/merged/alta_em excluídos) | comando | unit (3 classes de fixture) |
| Bahia literal | comando + views | inspeção rg nº1 (não testável quando default==Bahia) |
| before/after sem identidade | comando | unit (assert stdout, sem nome/prontuário) |
| raw_data limpo no apply | comando | unit + integração |
| sole writer | comando | inspeção rg nº4 + guarda S7 existente |
| card hoje via query canônica | `views.py` | unit dashboard (3 saidas hoje + 2 ontem-24h → 5) |
| card resumos independente | `views.py` | unit dashboard (4 `alta_em` hoje → 4; zero) |
| navegação dos cards | `dashboard.html` | integração (links `/painel/altas/`) |
| 2 séries + rótulos | `views.py` + `discharge_chart.html` | integração |
| médias na série exit | `views.py` | integração (regressão SMA/EMA) |
| janela 90d até ontem | `views.py` | integração |
| empty state | template | integração |

## Bootstrap and baseline

```bash
git status --short          # must be clean
git rev-parse HEAD          # record BASE_REF (expected 607ef97)
./scripts/test-in-container.sh check
```

Reference baseline at `607ef97`: 3403 unit / 595 integration (post-S7A).
Do not re-run full suites as a pre-baseline; report deltas against these
numbers instead. Escalate via contact_supervisor on any baseline
mismatch.

## TDD RED → GREEN → REFACTOR

RED first, focused (synthetic fixtures; timezone pinned with explicit
`ZoneInfo` datetimes):

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml up -d db
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/unit/test_daily_discharge_count.py \
  tests/unit/test_services_portal_dashboard.py"
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/integration/test_discharge_indicators.py"
```

Expected assertion-level failures: `--dry-run` flag absent
(`SystemExit`/usage error); death episode still counted
(`assert count == N` fails including death); merged duplicate double
count; 00:05 exit attributed to previous date; `alta_em` date shifting
the exit count; primary card returning the stale aggregate instead of
today's canonical count; summary card key absent; second series/labels
absent from chart context; `raw_data` untouched after apply.

GREEN: implement dry-run/apply flag, canonical classification query,
Bahia literals, card queries, second series, and raw_data clearing with
the smallest change. Refactor only shared date-window/serialization
helpers; keep views thin.

## Mandatory inspections

```bash
rg -n "get_default_timezone" apps/discharges/management/commands/refresh_daily_discharge_counts.py apps/services_portal/views.py
rg -n "America/Bahia" apps/discharges/management/commands/refresh_daily_discharge_counts.py apps/services_portal/views.py
rg -n "distinct=True|Count\(.*patient" apps/discharges/management/commands/refresh_daily_discharge_counts.py
rg -n "DailyDischargeCount" apps -g '*.py' | grep -v "management/commands/refresh_daily_discharge_counts" | grep -vE "test_|services_portal/views"
rg -n "raw_data" apps/discharges/management/commands/refresh_daily_discharge_counts.py tests/unit/test_daily_discharge_count.py
rg -n "last 24|24 hours|order_by\(\"-date\"\)\.first" apps/services_portal/views.py
```

Interpretation: the first returns nothing (no inherited timezone in
touched paths); the second shows the literal in command and views; the
third returns nothing (no distinct-patient workaround); the fourth
shows only readers outside the command; the fifth shows the clearing
plus its test; the sixth must not show the primary card falling back to
latest-row. Any default-timezone ambiguity, distinct-patient
workaround, death inclusion, stale-aggregate card or latest-row
fallback fails the slice.

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
uv run --no-sync python manage.py makemigrations --check
```

Inspect every diff against `BASE_REF`. Mark only RPSA-S8, create one
commit and stop. Do not run the rebuild against production data and do
not change scheduling.

## Automatic `INCOMPLETO`

Leave the task unchecked and make no commit if tree/baseline/dependency
fails, RED is not assertion-level, `--dry-run` mutates anything, apply
is not the default, aggregate before/after output is absent or carries
identity, a death exit or merged duplicate is counted, `alta_em` shifts
an exit date, patient-level `raw_data` remains after apply, another
aggregate writer appears, the primary card reads the stale aggregate or
falls back to latest/24h, a timezone boundary is untested,
`get_default_timezone` remains in a touched path, the S7 automatic
refresh guard is weakened, a migration appears, or any gate fails or
more than 8 files are needed.

## Required report

Write `/tmp/sirhosp-slice-RPSA-S8-report.md` with status, base/commit,
acceptance and requirement→file→test matrices, every changed file with
before/after snippets, RED/GREEN evidence (quoted failing assertions),
dry-run vs apply counts on synthetic data (before/after output pasted,
identity-free), Bahia midnight and death-exclusion proofs, card
evidence (today vs stale aggregate), chart two-series evidence,
inspections, all commands/gates, diff check, risks and next step. Valid
Markdown, synthetic data only.
