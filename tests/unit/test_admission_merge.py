"""Source-confirmed admission merge and rollback (RPSA-S4).

Covers the pure source-confirmation eligibility decision, oldest-PK
canonical choice, per-relation transfer registry dispositions, alias
movement, append-only operation audit, atomic rollback with strict
post-state preconditions and the pinned loud-failure behavior of the
reconciliation apply lock when the target row is merged mid-flight.

All fixtures are synthetic; no production source is ever contacted.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from apps.census.models import PatientMovement
from apps.clinical_docs.models import ClinicalEvent
from apps.deaths.models import DeathRecord
from apps.discharges.models import DischargeRecord
from apps.ingestion.models import EvolutionExtractionCoverage, IngestionRun
from apps.patients.admission_merge import (
    ELIGIBLE,
    RELATION_DISPOSITION_KEEP,
    RELATION_DISPOSITION_REPOINT,
    REVIEW_REQUIRED,
    AdmissionMergeStateError,
    AdmissionSourceConfirmation,
    MergeNotEligible,
    MergeRollbackBlocked,
    SourceEpisode,
    StaleSourceConfirmation,
    UnhandledAdmissionRelation,
    build_relation_registry,
    decide_merge_eligibility,
    merge_admissions,
    rollback_admission_merge,
    source_confirmation_fingerprint,
)
from apps.patients.models import (
    Admission,
    AdmissionMergeOperation,
    AdmissionSourceAlias,
    Patient,
    ReconciliationEvent,
    StaleAdmissionCase,
)
from apps.patients.reconciliation import (
    DischargeExitEvidence,
    apply_discharge_exit,
    decide_discharge_match,
)
from apps.patients.services import resolve_admission_identity
from apps.summaries.models import (
    AdmissionSummaryState,
    AdmissionSummaryVersion,
    SummaryPipelineRun,
    SummaryRun,
)

TZ_LOCAL = ZoneInfo("America/Bahia")

REPOINTED_ACCESSORS = (
    "events",
    "summary_state",
    "summary_versions",
    "summary_runs",
    "pipeline_runs",
    "movements",
    "evolution_extraction_coverage",
    "source_aliases",
    "discharge_evidence",
    "death_evidence",
)

ALL_ACCESSORS = REPOINTED_ACCESSORS + (
    "merged_from",
    "reconciliation_events",
    "stale_cases",
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ_LOCAL)


def _census_run() -> IngestionRun:
    """Minimal succeeded census run for stale-case FK fixtures."""
    from django.utils import timezone

    return IngestionRun.objects.create(
        status="succeeded",
        intent="census_extraction",
        queued_at=timezone.now(),
        processing_started_at=timezone.now(),
    )


def _make_patient(key: str) -> Patient:
    return Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE {key}",
    )


def _make_admission(
    patient: Patient,
    key: str,
    start: str | None,
    end: str | None,
    *,
    ward: str = "",
    bed: str = "",
    source_patient_reference: str | None = None,
) -> Admission:
    # Every synthetic admission carries a non-empty record number so the
    # audit-identity assertions below can never pass vacuously.
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=_dt(start) if start else None,
        discharge_date=_dt(end) if end else None,
        ward=ward,
        bed=bed,
        source_patient_reference=(
            source_patient_reference
            if source_patient_reference is not None
            else f"PRONT-{key}"
        ),
    )


def _confirmation(
    episodes: int | list[SourceEpisode],
    *,
    failed: bool = False,
    captured_at: datetime | None = None,
    local_date: str = "2026-05-01",
    patient_record: str = "P_MERGE_1",
) -> AdmissionSourceConfirmation:
    if isinstance(episodes, int):
        built = [
            SourceEpisode(
                source_admission_key=f"SRC_EP_{index}",
                admission_start=_dt("2026-05-01T08:00:00"),
                admission_end=_dt("2026-05-03T10:00:00"),
            )
            for index in range(episodes)
        ]
    else:
        built = list(episodes)
    return AdmissionSourceConfirmation(
        patient_record=patient_record,
        local_admission_date=date.fromisoformat(local_date),
        captured_at=captured_at or _dt("2026-05-04T09:00:00"),
        failed=failed,
        episodes=tuple(built),
    )


def _eligible_pair() -> tuple[Patient, Admission, Admission]:
    """Open/closed duplicate pair: open row has the lower (oldest) pk.

    The record numbers are deliberately distinct synthetic values so any
    movement of the record number between rows is detectable.
    """
    patient = _make_patient("P_MERGE_1")
    canonical = _make_admission(
        patient,
        "ADM_OPEN",
        "2026-05-01T08:00:00",
        None,
        ward="ENF",
        source_patient_reference="PRONT-100200",
    )
    duplicate = _make_admission(
        patient,
        "ADM_CLOSED",
        "2026-05-01T09:00:00",
        "2026-05-03T10:00:00",
        bed="L03",
        source_patient_reference="PRONT-100201",
    )
    AdmissionSourceAlias.objects.create(
        admission=duplicate, source_system="tasy", alias_key="ADM_DUP_OLD"
    )
    return patient, canonical, duplicate


def _merge_pair(
    canonical: Admission, duplicate: Admission
) -> AdmissionMergeOperation:
    confirmation = _confirmation(
        [
            SourceEpisode(
                source_admission_key="ADM_CLOSED",
                admission_start=_dt("2026-05-01T08:00:00"),
                admission_end=_dt("2026-05-03T10:00:00"),
            )
        ]
    )
    result = merge_admissions(
        first=duplicate,
        second=canonical,
        confirmation=confirmation,
        expected_fingerprint=source_confirmation_fingerprint(confirmation),
    )
    return AdmissionMergeOperation.objects.get(
        operation_uuid=result.operation_uuid
    )


def _merged_pair() -> tuple[Patient, Admission, Admission, AdmissionMergeOperation]:
    patient, canonical, duplicate = _eligible_pair()
    operation = _merge_pair(canonical, duplicate)
    return patient, canonical, duplicate, operation


def _audit_identity_leaks(operation: AdmissionMergeOperation) -> list[str]:
    """Report record-number leaks inside the operation audit payloads.

    Scans ``before_state`` (including the recorded canonical after-state)
    and ``relation_manifest`` for the patient record number key.
    """

    leaks: list[str] = []

    def scan(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "source_patient_reference":
                    leaks.append(
                        f"audit payload carries source_patient_reference="
                        f"{value!r}"
                    )
                scan(value)
        elif isinstance(node, list):
            for item in node:
                scan(item)

    scan(operation.before_state)
    scan(operation.relation_manifest)
    return leaks


# ---------------------------------------------------------------------------
# Relation row factories (one per inventoried reverse relation)
# ---------------------------------------------------------------------------


def _attach_relation(accessor: str, duplicate: Admission, patient: Patient) -> None:
    """Attach one synthetic row to the duplicate for the given accessor."""
    day = date(2026, 5, 2)
    if accessor == "events":
        happened_at = duplicate.admission_date
        assert happened_at is not None
        ClinicalEvent.objects.create(
            admission=duplicate,
            patient=patient,
            event_identity_key="EVT-DUP",
            content_hash="hash-DUP",
            happened_at=happened_at,
            author_name="DR. TESTE",
            profession_type="medica",
            content_text="Evolucao sintetica DUP.",
        )
    elif accessor == "summary_state":
        AdmissionSummaryState.objects.create(
            admission=duplicate, coverage_start=day, coverage_end=day
        )
    elif accessor == "summary_versions":
        state = AdmissionSummaryState.objects.create(
            admission=duplicate, coverage_start=day, coverage_end=day
        )
        run = SummaryRun.objects.create(
            admission=duplicate, mode="generate", target_end_date=day
        )
        AdmissionSummaryVersion.objects.create(
            admission=duplicate,
            summary_state=state,
            run=run,
            chunk_index=0,
            coverage_start=day,
            coverage_end=day,
        )
    elif accessor == "summary_runs":
        SummaryRun.objects.create(
            admission=duplicate, mode="generate", target_end_date=day
        )
    elif accessor == "pipeline_runs":
        SummaryPipelineRun.objects.create(admission=duplicate, mode="generate")
    elif accessor == "movements":
        PatientMovement.objects.create(
            patient=patient,
            admission=duplicate,
            movement_date=day,
            first_seen_at=duplicate.created_at,
            last_seen_at=duplicate.created_at,
        )
    elif accessor == "evolution_extraction_coverage":
        EvolutionExtractionCoverage.objects.create(
            admission=duplicate, start_date=day, end_date=day
        )
    elif accessor == "merged_from":
        chained = _make_admission(
            patient, "ADM_CHAINED", "2026-05-01T10:00:00", None
        )
        chained.merged_into = duplicate
        chained.save(update_fields=["merged_into"])
    elif accessor == "source_aliases":
        AdmissionSourceAlias.objects.create(
            admission=duplicate, source_system="tasy", alias_key="ADM_EXTRA"
        )
    elif accessor == "discharge_evidence":
        DischargeRecord.objects.create(admission=duplicate, prontuario="")
    elif accessor == "death_evidence":
        DeathRecord.objects.create(admission=duplicate, date=day, prontuario="")
    elif accessor == "reconciliation_events":
        ReconciliationEvent.objects.create(
            admission=duplicate,
            source_kind="discharge_record",
            source_id=42,
            status="pending",
        )
    else:  # pragma: no cover - registry drift guard
        raise AssertionError(f"no fixture factory for relation {accessor}")


def _related_model(accessor: str):
    for relation in Admission._meta.related_objects:
        if relation.get_accessor_name() == accessor:
            return relation.related_model, relation.field.name
    raise AssertionError(accessor)  # pragma: no cover


# ---------------------------------------------------------------------------
# Eligibility (pure decision over the injected confirmation)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMergeEligibility:
    def test_fresh_single_episode_is_eligible(self, db: object) -> None:
        confirmation = _confirmation(1)
        decision = decide_merge_eligibility(confirmation=confirmation)
        assert decision.decision == ELIGIBLE
        assert decision.reason_code == ""
        assert decision.episode_count == 1
        assert decision.fingerprint == source_confirmation_fingerprint(
            confirmation
        )

    @pytest.mark.parametrize(
        ("episodes", "failed", "reason"),
        [
            (2, False, "multiple_episodes"),
            (0, False, "zero_episodes"),
            (1, True, "source_failed"),
        ],
    )
    def test_non_eligible_results_require_review(
        self, db: object, episodes: int, failed: bool, reason: str
    ) -> None:
        decision = decide_merge_eligibility(
            confirmation=_confirmation(episodes, failed=failed)
        )
        assert decision.decision == REVIEW_REQUIRED
        assert decision.reason_code == reason

    def test_fingerprint_is_stable_and_discriminating(self, db: object) -> None:
        one = _confirmation(1)
        again = _confirmation(1)
        other = _confirmation(
            [
                SourceEpisode(
                    source_admission_key="SRC_EP_0",
                    admission_start=_dt("2026-05-01T08:00:00"),
                    admission_end=_dt("2026-05-04T10:00:00"),
                )
            ]
        )
        assert (
            source_confirmation_fingerprint(one)
            == source_confirmation_fingerprint(again)
        )
        assert (
            source_confirmation_fingerprint(one)
            != source_confirmation_fingerprint(other)
        )


# ---------------------------------------------------------------------------
# Registry classification
# ---------------------------------------------------------------------------


class TestRelationRegistry:
    def test_registry_classifies_every_known_relation(self, db: object) -> None:
        registry = build_relation_registry()
        assert set(registry) == set(ALL_ACCESSORS)

    def test_dispositions_are_explicit(self, db: object) -> None:
        registry = build_relation_registry()
        repointed = {
            accessor
            for accessor, entry in registry.items()
            if entry.disposition == RELATION_DISPOSITION_REPOINT
        }
        kept = {
            accessor
            for accessor, entry in registry.items()
            if entry.disposition == RELATION_DISPOSITION_KEEP
        }
        assert kept == {
            "merged_from",
            "reconciliation_events",
            "stale_cases",
        }
        assert set(REPOINTED_ACCESSORS) <= repointed

    def test_unknown_relation_is_a_hard_error(self, db: object) -> None:
        from apps.patients import admission_merge

        with pytest.raises(UnhandledAdmissionRelation):
            admission_merge._disposition_for("does_not_exist")


# ---------------------------------------------------------------------------
# Merge execution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMergeExecution:
    def test_reversed_input_order_still_keeps_oldest_canonical(
        self, db: object
    ) -> None:
        patient, canonical, duplicate = _eligible_pair()
        operation = _merge_pair(canonical, duplicate)
        assert operation.canonical_admission_id == canonical.pk
        assert operation.merged_admission_id == duplicate.pk
        duplicate.refresh_from_db()
        assert duplicate.merged_into_id == canonical.pk

    def test_stale_confirmation_blocks_mutation(self, db: object) -> None:
        patient, canonical, duplicate = _eligible_pair()
        confirmation = _confirmation(1)
        other = _confirmation(1, local_date="2026-06-01")
        with pytest.raises(StaleSourceConfirmation):
            merge_admissions(
                first=duplicate,
                second=canonical,
                confirmation=confirmation,
                expected_fingerprint=source_confirmation_fingerprint(other),
            )
        duplicate.refresh_from_db()
        canonical.refresh_from_db()
        assert duplicate.merged_into_id is None
        assert canonical.discharge_date is None

    def test_not_eligible_confirmation_blocks_mutation(self, db: object) -> None:
        patient, canonical, duplicate = _eligible_pair()
        ineligible = _confirmation(2)
        with pytest.raises(MergeNotEligible):
            merge_admissions(
                first=duplicate,
                second=canonical,
                confirmation=ineligible,
                expected_fingerprint=source_confirmation_fingerprint(ineligible),
            )
        duplicate.refresh_from_db()
        assert duplicate.merged_into_id is None

    def test_already_merged_row_is_rejected(self, db: object) -> None:
        patient, canonical, duplicate, _ = _merged_pair()
        third = _make_admission(patient, "ADM_THIRD", "2026-05-02T08:00:00", None)
        confirmation = _confirmation(1)
        with pytest.raises(AdmissionMergeStateError):
            merge_admissions(
                first=third,
                second=duplicate,
                confirmation=confirmation,
                expected_fingerprint=source_confirmation_fingerprint(confirmation),
            )

    @pytest.mark.parametrize("accessor", REPOINTED_ACCESSORS)
    def test_repointed_relation_transfers_to_canonical(
        self, db: object, accessor: str
    ) -> None:
        patient, canonical, duplicate = _eligible_pair()
        _attach_relation(accessor, duplicate, patient)
        operation = _merge_pair(canonical, duplicate)

        registry = build_relation_registry()
        assert registry[accessor].disposition == RELATION_DISPOSITION_REPOINT

        model, field_name = _related_model(accessor)
        entry = operation.relation_manifest[accessor]
        if accessor == "source_aliases":
            moved_alias_keys = set(
                AdmissionSourceAlias.objects.filter(
                    admission=canonical
                ).values_list("alias_key", flat=True)
            )
            assert moved_alias_keys == {"ADM_DUP_OLD", "ADM_CLOSED", "ADM_EXTRA"}
            assert not AdmissionSourceAlias.objects.filter(
                admission=duplicate
            ).exists()
            return
        assert entry["moved"] >= 1, f"{accessor} must transfer"
        assert not model.objects.filter(**{field_name: duplicate}).exists()
        assert model.objects.filter(**{field_name: canonical}).exists()

    def test_kept_attached_relations_stay_on_merged_row(self, db: object) -> None:
        patient, canonical, duplicate = _eligible_pair()
        _attach_relation("reconciliation_events", duplicate, patient)
        _attach_relation("merged_from", duplicate, patient)
        StaleAdmissionCase.objects.create(
            admission=duplicate,
            first_absence_run=_census_run(),
            first_absence_at=_dt("2026-05-01T10:00:00"),
            last_absence_run=_census_run(),
            last_absence_at=_dt("2026-05-01T11:00:00"),
        )

        operation = _merge_pair(canonical, duplicate)
        registry = build_relation_registry()
        assert registry["merged_from"].disposition == RELATION_DISPOSITION_KEEP
        assert registry["reconciliation_events"].disposition == (
            RELATION_DISPOSITION_KEEP
        )
        assert registry["stale_cases"].disposition == (
            RELATION_DISPOSITION_KEEP
        )
        duplicate.refresh_from_db()
        assert list(
            duplicate.reconciliation_events.values_list("source_id", flat=True)
        ) == [42]
        # The reverse accessor uses the related model's default manager, so
        # the chained merged row is inspected through ``all_objects``.
        assert Admission.all_objects.filter(merged_into=duplicate).count() == 1
        assert operation.relation_manifest["reconciliation_events"]["disposition"] == (
            RELATION_DISPOSITION_KEEP
        )
        assert operation.relation_manifest["merged_from"]["attached"] == 1
        # The stale case stays attached to the row it was raised against
        # (frozen there by the RPSA-S5 scan/evaluation) and is recorded in
        # the manifest's kept relations.
        assert duplicate.stale_cases.count() == 1
        assert operation.relation_manifest["stale_cases"]["disposition"] == (
            RELATION_DISPOSITION_KEEP
        )

    def test_summary_state_conflict_stays_attached(self, db: object) -> None:
        patient, canonical, duplicate = _eligible_pair()
        day = date(2026, 5, 2)
        AdmissionSummaryState.objects.create(
            admission=canonical, coverage_start=day, coverage_end=day
        )
        AdmissionSummaryState.objects.create(
            admission=duplicate, coverage_start=day, coverage_end=day
        )
        operation = _merge_pair(canonical, duplicate)
        canonical.refresh_from_db()
        duplicate.refresh_from_db()
        # Conflict-safe: canonical keeps its own state; the duplicate's row is
        # never deleted and stays attached for maintenance visibility.
        assert canonical.summary_state is not None
        assert duplicate.summary_state is not None
        entry = operation.relation_manifest["summary_state"]
        assert entry["moved"] == 0
        assert entry["kept"] == 1

    def test_aliases_move_old_and_new_keys_resolve_canonical(
        self, db: object
    ) -> None:
        patient, canonical, duplicate, _ = _merged_pair()
        for key in ("ADM_OPEN", "ADM_CLOSED", "ADM_DUP_OLD"):
            match = resolve_admission_identity(
                patient=patient,
                source_system="tasy",
                source_admission_key=key,
                admission_start=None,
                admission_end=None,
            )
            assert match.admission is not None
            assert match.admission.pk == canonical.pk, key

    def test_period_combined_from_confirmation_without_empties(
        self, db: object
    ) -> None:
        patient, canonical, duplicate, _ = _merged_pair()
        canonical.refresh_from_db()
        assert canonical.admission_date == _dt("2026-05-01T08:00:00")
        assert canonical.discharge_date == _dt("2026-05-03T10:00:00")
        assert canonical.ward == "ENF"
        assert canonical.bed == "L03"

    def test_merged_row_persists_never_deleted(self, db: object) -> None:
        patient, canonical, duplicate, _ = _merged_pair()
        assert (
            Admission.all_objects.filter(pk__in=[canonical.pk, duplicate.pk]).count()
            == 2
        )
        duplicate.refresh_from_db()
        assert duplicate.merged_into_id == canonical.pk

    def test_clinical_queries_hide_merged_row(self, db: object) -> None:
        patient, canonical, duplicate, _ = _merged_pair()
        assert Admission.objects.filter(patient=patient).count() == 1
        assert Admission.objects.get(pk=canonical.pk).pk == canonical.pk
        with pytest.raises(Admission.DoesNotExist):
            Admission.objects.get(pk=duplicate.pk)

    def test_operation_audit_is_single_structural_and_immutable(
        self, db: object
    ) -> None:
        patient, canonical, duplicate, operation = _merged_pair()
        assert AdmissionMergeOperation.objects.count() == 1
        assert operation.canonical_admission_id == canonical.pk
        assert operation.merged_admission_id == duplicate.pk
        assert operation.rolled_back_at is None
        # The patient record number (prontuario) is identity: it is never
        # merged, snapshotted or restored. The canonical row keeps its own
        # value and the audit carries neither row's value.
        assert _audit_identity_leaks(operation) == []
        canonical.refresh_from_db()
        duplicate.refresh_from_db()
        assert canonical.source_patient_reference == "PRONT-100200"
        assert duplicate.source_patient_reference == "PRONT-100201"
        payload = {
            **operation.before_state,
            **operation.relation_manifest,
            "fingerprint": operation.source_fingerprint,
        }
        dumped = repr(payload).lower()
        for forbidden in (
            "paciente merge",
            "p_merge_1",
            "dr. teste",
            "pront-100200",
            "pront-100201",
        ):
            assert forbidden not in dumped

        payload_before = (
            operation.before_state,
            operation.relation_manifest,
            operation.source_fingerprint,
        )
        # A later non-eligible attempt must not touch the recorded payload.
        ineligible = _confirmation(0)
        with pytest.raises(MergeNotEligible):
            merge_admissions(
                first=duplicate,
                second=canonical,
                confirmation=ineligible,
                expected_fingerprint=source_confirmation_fingerprint(ineligible),
            )
        operation.refresh_from_db()
        assert (
            operation.before_state,
            operation.relation_manifest,
            operation.source_fingerprint,
        ) == payload_before

    def test_merge_logs_carry_no_patient_identity(
        self, db: object, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        patient, canonical, duplicate = _eligible_pair()
        confirmation = _confirmation(1)
        with caplog.at_level(logging.INFO, logger="apps.patients.admission_merge"):
            merge_admissions(
                first=duplicate,
                second=canonical,
                confirmation=confirmation,
                expected_fingerprint=source_confirmation_fingerprint(confirmation),
            )
        joined = "\n".join(record.getMessage() for record in caplog.records)
        assert "P_MERGE_1" not in joined
        assert "PACIENTE P_MERGE_1" not in joined


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRollback:
    def test_rollback_restores_fields_relations_aliases(self, db: object) -> None:
        patient, canonical, duplicate = _eligible_pair()
        happened_at = duplicate.admission_date
        assert happened_at is not None
        ClinicalEvent.objects.create(
            admission=duplicate,
            patient=patient,
            event_identity_key="EVT-RB",
            content_hash="hash-RB",
            happened_at=happened_at,
            author_name="DR. TESTE",
            profession_type="medica",
            content_text="Evolucao sintetica RB.",
        )
        operation = _merge_pair(canonical, duplicate)
        result = rollback_admission_merge(operation=operation)

        canonical.refresh_from_db()
        duplicate.refresh_from_db()
        assert duplicate.merged_into_id is None
        assert canonical.admission_date == _dt("2026-05-01T08:00:00")
        assert canonical.discharge_date is None
        assert canonical.ward == "ENF"
        assert canonical.bed == ""
        # The record number is never restored (it was never merged away):
        # the canonical row keeps its own value through the rollback.
        assert canonical.source_patient_reference == "PRONT-100200"
        assert duplicate.discharge_date == _dt("2026-05-03T10:00:00")
        assert duplicate.bed == "L03"
        assert duplicate.events.filter(event_identity_key="EVT-RB").exists()
        assert not canonical.events.exists()
        assert set(
            AdmissionSourceAlias.objects.filter(admission=duplicate).values_list(
                "alias_key", flat=True
            )
        ) == {"ADM_DUP_OLD"}
        # The fallback alias created by the operation (the duplicate's own
        # key) is never deleted: the merge module performs no deletes, and
        # resolution stays correct because the current-key layer shadows it.
        assert AdmissionSourceAlias.objects.filter(
            alias_key="ADM_CLOSED", admission=canonical
        ).exists()
        restored_match = resolve_admission_identity(
            patient=patient,
            source_system="tasy",
            source_admission_key="ADM_CLOSED",
            admission_start=None,
            admission_end=None,
        )
        assert restored_match.match_reason == "current_key"
        assert restored_match.admission is not None
        assert restored_match.admission.pk == duplicate.pk
        assert result.reverted_relations["events"] == 1

    def test_operation_records_rollback_state(self, db: object) -> None:
        patient, canonical, duplicate, operation = _merged_pair()
        payload_before = (operation.before_state, operation.relation_manifest)
        rollback_admission_merge(operation=operation)
        operation.refresh_from_db()
        assert operation.rolled_back_at is not None
        assert (operation.before_state, operation.relation_manifest) == payload_before

    def test_incompatible_mutation_blocks_rollback_without_partial_writes(
        self, db: object
    ) -> None:
        patient, canonical, duplicate, operation = _merged_pair()
        # Incompatible later mutation: the canonical discharge date changed
        # after the merge, so the recorded boundary no longer holds.
        canonical.discharge_date = _dt("2026-05-05T12:00:00")
        canonical.save(update_fields=["discharge_date", "updated_at"])

        counts_before = {
            accessor: _related_model(accessor)[0].objects.count()
            for accessor in ALL_ACCESSORS
        }
        with pytest.raises(MergeRollbackBlocked):
            rollback_admission_merge(operation=operation)

        canonical.refresh_from_db()
        duplicate.refresh_from_db()
        assert canonical.discharge_date == _dt("2026-05-05T12:00:00")
        assert duplicate.merged_into_id == canonical.pk
        for accessor, count in counts_before.items():
            assert _related_model(accessor)[0].objects.count() == count, accessor
        operation.refresh_from_db()
        assert operation.rolled_back_at is None

    def test_merged_into_drift_blocks_rollback(self, db: object) -> None:
        patient, canonical, duplicate, operation = _merged_pair()
        duplicate.merged_into = None
        duplicate.save(update_fields=["merged_into", "updated_at"])
        with pytest.raises(MergeRollbackBlocked):
            rollback_admission_merge(operation=operation)

    def test_rollback_twice_is_blocked(self, db: object) -> None:
        patient, canonical, duplicate, operation = _merged_pair()
        rollback_admission_merge(operation=operation)
        with pytest.raises(MergeRollbackBlocked):
            rollback_admission_merge(operation=operation)


# ---------------------------------------------------------------------------
# Apply-lock loud failure pinned as expected behavior (manager gate)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestApplyLockFailsLoudOnMergedTarget:
    def test_target_merged_mid_flight_raises_does_not_exist(
        self, db: object
    ) -> None:
        patient, canonical, duplicate = _eligible_pair()
        # The decision resolves the closed duplicate (a canonical row
        # before the merge) by its current external key.
        evidence = DischargeExitEvidence(
            patient_record=patient.patient_source_key,
            exit_datetime=_dt("2026-05-03T10:00:00"),
            admission_key=duplicate.source_admission_key,
            admission_start=duplicate.admission_date,
        )
        decision = decide_discharge_match(evidence=evidence)
        assert decision.admission is not None
        assert decision.admission.pk == duplicate.pk

        # Mid-flight: the decided row is merged into the older canonical
        # row between decide and apply.
        confirmation = _confirmation(
            [
                SourceEpisode(
                    source_admission_key="ADM_CLOSED",
                    admission_start=_dt("2026-05-01T08:00:00"),
                    admission_end=_dt("2026-05-03T10:00:00"),
                )
            ]
        )
        merge_admissions(
            first=duplicate,
            second=canonical,
            confirmation=confirmation,
            expected_fingerprint=source_confirmation_fingerprint(confirmation),
        )

        events_before = ReconciliationEvent.objects.count()
        with pytest.raises(Admission.DoesNotExist):
            apply_discharge_exit(
                decision=decision,
                exit_datetime=_dt("2026-05-03T10:00:00"),
                exit_type="hospital_discharge",
                source_kind="discharge_record",
                source_id=999,
            )
        canonical.refresh_from_db()
        duplicate.refresh_from_db()
        # The stage failed loudly and mutated nothing: the canonical row
        # keeps the merge-combined state and no reconciliation event was
        # written; the next cycle re-resolves the key through the alias.
        assert canonical.discharge_date == _dt("2026-05-03T10:00:00")
        assert duplicate.merged_into_id == canonical.pk
        assert ReconciliationEvent.objects.count() == events_before
        re_resolved = resolve_admission_identity(
            patient=patient,
            source_system="tasy",
            source_admission_key="ADM_CLOSED",
            admission_start=None,
            admission_end=None,
        )
        assert re_resolved.admission is not None
        assert re_resolved.admission.pk == canonical.pk
