# Admission Manager Call-Site Classification (RPSA-S4)

Required classification gate before any `merged_into` writer ships
(design decision 3). Every `Admission.objects` / reverse-accessor call
site in `apps/` is classified below as **clinical** (default manager:
merged rows hidden), **maintenance** (`all_objects`/unfiltered access),
**verify-with-test** (no edit; behavior pinned by an RPSA-S4 test), or
**not applicable** (regex false positive: `apps.admissions` module path
or a non-ORM attribute named `admissions`).

Derived from `rg -n "Admission\.objects|admission_set|\.admissions\b"
apps --glob '*.py' --glob '!**/migrations/**'` at BASE_REF `ce5ce03`
plus the RPSA-S4 merge module and admin additions. Line numbers refer to
that tree.

## Verdict summary

| Verdict | Sites |
| --- | --- |
| clinical (keep default manager) | 37 |
| maintenance (`all_objects` / `_base_manager`) | 4 |
| verify-with-test | 2 (both passed their mandated tests; no edit) |
| not applicable (regex false positive) | 8 |

## Clinical call sites (default manager kept — merged rows hidden)

| Site | Surface | Rationale |
| --- | --- | --- |
| `apps/census/services.py:295` | Ward/bed enrichment of the active admission | Clinical census enrichment; a merged duplicate must never receive census data. |
| `apps/census/services.py:780` | Best-effort active admission for a census movement | Clinical linkage; the canonical active episode is the correct target. |
| `apps/census/management/commands/sync_missing_discharges.py:31` | Latest-admission subquery | Stale/sync command; canonical-only prevents orphan duplicates from masking the real latest episode. |
| `apps/census/management/commands/sync_missing_discharges.py:35` | Active-admission candidates | Same surface as above. |
| `apps/census/management/commands/report_suspected_stale_inpatients.py:61` | Latest-admission subquery | Stale detection must judge the canonical episode only. |
| `apps/census/management/commands/report_suspected_stale_inpatients.py:79` | Latest-pk subquery | Same surface. |
| `apps/census/management/commands/report_suspected_stale_inpatients.py:83` | Active-admission candidates | Same surface. |
| `apps/services_portal/views.py:893` | Portal current-inpatient listing | Patient-facing clinical view; merged rows must stay invisible. |
| `apps/discharges/management/commands/refresh_daily_discharge_counts.py:29` | Aggregate of `discharge_date` | Operational indicator over canonical exits only; merged rows would double count. |
| `apps/summaries/services.py:354` | Admission fetch for summary processing | Summaries follow the canonical episode. |
| `apps/summaries/services.py:807` | Admission fetch for summary processing | Same surface. |
| `apps/summaries/services.py:1187` | Admission fetch for summary processing | Same surface. |
| `apps/ingestion/patient_flow_findings.py:318` | Cohort admissions lookup | Clinical findings surface over canonical rows. |
| `apps/ingestion/pipeline_health.py:371` | Freshness of `Admission.updated_at` | Health aggregate; merged rows are dormant by design and must not mask staleness. |
| `apps/ingestion/views.py:74` | Admission detail view | Display-only; merged rows are not clinical history. |
| `apps/ingestion/views.py:162` | Admission detail view | Display-only. |
| `apps/ingestion/views.py:292` | Admission listing for sync CTA | Display-only. |
| `apps/patients/services.py:73` | `resolve_admission_identity` base queryset | Canonical-only is the identity resolver's own contract (RPSA-S1): merged rows resolve through the alias layer pointing at the winner. |
| `apps/patients/services.py:257` | `list_admissions_for_patient` | Clinical patient listing; spec scenario "Merged admission is preserved but not clinically listed". |
| `apps/patients/services.py:265` | `get_admission_or_404` | Clinical detail fetch; a merged id 404s clinically by design. |
| `apps/patients/reconciliation.py:296` | Containing-period match layer | Matcher layer; a merged row must never be a reconciliation target. |
| `apps/patients/reconciliation.py:338` | Unique-local-date match layer | Same matcher contract. |
| `apps/patients/reconciliation.py:388` | Apply lock `select_for_update().get(...)` | Pinned expected behavior: a target merged between decide and apply raises `DoesNotExist` loudly; the stage fails and the next cycle re-resolves via alias. Pinned by `tests/unit/test_admission_merge.py::TestApplyLockFailsLoudOnMergedTarget`. Never "fix" silently. |
| `apps/ingestion/services.py:91` | `backfill_admission_ward_from_census` | Clinical ward/bed enrichment of active (canonical) admissions. |
| `apps/ingestion/services.py:345` | `_upsert_admission` (evolution path), key-unique `get_or_create` | Legacy evolution-path writer (no period in payload; key-only since RPSA-S1). A merged row's key hits the `uq_adm_src` unique constraint and fails loudly instead of recreating — fail-closed, pre-existing semantics, out of this slice's edit scope (residual risk recorded in the slice report). |
| `apps/ingestion/services.py:639` | Latest admission for full-sync enqueue | Clinical follow-up targeting of the canonical episode. |
| `apps/ingestion/services.py:819` | `_consolidate_period_duplicates` candidates | Legacy period-collapse consolidator (S1-hardened alias transfer). Ground truth: merged rows are invisible to the default manager, so the consolidator can never delete or re-collapse them. Out of scope beyond this note (design decision 3 keeps the two mechanisms separate). |
| `apps/ingestion/services.py:859` | Consolidator delete of same-period duplicates | Same surface as above; deletes only never-merged canonical duplicates. |
| `apps/ingestion/services.py:1111` | `resolve_admission_for_event` key layer | Clinical event-to-admission fallback over canonical rows. |
| `apps/ingestion/services.py:1121` | Period-match layer | Same fallback. |
| `apps/ingestion/services.py:1138` | Nearest-previous layer | Same fallback. |
| `apps/ingestion/services.py:1146` | Nearest-posterior layer | Same fallback. |
| `apps/ingestion/services.py:1153` | Final fallback layer | Same fallback. |
| `apps/discharges/services.py:125` | `_find_admission` exact-date lookup | Legacy `process_discharges` path: out of scope per the slice beyond the verify-with-test coverage; keeps default manager (a merged row is never a discharge target). |
| `apps/discharges/services.py:141` | `_find_admission` open-admission fallback | Same legacy path. |
| `apps/discharges/services.py:155` | `_find_admission` same-day-closed fallback | Same legacy path. |
| `apps/discharges/services.py:194` | `_get_or_create_recovery_admission` | Same legacy path; key collision with a merged row fails loudly on `uq_adm_src` instead of recreating. |

