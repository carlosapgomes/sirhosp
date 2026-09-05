# Slice RPSA-S5 — Two-census absence detection and bounded confirmation

## Mission

Implement conservative stale-admission cases from accepted complete census
runs, post-census observation and an hourly safety command. Absence only
schedules bounded source confirmation; it never writes
`Admission.discharge_date`. Exit-reconciliation `conflict` evidence joins
the same bounded sync queue.

## Mandatory context-zero reading order

1. `AGENTS.md`, `PROJECT_CONTEXT.md`
2. Change proposal, design, tasks and ADR-0009
3. `specs/stale-admission-detection/spec.md`,
   `specs/census-snapshot-processing/spec.md` and
   `specs/adaptive-census-orchestration/spec.md`
4. RPSA-S2/S3 reports (reconciliation statuses, enqueue patterns) and the
   RPSA-S4 report (manager policy; commits up to `faaadbe`)
5. `apps/census/models.py`, `apps/census/services.py`
   (`validate_snapshot_completeness`, `process_census_snapshot`) and
   `apps/census/orchestration.py` (`run_single_cycle`, advisory-lock
   helpers, `ADVISORY_LOCK_KEY`)
6. Existing stale-report commands (`refresh_suspected_admissions`,
   `report_suspected_stale_inpatients`, `sync_missing_discharges`) —
   read-only reference; they are NOT superseded or edited in this slice
7. `apps/ingestion/services.py` (`queue_admissions_only_run`) and the
   caller-side dedup pattern in `apps/discharges/services.py`
   (`_enqueue_missing_mirror_sync`) / `apps/deaths/services.py`
8. `apps/patients/models.py` (managers, `RECONCILIATION_STATUS_CONFLICT`,
   `DischargeRecord`/`DeathRecord` linkage fields)
9. `tests/integration/test_admission_identity_schema.py` (pinned reverse
   accessor inventory) and census orchestration tests

## Ground truth (established; do not reinvent)

- Acceptance provenance: an "accepted complete census run" is one whose
  snapshots pass `validate_snapshot_completeness` inside
  `process_census_snapshot`; reuse that function and the processed run id
  exactly as `process_census_snapshot` does. Do not reimplement a weaker
  completeness predicate; rejected/incomplete runs neither advance nor
  reset an absence sequence.
- Observation hook: in `apps/census/orchestration.py::run_single_cycle`,
  immediately after the successful `process_census_snapshot` call (step 7);
  observation is best-effort — its failure logs structurally and never
  fails the census cycle or leaks the orchestrator lock.
- Case model lives in `apps/patients/models.py` (next migration
  `0005_*.py`): PostgreSQL-backed, one case per open canonical admission
  (default manager), fields including first/last absence run ids, run
  timestamps, reappearance resolution, last enqueue attempt/outcome. The
  dedicated review permission is created in the same migration via model
  `Meta.permissions` — pin the codename
  `review_reconciliation_cases` ("Can review reconciliation cases") so
  RPSA-S6 consumes exactly it.
- Cooldowns are case-level and evaluated at enqueue time:
  `>= 6h` since the last INCONCLUSIVE attempt (run failed/timed out, or
  admission still open with no exit evidence), `>= 24h` since the last
  CONCLUSIVE no-exit response (sync succeeded, admission still open,
  still absent, no matching exit evidence). Boundary equality is eligible;
  pin both boundaries with tests. Outcome classification derives from the
  `admissions_only` run status plus admission/evidence state at the next
  evaluation.
- Enqueue reuses `queue_admissions_only_run(*, patient_record=...)` with
  caller-side active dedup mirroring `_enqueue_missing_mirror_sync`
  (skip when an equivalent queued/running `IngestionRun` exists for the
  patient). At most 100 enqueues per cycle, deterministic oldest-first;
  the remainder stay eligible. Do not create a second queue abstraction.
- Conflict-evidence sync route: patients whose `DischargeRecord` or
  `DeathRecord` rows carry `reconciliation_status` equal to
  `RECONCILIATION_STATUS_CONFLICT` are enqueued through the same bounded,
  deduplicated, cooldown-governed path (re-syncing the admissions catalog
  can populate a missing start or resolve contradictory identifiers).
  `pending`, `ambiguous`, `patient_not_found` and `admission_not_found`
  rows are NOT re-enqueued here — S2/S3 already enqueue them at
  extraction time with active dedup.
