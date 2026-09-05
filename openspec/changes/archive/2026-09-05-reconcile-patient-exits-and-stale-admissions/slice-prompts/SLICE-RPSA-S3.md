# Slice RPSA-S3 — Death reconciliation and legacy PDF retirement

## Mission

Implement only death exit reconciliation and retire the legacy PDF flows. A
death closes an episode only with a genuine source datetime contained by
exactly one canonical admission period; date-only evidence requests
`admissions_only` and never synthesizes an hour. `process_discharge_pdf` and
the PDF-based aggregate backfill (`backfill_daily_discharges`) must fail
before opening a PDF or performing any side effect and become explicit
removal candidates.

## Mandatory context-zero reading order

1. `AGENTS.md`, `PROJECT_CONTEXT.md`
2. Change proposal, design (decisions 1-3), tasks, ADR-0009
3. `specs/admission-exit-reconciliation/spec.md` (death and legacy-PDF
   scenarios) and `specs/historical-extraction-services/spec.md` (persisted
   death evidence scenarios)
4. RPSA-S2 implementation: commits `455c37d`, `2c8a20f`, `f28f7de` and
   `/tmp/sirhosp-slice-RPSA-S2-report.md`
5. `apps/patients/reconciliation.py` — the single matcher/audit boundary this
   slice extends; `apps/discharges/services.py` (`reconcile_discharge_record`,
   `_enqueue_missing_mirror_sync`) as the adapter pattern to mirror
6. `apps/deaths/models.py`, `apps/deaths/services.py` and
   `automation/source_system/deaths/extract_deaths.py` (CSV column shape)
7. `apps/patients/models.py` (`EXIT_DEATH`, `RECONCILIATION_STATUS_*`) and
   `apps/discharges/models.py` (`DischargeRecord` linkage pattern)
8. `apps/ingestion/services.py` — `queue_admissions_only_run`,
   `queue_demographics_only_run`
9. `apps/discharges/management/commands/process_discharge_pdf.py`,
   `apps/discharges/management/commands/backfill_daily_discharges.py`,
   `automation/source_system/discharges/pdf_utils.py` and every caller found
   by `rg -n 'process_discharge_pdf|pdf_utils|backfill_daily_discharges' .`
10. Existing death/PDF tests (see the authorized-exception list) and
    `README.md`

Before RED, document in the report which death payload fields can contain a
true time and how date-only values are represented (current synthetic
fixtures show `OBITO`/`DATA OBITO` as `DD/MM/YYYY`). If this cannot be proven
from code/fixtures, stop `INCOMPLETO` rather than infer it.

## Ground truth (established; do not reinvent)

- `decide_discharge_match`/`apply_discharge_exit` in
  `apps/patients/reconciliation.py` are the only matcher/audit boundary;
  `apply_discharge_exit` already accepts `exit_type`, `EXIT_DEATH` already
  exists in `apps/patients/models.py`, and no `patients` migration is
  expected.
- Death evidence carries no admission key/start/local date, so the matcher
  gains one new layer (design decision 3): among the patient's canonical
  admissions (`Admission.objects` already excludes merged rows), the unique
  admission whose known period contains the death datetime —
  `admission_date <= D` and (`discharge_date IS NULL` or
  `D <= discharge_date`). Null start disqualifies the row; zero or multiple
  candidates fail closed (`admission_not_found`/`ambiguous`). Equality
  boundaries are inclusive, consistent with the RPSA-S2 tripwires.
- Extend `DischargeExitEvidence` with a minimal opt-in marker for that layer
  (for example `match_by_period: bool = False`); the default must keep every
  discharge call site unchanged, and the dataclass must not be renamed.
- `DeathRecord` linkage mirrors `DischargeRecord` (RPSA-S2 migration 0006):
  nullable `admission` FK (`on_delete=SET_NULL`, `related_name` like
  `death_evidence`), `reconciliation_status` with the same 8-value check
  constraint, `reconciled_at`, plus a parsed nullable `obito_em` datetime
  (`data_obito` keeps the raw string). Make `daily_count` nullable/`SET_NULL`
  while still populating it on upsert, so evidence survives aggregate-row
  deletion; `DailyDeathCount` semantics are otherwise out of scope.
