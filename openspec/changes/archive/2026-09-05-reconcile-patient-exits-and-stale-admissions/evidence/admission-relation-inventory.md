# Admission Relation Inventory (RPSA-S1, re-derived in RPSA-S2)

Baseline inventory of every reverse relation targeting `patients.Admission`
and the query paths that resolve or list admissions. Recorded before any
future merge/transfer logic (RPSA-S4). Re-derive this inventory after each
schema slice that adds relations; RPSA-S4 requires a superset of this list
that explicitly includes the discharge and death evidence links.

Generated against the model state introduced by
`apps/patients/migrations/0002_admission_identity.py` and re-derived after
`apps/discharges/migrations/0006_discharge_reconciliation_linkage.py` plus
`apps/patients/migrations/0003_reconciliation_event.py` (RPSA-S2 evidence
and audit FKs). Clinical-vs-maintenance classification of every
`Admission.objects`/reverse-accessor call site remains the RPSA-S4 hard
gate before any merge writer ships.

## Reverse relations

| Accessor | Model (app) | Field kind | on_delete | Nullable |
| --- | --- | --- | --- | --- |
| `events` | `ClinicalEvent` (clinical_docs) | ForeignKey | CASCADE | no |
| `summary_state` | `AdmissionSummaryState` (summaries) | OneToOneField | CASCADE | no |
| `summary_versions` | `AdmissionSummaryVersion` (summaries) | ForeignKey | CASCADE | no |
| `summary_runs` | `SummaryRun` (summaries) | ForeignKey | CASCADE | no |
| `pipeline_runs` | `SummaryPipelineRun` (summaries) | ForeignKey | CASCADE | no |
| `movements` | `PatientMovement` (census) | ForeignKey | SET_NULL | yes |
| `evolution_extraction_coverage` | `EvolutionExtractionCoverage` (ingestion) | ForeignKey | CASCADE | no |
| `merged_from` | `Admission` (patients, self) | ForeignKey | SET_NULL | yes |
| `source_aliases` | `AdmissionSourceAlias` (patients) | ForeignKey | CASCADE | no |
| `discharge_evidence` | `DischargeRecord` (discharges) | ForeignKey | SET_NULL | yes |
| `reconciliation_events` | `ReconciliationEvent` (patients) | ForeignKey | SET_NULL | yes |

## Machine-readable accessor list

The integration test
`tests/integration/test_admission_identity_schema.py::TestRelationInventoryMatchesRuntime`
compares the following fenced block against
`Admission._meta.related_objects` accessor names at runtime. One accessor per
line, no duplicates.

```text
events
summary_state
summary_versions
summary_runs
pipeline_runs
movements
evolution_extraction_coverage
merged_from
source_aliases
discharge_evidence
reconciliation_events
```

## Query and write paths

- `apps/ingestion/services.py`: `upsert_admission_snapshot` (canonical
  admission writer; layered identity resolution with fail-closed ambiguity),
  `_consolidate_period_duplicates` (legacy duplicate cleanup; since the
  RPSA-S1 fix round it repoints aliases to the surviving canonical row and
  records the removed row's own key as an alias before deleting it),
  `persist_admissions_snapshot` (patient + admissions boundary shared by both
  workers), `backfill_admission_ward_from_census` (active admission
  ward/bed enrichment), `resolve_admission_for_event` (event-to-admission
  fallback), `_upsert_admission` (evolution-path admission upsert).
- `apps/patients/services.py`: `list_admissions_for_patient`,
  `get_admission_or_404`, `merge_patients` (patient-level merge),
  `resolve_admission_identity` and `ensure_admission_alias` (identity layer).
- `apps/census/admissions_recovery.py`: plans bounded `admissions_only` runs;
  no direct Admission queries.
- `apps/services_portal/views.py`: patient and admission listings (clinical
  surfaces; default manager excludes merged rows from RPSA-S1 onward).
- Admin (`apps/patients/admin.py`): admissions via the default manager;
  merged-row inspection is an RPSA-S4 concern.

## Semantics introduced by RPSA-S1

- Default manager `Admission.objects` returns canonical rows only
  (`merged_into__isnull=True`); `Admission.all_objects` is the explicit
  unfiltered maintenance access.
- `merged_into` is a marker only in this slice: no writer sets it in
  production flows, and the `ck_admission_no_self_merge` check constraint
  forbids self-reference.
- `AdmissionSourceAlias` preserves every observed external key with a
  `(source_system, alias_key)` uniqueness constraint so an alias resolves to
  exactly one canonical admission.
