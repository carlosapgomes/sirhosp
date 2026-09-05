# Slice RPSA-S2 — Canonical hospital-discharge reconciliation

## Mission

Implement only evidence-linked hospital-discharge reconciliation after RPSA-S1:
status/linkage, pure ordered matching, transactional application and extraction
integration. `saida_em` is authoritative; `alta_em` never closes an admission.
Do not implement death handling, merge, census, UI, aggregates or backfill.

## Mandatory context-zero reading order

1. `AGENTS.md` and `PROJECT_CONTEXT.md`
2. This change's `proposal.md`, `design.md`, `tasks.md` and ADR-0009
3. `specs/admission-exit-reconciliation/spec.md`
4. `specs/historical-extraction-services/spec.md`
5. RPSA-S1 report and commit diff
6. `apps/patients/models.py`, `apps/ingestion/models.py`
7. `apps/discharges/models.py`, `services.py`, `extraction_service.py`
8. Existing discharge, patient and ingestion unit/integration tests

## Scope and file limit

Maximum **10 repository files changed**, including task checkbox:

- `apps/patients/models.py`
- `apps/patients/reconciliation.py` (new)
- next `apps/patients/migrations/0003_*.py`
- `apps/discharges/models.py`
- next `apps/discharges/migrations/0006_*.py`
- `apps/discharges/services.py`
- `apps/discharges/extraction_service.py`
- `tests/unit/test_admission_exit_reconciliation.py`
- `tests/integration/test_discharge_reconciliation.py`
- this change's `tasks.md`

Use actual next migration numbers. Stop `INCOMPLETO` if another file is required.

## Bootstrap and baseline

```bash
git status --short
git rev-parse HEAD
BASE_REF="$(git rev-parse HEAD)"
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
```

Tree must be clean and RPSA-S1 complete. Record exact outputs before edits.

## Contract matrix

| Contract | Target | Required assertion |
| --- | --- | --- |
| statuses are exactly the eight specified values | evidence model/API | invalid value rejected |
| source shape exposes only real key/time precision | adapter/decision value | unavailable levels skipped, not synthesized |
| discharge date string is local-date only | XLS adapter | no exact-start claim; invalid date does not choose latest |
| match precedence is key → alias → exact start → one Bahia local date | pure decision function | precedence and zero/multiple cases |
| null admission start or contradictory strong IDs | pure decision | `conflict`, distinct from `ambiguous` |
| valid `saida_em` closes as `hospital_discharge` | transaction service | exact aware timestamp stored |
| `alta_em` without `saida_em` leaves open | transaction service | no field mutation |
| exit before admission is invalid | pure decision | status plus unchanged Admission |
| repeated equal evidence is `already_reconciled` | transaction service | no duplicate mutation/audit semantics |
| unambiguous correction preserves prior value | append-only audit | before and after values asserted |
| missing patient/admission creates no synthetic row | service/extraction integration | status and bounded sync request |
| evidence persistence is decoupled from daily aggregate | schema/extraction | no `DailyDischargeCount` write or patient raw data |
| source logs contain no name/prontuário | all touched paths | `caplog`/output regression |

Audit must be append-only, indefinitely retained and contain source kind/ID,
reason code and structural before/after state, not copied patient identity or
clinical text. Use row locks and deterministic selection.

## TDD RED → GREEN → REFACTOR

1. Write synthetic unit and integration tests first.
2. Run official `unit` and `integration` commands and capture assertion-level
   failures; import/collection errors do not qualify as RED.
3. Implement the smallest pure matcher, additive migration and transactional
   application boundary. Make `DischargeRecord.daily_count` nullable or
   otherwise safely decouple evidence from aggregate storage within the
   authorized migration; do not rebuild historical counts in this slice.
4. Call that boundary after discharge persistence without duplicating matching
   logic or writing `DailyDischargeCount` in extraction.
5. Refactor duplicated branches into named decisions/statuses. Apply clean code,
   DRY and YAGNI; do not build a generic rules engine.

## Mandatory inspections

```bash
rg -n "alta_em.*discharge_date|discharge_date.*alta_em" apps tests
rg -n "saida_em|America/Bahia|select_for_update|already_reconciled" apps/patients apps/discharges tests
rg -n "DailyDischargeCount.*(create|update)|update_or_create\(" apps/discharges/extraction_service.py
rg -n "nome|prontuario|patient_source_key" apps/patients/reconciliation.py apps/discharges/services.py
rg -n "Admission\.objects.*first\(|\.order_by\(.*\)\.first\(\)" apps/patients/reconciliation.py
```

Any `alta_em`→`discharge_date` write, operational aggregate write from evidence
persistence or arbitrary `.first()` candidate selection is a hard failure.
Identity fields may be queried for matching but must not be logged or copied
into audit payloads.

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

Inspect the complete diff against `BASE_REF`. Only when every gate passes, mark
only RPSA-S2 complete and create one commit. Stop after the commit. Never access
production or run a backfill.

## Automatic `INCOMPLETO` conditions

Stop without checkbox or commit if baseline/tree is invalid, RED is not a real
assertion failure, matching is ambiguous, `alta_em` closes an admission,
evidence persistence still writes the operational aggregate, audit can be
edited/deleted through the service, migration is destructive, PHI enters
logs/audit duplication, any gate fails or the file limit is exceeded.

## Required report

Write `/tmp/sirhosp-slice-RPSA-S2-report.md` in valid Markdown with status,
`BASE_REF`/commit, acceptance and traceability matrices, all changed files,
before/after snippets per file, RED/GREEN proof, migration/constraint evidence,
inspection and gate outputs, `git diff --check`, risks and next step. Use only
synthetic patient data. The report must independently substantiate every claim.