- Enqueue policy mirrors the discharge boundary: `patient_not_found` enqueues
  deduplicated `admissions_only` + `demographics_only`; date-only
  (`pending`), `admission_not_found` and `ambiguous` enqueue only
  `admissions_only`; `conflict`/`invalid_exit_datetime` enqueue nothing
  (RPSA-S5 owns conflict routing and cooldowns). Dedup means no new run while
  an equivalent queued/running `IngestionRun` exists for the patient;
  cross-cycle cooldown is a recorded RPSA-S5 residual.
- Use a new `EVIDENCE_SOURCE_DEATH_RECORD` audit source constant beside
  `EVIDENCE_SOURCE_DISCHARGE_RECORD`. Audit and logs stay structural only.

## Scope and file limit

Maximum **15 repository files changed** — 9 core, 3 authorized test
exceptions, 3 documentation/orchestration:

Core:

- `apps/deaths/models.py`
- next `apps/deaths/migrations/0003_*.py`
- `apps/deaths/services.py`
- `apps/patients/reconciliation.py`
- `apps/discharges/management/commands/process_discharge_pdf.py`
- `apps/discharges/management/commands/backfill_daily_discharges.py`
- `tests/unit/test_death_exit_reconciliation.py` (new)
- `tests/integration/test_death_exit_reconciliation.py` (new)
- `tests/integration/test_legacy_pdf_commands.py` (new)

Authorized exceptions (spec-superseded tests; minimal edits pinning the new
invariants, preserving unrelated assertions, mapped in the report):

- `tests/unit/test_death_persistence_hardening.py` (delete/recreate and
  stale-clear expectations)
- `tests/unit/test_death_extraction_service.py` (persistence
  semantics and metrics)
- `tests/integration/test_admission_identity_schema.py` (one-line addition of
  the new `death_evidence` accessor to the pinned reverse-relation inventory,
  mirroring the RPSA-S2 pattern for `discharge_evidence`)

Documentation/orchestration:

- `README.md`
- `docs/plans/censo-duplo-objetivo.md`
- this change's `tasks.md`

Any additional required file means `INCOMPLETO`. Explicitly out of scope:
`automation/source_system/discharges/pdf_utils.py` (stays until removal),
`apps/services_portal` death views, `DailyDeathCount` redesign, and the
evolution-PDF tests (`test_persistent_evolution_pdf.py`,
`test_pymupdf_import.py` — a different flow).

## Contract matrix

| Contract | Required proof |
| --- | --- |
| complete death datetime + unique containing period | closes at the exact aware value; audit `exit_type=death`; evidence linked |
| zero or multiple containing periods | `admission_not_found`/`ambiguous`; no mutation; sync enqueued |
| date-only death | `pending`; one deduplicated `admissions_only`; no synthesized hour |
| missing patient | `patient_not_found`; `admissions_only` + `demographics_only` dedup; no synthetic rows |
| repeated death evidence | stable `DeathRecord` PK/link/status; no delete/recreate; no duplicate active enqueue |
| row absent from repeated snapshot | evidence retained; aggregate count reflects the new snapshot |
| corrected death datetime on re-extraction | `reconciled` correction with prior/new in the append-only audit |
| deaths never touch the discharge aggregate | inspection: no `DailyDischargeCount` reference in `apps/deaths` |
| `process_discharge_pdf` invoked | safe `CommandError` before any side effect |
| `backfill_daily_discharges` invoked | same fail-safe retirement |
| executable callers of command/helper | none outside docs and the compatibility tests |
| removal candidacy | README lists command, helper and backfill with the one-cycle gate |
| logs/output contain no name or record number | captured log/command assertions |

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| camada de período no matcher | `apps/patients/reconciliation.py` | unit: período único/zero/múltiplo; boundaries de igualdade |
| fechamento + auditoria de óbito | `apps/patients/reconciliation.py` | unit: `exit_type=death`, prior/new, idempotência |
| upsert estável + linkage | `apps/deaths/models.py`, migration `0003_*`, `apps/deaths/services.py` | unit/integration: PK estável, sem delete; `makemigrations --check` |
| parse de `data_obito` sem síntese | `apps/deaths/services.py` | unit: date-only → `pending`; datetime → aware `America/Bahia` |
| enqueue limitado e deduplicado | `apps/deaths/services.py` | unit/integration: política por status; sem run ativo duplicado |
| aposentadoria dos comandos PDF | os dois commands | `tests/integration/test_legacy_pdf_commands.py` |
| óbito fora do agregado de altas | `apps/deaths/**` | `rg -n "DailyDischargeCount" apps/deaths` sem hits |