- Safety command `reconcile_stale_admissions` (management command,
  orchestration-only): runs the same evaluation/enqueue pass bounded and
  aggregate-safe, guarded by a DISTINCT PostgreSQL advisory lock constant
  (mirror `acquire_orchestrator_lock`'s `pg_try_advisory_lock` pattern;
  never reuse `ADVISORY_LOCK_KEY`), releasing the lock on every exit path.
- Command/log output is structural only: counts, statuses, run ids and
  ages — never patient name, prontuário or `patient_source_key` values.
- Absence never writes `discharge_date`; explicit exit evidence remains
  independent of census waiting (no imposed ordering between the
  discharge/death reconciliation boundaries and this slice).

## Scope and file limit

Maximum **14 repository files changed** — 9 core, 3 authorized exceptions,
2 conditional exceptions:

Core:

- `apps/patients/models.py`
- next `apps/patients/migrations/0005_*.py`
- `apps/census/stale_admissions.py` (new)
- `apps/census/services.py`
- `apps/census/orchestration.py`
- `apps/census/management/commands/reconcile_stale_admissions.py` (new)
- `tests/unit/test_stale_admission_detection.py` (new)
- `tests/integration/test_stale_admission_detection.py` (new)
- this change's `tasks.md`

Authorized exceptions (same conscious-update pattern as RPSA-S2/S3):

- `tests/integration/test_admission_identity_schema.py` — add the case
  model's new reverse accessor to the pinned inventory (one line, plus
  its comment), preserving every unrelated assertion.
- `apps/patients/admission_merge.py` — add ONE registry entry for the new
  `stale_cases` accessor with disposition KEEP (cases are operational
  history, like `merged_from`/`reconciliation_events`; the canonical
  episode raises its own cases on later observations — no suspicion is
  lost; REPOINT would need new conflict-safe transfer logic under the
  partial unique constraint and is out of scope).
- `tests/unit/test_admission_merge.py` — extend the pinned accessor set
  and the kept-disposition assertion with `stale_cases`.

Conditional exceptions (edit only with evidence and prior escalation via
`contact_supervisor`):

- `tests/unit/test_adaptive_census_orchestrator.py` — only if the new
  post-census observation hook breaks an existing assertion; minimal
  edits pinning the hook, preserving unrelated assertions.
- `apps/ingestion/services.py` — only if the existing queue API genuinely
  cannot express the dedup; prefer caller-side logic in
  `apps/census/stale_admissions.py`.

Do not modify `deploy/systemd` or the legacy stale-report commands in
this slice. Any other file means `INCOMPLETO`.

## Contract matrix

| Contract | Required test |
| --- | --- |
| first accepted absence starts one case only | no enqueue, no discharge write |
| second consecutive accepted absence + >=30 min | case eligible and one queue request |
| second run before 30 min | not eligible (boundary equality pinned) |
| incomplete/rejected/ambiguous run | case neither advances nor resets |
| non-consecutive accepted runs (gap) | sequence does not advance falsely |
| reappearance resolves census-only suspicion | case closed; admission and prior exit evidence untouched |
| repeated same run is idempotent | observation and queue not duplicated |
| explicit exit evidence is independent | no imposed census wait |
| conflict evidence enqueues bounded sync | one deduplicated `admissions_only` for conflict rows |
| pending/ambiguous/not-found rows not re-enqueued | zero new runs for them |
| active equivalent run deduplicates | no new `admissions_only` row |
| 6-hour inconclusive and 24-hour conclusive cooldowns | boundary tests at exact thresholds |
| over 100 eligible cases | deterministic oldest 100 only; remainder stay eligible |
| orchestrator failure path | no false confirmation; cycle survives; lock released |
| dedicated review permission | migration creates exact codename; assignment grants it |
| safety command | bounded, aggregate-safe, distinct advisory lock, always released |
| absence never writes discharge_date | zero discharge writes across all scenarios |
| output carries no identity | captured log/command assertions |

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| aceitação reutilizada | `apps/census/stale_admissions.py` | unit: cenários aceito/rejeitado/incompleto via `validate_snapshot_completeness` |
| caso + permissão | `apps/patients/models.py`, migration `0005_*` | integration: criação idempotente; permissão existe pós-migrate; `makemigrations --check` |
| sequência 2×aceitas + 30 min | `stale_admissions.py` | unit: boundaries 29/30 min; gap entre runs |
| reaparição | `stale_admissions.py` | unit: caso fechado, sem mutação clínica |
| cooldowns 6h/24h | `stale_admissions.py` | unit: boundaries exatos; outcomes inconclusivo/conclusivo |
| fila limitada + dedup | `stale_admissions.py` | unit/integration: <=100 oldest-first; run ativo deduplicado |
| rota conflict | `stale_admissions.py` | integration: `DischargeRecord`/`DeathRecord` conflict -> 1 run; demais statuses -> 0 |
| hook pós-censo | `apps/census/orchestration.py` | integration: hook chamado após snapshot; falha não derruba ciclo |
| comando de segurança | `management/commands/reconcile_stale_admissions.py` | integration: lock distinto, saída agregada, bounded |
| sem escrita de alta | `stale_admissions.py` | inspeção `rg` + testes |