## Maintenance call sites (`all_objects` / unfiltered — must see merged rows)

| Site | Surface | Rationale |
| --- | --- | --- |
| `apps/patients/admission_merge.py:403` | `_lock_pair` (`all_objects.select_for_update`) | The merge/rollback module itself: both rows must lock even when one is already merged (chained merges, rollback). |
| `apps/patients/admission_merge.py` (`_related_rows` via `Model._base_manager`) | Relation transfer/verification queries | Maintenance transfers; the self-referential `merged_from` relation must observe hidden rows through the unfiltered base manager. |
| `apps/patients/admin.py:40` | `AdmissionAdmin.get_queryset` | Django admin must expose canonical and merged rows side by side (design decision 3 hard gate). |
| `apps/patients/services.py:296` | `merge_patients` admission re-point (pre-existing) | Patient-level merge is maintenance; skipping merged rows would cascade them away with the deleted patient (fixed in RPSA-S1 fix round). |

`merged_into` writers exist only in the merge module
(`apps/patients/admission_merge.py` merge step 7 and rollback step 1)
plus the field definition (`apps/patients/models.py:180`) and its
migration. The append-only `AdmissionMergeOperation` stores admission
identifiers as plain integers (no FK, no new reverse accessors), so the
pinned runtime inventory in
`tests/integration/test_admission_identity_schema.py` remains valid and
stays untouched in this slice.

## Verify-with-test (no edit; mandated tests passed)

| Site | Required behavior | Test (result) |
| --- | --- | --- |
| `apps/ingestion/services.py:963` (`Admission.objects.create` on the resolver-based admissions snapshot upsert path) | A merged row's key must resolve to the canonical winner through `resolve_admission_identity` and never create a second row. | `tests/integration/test_admission_merge.py::TestUpsertWithMergedRowKey::test_merged_row_key_resolves_winner_without_second_row` and `::test_merged_alias_key_resolves_winner_without_second_row` — both passed on the first GREEN run; no production edit required. |
| `apps/ingestion/management/commands/process_ingestion_runs_persistent_session.py:2039` (`.first()` target lookup) | Must stay None-guarded: a merged target pk resolves to `None` and the stage fails loudly with a sanitized `ValidationError`. | `tests/integration/test_admission_merge.py::TestPersistentSessionTargetLookupGuard::test_merged_target_pk_is_none_guarded_and_fails_loud` — passed on the first GREEN run; lookup was already None-guarded; no edit required. |

## Not applicable (regex false positives)

| Site | Why it matches |
| --- | --- |
| `apps/admissions/apps.py:8` | `name = "apps.admissions"` — app config string. |
| `apps/admissions/__init__.py:3` | Import of `AdmissionsConfig`. |
| `apps/admissions/services.py:364` | Import of `AdmissionRecord`/`DailyAdmissionCount` models (no `patients.Admission`). |
| `apps/admissions/management/commands/extract_admissions.py:22` | Import of `run_admission_extraction`. |
| `apps/services_portal/views.py:36` | Import of `DailyAdmissionCount`. |
| `apps/census/flow_service.py:19` | Import of `DailyAdmissionCount`. |
| `apps/ingestion/historical_recovery.py:141` | Import of `run_admission_extraction`. |
| `apps/ingestion/extractors/patient_flow_snapshot.py:100` | `self.admissions` — normalized snapshot payload attribute, not an ORM query. |

## Coverage proof

The final `rg -n "Admission\.objects|admission_set|\.admissions\b"`
listing contains exactly 47 matches and is a strict subset of the tables
above: 37 clinical + 2 verify-with-test + 8 not applicable. The regex
cannot see `all_objects`/`_base_manager` sites by construction, so those
are enumerated separately: all four maintenance sites above (merge lock,
merge-module relation transfers, admin queryset, `merge_patients`) map
to maintenance verdicts, and no site outside the merge module writes
`merged_into`.