## RED

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml up -d db
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/unit/test_death_exit_reconciliation.py"
POSTGRES_PORT=55433 docker compose -p sirhosp-test -f compose.yml \
  -f compose.test.yml run --rm test-runner bash -lc \
  "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q \
  tests/integration/test_death_exit_reconciliation.py \
  tests/integration/test_legacy_pdf_commands.py"
```

- Falha esperada (unit): asserções de fechamento/estados de óbito falham
  porque a camada de período não existe; atributos de linkage ausentes em
  `DeathRecord` demonstram a migração pendente.
- Falha esperada (integração): a `CommandError` de depreciação não é
  levantada (os comandos ainda executam) e o upsert estável não preserva a
  PK.
- Falhas devem demonstrar comportamento ausente (asserção ou atributo),
  nunca erro de sintaxe/import nos arquivos de teste.
- Baseline de referência no HEAD: 3251 unit / 525 integration. Qualquer
  falha não relacionada aos novos testes deve ser escalada via
  `contact_supervisor`, não corrigida silenciosamente.

## GREEN / verificação local

- Os mesmos comandos focados do RED passam (exit 0).
- `./scripts/test-in-container.sh unit` e `./scripts/test-in-container.sh
  integration` verdes; desvios de contagem além dos novos testes e das duas
  exceções autorizadas devem ser explicados no relatório.
- `./scripts/test-in-container.sh lint` e `typecheck` sem erro.
- No container:
  `uv run --no-sync python manage.py makemigrations --check` — nenhuma
  migração pendente.

## Mandatory inspections

```bash
rg -n "midnight|noon|23:59|time\.min|time\.max|combine\(" apps/deaths \
  apps/discharges/management/commands
rg -n "discharge_date" apps/deaths
rg -n "DailyDischargeCount" apps/deaths
rg -n "admissions_only|exit_type|select_for_update|EVIDENCE_SOURCE_DEATH" \
  apps/deaths apps/patients/reconciliation.py tests
rg -n "process_discharge_pdf|pdf_utils|backfill_daily_discharges" . \
  -g '!openspec/changes/archive/**'
rg -n "\.delete\(\)|records\.all\(\)\.delete" apps/deaths/services.py
rg -n "open\(|read_text|extract_patients|process_discharges|\.create\(|\
\.update\(" apps/discharges/management/commands/process_discharge_pdf.py \
  apps/discharges/management/commands/backfill_daily_discharges.py
```

Interpretation: `discharge_date` and `DailyDischargeCount` must have zero
hits under `apps/deaths` (closure happens only through the reconciliation
boundary). Field names like `nome`/`prontuario` may exist in persistence
code, but no logger/print argument and no audit `details_json` value may
carry identity. Any synthesized death hour, direct discharge write, file
read or persistence inside a retired PDF command fails the slice.

## Gates and completion

Run:

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

Inspect all diffs against `BASE_REF`. Mark only RPSA-S3 and create one commit
only after every gate passes, then stop. Production and backfill are
forbidden.

## Required report

Write `/tmp/sirhosp-slice-RPSA-S3-report.md` even if incomplete. Include
status, base/commit, characterized death payload shape, checklist and
requirement→file→test matrix, changed files with before/after snippets,
RED/GREEN with quoted failing assertions, commands and exact results,
period-layer decision snippet with equality boundaries, enqueue policy
evidence, baseline count deltas, inspections/gates, residual risks and next
step. Valid Markdown and synthetic values only.

## Automatic `INCOMPLETO`

No task mark/commit when the tree or baseline is invalid, source time
semantics are unproven, RED is not behavior-demonstrating, any hour is
synthesized, the period layer can pick a non-unique or blind candidate
(latest/open fallback), death persistence deletes/recreates linked evidence,
either PDF command performs any side effect before its deprecation error, an
executable caller or active documentation remains, deaths write
`DailyDischargeCount`, identity leaks into logs/audit, the migration is
destructive, an unrelated baseline test breaks without a controller-approved
exception, a gate fails or scope exceeds 15 files.