## RED

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml up -d db
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/unit/test_stale_admission_detection.py"
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/integration/test_stale_admission_detection.py"
```

- Falha esperada (unit): `ModuleNotFoundError`/`AttributeError` em
  `apps.census.stale_admissions` demonstra a ausência do módulo; após
  criar o módulo vazio, as falhas devem ser de asserção (sequência,
  boundaries, cooldowns, dedup).
- Falha esperada (integração): a migration `0005` não existe (campos do
  caso ausentes), a permissão não é criada, o hook não é chamado após o
  snapshot, o comando de segurança não existe (`CommandError`).
- Falhas devem demonstrar comportamento ausente (asserção ou atributo),
  nunca erro de sintaxe/import nos arquivos de teste.
- Baseline de referência no HEAD (`faaadbe`): 3314 unit / 550
  integration. Qualquer falha não relacionada aos novos testes ou às
  exceções autorizadas deve ser escalada via `contact_supervisor`.

## GREEN / verificação local

- Os mesmos comandos focados do RED passam (exit 0).
- `./scripts/test-in-container.sh unit` e `integration` verdes; desvios
  de contagem além dos novos testes e das exceções autorizadas devem ser
  explicados no relatório.
- `./scripts/test-in-container.sh lint` e `typecheck` sem erro.
- No container: `uv run --no-sync python manage.py makemigrations --check`
  e, após migrar em teste, uma asserção de que a permissão
  `review_reconciliation_cases` existe no registry do Django.

## Mandatory inspections

```bash
rg -n "discharge_date\s*=|update\(.*discharge_date" apps/census
rg -n "validate_snapshot_completeness" apps/census/stale_admissions.py
rg -n "RECONCILIATION_STATUS_CONFLICT" apps/census/stale_admissions.py
rg -n "pg_try_advisory_lock|ADVISORY_LOCK_KEY" apps/census \
  apps/census/management/commands/reconcile_stale_admissions.py
rg -n "review_reconciliation_cases" apps/patients tests
rg -n "queue_admissions_only_run|status__in=.*queued.*running" \
  apps/census/stale_admissions.py
rg -n "nome|prontuario|patient_source_key" apps/census/stale_admissions.py \
  apps/census/management/commands/reconcile_stale_admissions.py
rg -n "100|timedelta\(hours=6\)|timedelta\(hours=24\)" \
  apps/census/stale_admissions.py tests
```

Interpretation: zero discharge writes under `apps/census`; completeness
and conflict constants reused (not reinvented); a distinct advisory-lock
constant (never `ADVISORY_LOCK_KEY`); enqueue only through
`queue_admissions_only_run` with active dedup; identity field names may
appear in queries but never in log/command output values. Any
census-origin discharge write, weaker completeness predicate, queue above
100, duplicate active work or identity leak fails the slice.

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

Inspect every diff against `BASE_REF`; then and only then mark RPSA-S5,
make one commit and stop. Do not access production or deploy timers.

## Required report

Write `/tmp/sirhosp-slice-RPSA-S5-report.md` even on failure, with
status, base/commit, acceptance and requirement→file→test matrices,
changed-file before/after snippets, RED/GREEN with quoted assertions,
time-boundary (30 min, 6 h, 24 h) and cap evidence, conflict-route
evidence, permission-registry proof, inspections, all commands/gates,
diff check, risks and next step. Valid Markdown and synthetic data only.

## Automatic `INCOMPLETO`

No checkbox/commit if tree or baseline is invalid, RED is not
assertion-level (after module creation), accepted-run provenance is
unclear or reimplements a weaker completeness predicate, the dedicated
permission is absent after migration, absence changes clinical exit
state, the queue can exceed 100 or duplicate active work, cooldown or
30-minute boundaries lack tests, the hook can fail the census cycle or
leak the orchestrator lock, the safety command reuses the orchestrator
lock key, pending/ambiguous rows get re-enqueued, identity leaks, a
conditional exception is edited without evidence and escalation, a gate
fails or more than 14 files are needed.
