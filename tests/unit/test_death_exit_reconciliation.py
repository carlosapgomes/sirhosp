"""Death-exit reconciliation and stable death evidence upsert (RPSA-S3).

Covers the death-evidence period layer of the canonical matcher (the
unique canonical admission whose known period contains a complete death
datetime — inclusive boundaries, zero/multiple candidates fail closed),
the ``death`` exit application with append-only audit, the
``data_obito`` parse layer (date-only never synthesizes an hour), the
stable-key ``process_deaths`` upsert (evidence PK/link/status survive
repeated extraction; snapshot-absent rows are detached, never deleted),
and the bounded/deduplicated source-synchronization requests.

All fixtures are synthetic.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from apps.deaths.models import DailyDeathCount, DeathRecord
from apps.deaths.services import process_deaths, reconcile_death_record
from apps.ingestion.models import IngestionRun
from apps.patients.models import (
    EXIT_DEATH,
    RECONCILIATION_STATUS_ADMISSION_NOT_FOUND,
    RECONCILIATION_STATUS_ALREADY_RECONCILED,
    RECONCILIATION_STATUS_AMBIGUOUS,
    RECONCILIATION_STATUS_PATIENT_NOT_FOUND,
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    Patient,
    ReconciliationEvent,
)
from apps.patients.reconciliation import (
    DischargeExitEvidence,
    apply_discharge_exit,
    decide_discharge_match,
)

TZ_LOCAL = ZoneInfo("America/Bahia")
REF_DATE = date(2026, 6, 1)


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
    end: str | None = None,
) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=(
            datetime.fromisoformat(start).replace(tzinfo=TZ_LOCAL)
            if start
            else None
        ),
        discharge_date=(
            datetime.fromisoformat(end).replace(tzinfo=TZ_LOCAL) if end else None
        ),
    )


def _death_evidence(**overrides: Any) -> DischargeExitEvidence:
    base: dict[str, Any] = dict(
        patient_record="555",
        exit_datetime=datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL),
        admission_key=None,
        admission_start=None,
        admission_local_date=None,
        source_system="tasy",
        match_by_period=True,
    )
    base.update(overrides)
    return DischargeExitEvidence(**base)


def _make_death_record(
    *,
    prontuario: str = "555",
    data_obito: str = "01/06/2026 12:00",
) -> DeathRecord:
    return DeathRecord.objects.create(
        date=REF_DATE,
        prontuario=prontuario,
        nome=f"PACIENTE {prontuario}",
        data_obito=data_obito,
    )


def _snapshot(*records: dict[str, str]) -> list[dict[str, str]]:
    return list(records)


RECORD_555 = {
    "PRONTUARIO": "555",
    "NOME": "PACIENTE 555",
    "OBITO": "01/06/2026 12:00",
    "DATA OBITO": "01/06/2026 12:00",
}


# =========================================================================
# Period layer of the pure match decision
# =========================================================================


@pytest.mark.django_db
class TestPeriodLayerDecision:
    def test_unique_containing_period_matches_as_death(self):
        patient = _make_patient("555")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        decision = decide_discharge_match(evidence=_death_evidence())
        assert decision.status == RECONCILIATION_STATUS_RECONCILED
        assert decision.admission is not None
        assert decision.admission.pk == admission.pk
        assert decision.exit_type == EXIT_DEATH

    def test_death_equal_to_admission_start_is_reconciled(self):
        """Inclusive left boundary: death exactly at the admission start is
        a valid containment (never ``invalid_exit_datetime``)."""
        patient = _make_patient("555")
        boundary = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)
        admission = _make_admission(patient, "ADM-1", "2026-06-01T12:00:00")
        decision = decide_discharge_match(
            evidence=_death_evidence(exit_datetime=boundary)
        )
        assert decision.status == RECONCILIATION_STATUS_RECONCILED
        assert decision.admission is not None
        assert decision.admission.pk == admission.pk

    def test_death_equal_to_discharge_date_is_already_reconciled(self):
        """Inclusive right boundary: death exactly at the recorded exit is
        ``already_reconciled`` — the period boundary contains the death."""
        patient = _make_patient("555")
        boundary = datetime(2026, 6, 10, 18, 0, tzinfo=TZ_LOCAL)
        _make_admission(
            patient,
            "ADM-1",
            "2026-05-20T08:00:00",
            end="2026-06-10T18:00:00",
        )
        decision = decide_discharge_match(
            evidence=_death_evidence(exit_datetime=boundary)
        )
        assert decision.status == RECONCILIATION_STATUS_ALREADY_RECONCILED

    def test_zero_containing_periods_is_admission_not_found(self):
        """Death before every known period never picks the latest
        admission (no open/latest fallback)."""
        patient = _make_patient("555")
        _make_admission(patient, "ADM-1", "2026-06-05T08:00:00")
        decision = decide_discharge_match(evidence=_death_evidence())
        assert decision.status == RECONCILIATION_STATUS_ADMISSION_NOT_FOUND
        assert decision.admission is None

    def test_multiple_containing_periods_are_ambiguous(self):
        patient = _make_patient("555")
        _make_admission(patient, "ADM-A", "2026-05-01T08:00:00")
        _make_admission(patient, "ADM-B", "2026-05-15T08:00:00")
        decision = decide_discharge_match(evidence=_death_evidence())
        assert decision.status == RECONCILIATION_STATUS_AMBIGUOUS
        assert decision.admission is None
        assert decision.candidate_count == 2

    def test_null_start_admission_is_not_a_candidate(self):
        """An admission with unknown start has no known period: it cannot
        contain the death datetime and is never a candidate."""
        patient = _make_patient("555")
        _make_admission(patient, "ADM-NULL", None)
        decision = decide_discharge_match(evidence=_death_evidence())
        assert decision.status == RECONCILIATION_STATUS_ADMISSION_NOT_FOUND
        assert decision.admission is None

    def test_closed_admission_excluding_death_is_not_a_candidate(self):
        """A closed period that ends before the death does not contain it."""
        patient = _make_patient("555")
        _make_admission(
            patient,
            "ADM-1",
            "2026-05-01T08:00:00",
            end="2026-05-10T10:00:00",
        )
        decision = decide_discharge_match(evidence=_death_evidence())
        assert decision.status == RECONCILIATION_STATUS_ADMISSION_NOT_FOUND

    def test_period_layer_is_opt_in_for_discharge_evidence(self):
        """Without ``match_by_period`` the discharge contract is unchanged:
        no key/start/local-date means ``admission_not_found`` — the patient's
        open admission is never a fallback."""
        patient = _make_patient("555")
        _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        decision = decide_discharge_match(
            evidence=_death_evidence(match_by_period=False)
        )
        assert decision.status == RECONCILIATION_STATUS_ADMISSION_NOT_FOUND


# =========================================================================
# Death exit application (transactional, append-only audit)
# =========================================================================


@pytest.mark.django_db
class TestApplyDeathExit:
    def test_death_close_stores_exact_timestamp_and_audits(self):
        patient = _make_patient("555")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        decision = decide_discharge_match(evidence=_death_evidence())
        death_at = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)

        status = apply_discharge_exit(
            decision=decision,
            exit_datetime=death_at,
            exit_type=EXIT_DEATH,
            source_kind="death_record",
            source_id=7,
        )

        assert status == RECONCILIATION_STATUS_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == death_at
        event = ReconciliationEvent.objects.get()
        assert event.exit_type == EXIT_DEATH
        assert event.source_kind == "death_record"
        assert event.source_id == 7
        assert event.prior_discharge_date is None
        assert event.new_discharge_date == death_at

    def test_repeated_death_evidence_is_already_reconciled(self):
        patient = _make_patient("555")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        decision = decide_discharge_match(evidence=_death_evidence())
        death_at = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)

        first = apply_discharge_exit(
            decision=decision,
            exit_datetime=death_at,
            exit_type=EXIT_DEATH,
            source_kind="death_record",
            source_id=7,
        )
        second = apply_discharge_exit(
            decision=decide_discharge_match(evidence=_death_evidence()),
            exit_datetime=death_at,
            exit_type=EXIT_DEATH,
            source_kind="death_record",
            source_id=7,
        )

        assert first == RECONCILIATION_STATUS_RECONCILED
        assert second == RECONCILIATION_STATUS_ALREADY_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == death_at
        assert ReconciliationEvent.objects.count() == 1

    def test_corrected_death_datetime_records_prior_and_new(self):
        """A corrected death datetime still inside the known period is an
        authoritative correction: prior/new values land in the audit.
        (A datetime AFTER the recorded exit falls outside the known period
        and fails closed as ``admission_not_found`` — the ground-truth
        containment predicate.)"""
        patient = _make_patient("555")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        death_at = datetime(2026, 6, 1, 15, 0, tzinfo=TZ_LOCAL)
        apply_discharge_exit(
            decision=decide_discharge_match(
                evidence=_death_evidence(exit_datetime=death_at)
            ),
            exit_datetime=death_at,
            exit_type=EXIT_DEATH,
            source_kind="death_record",
            source_id=7,
        )
        corrected = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)

        status = apply_discharge_exit(
            decision=decide_discharge_match(
                evidence=_death_evidence(exit_datetime=corrected)
            ),
            exit_datetime=corrected,
            exit_type=EXIT_DEATH,
            source_kind="death_record",
            source_id=7,
        )

        assert status == RECONCILIATION_STATUS_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == corrected
        event = ReconciliationEvent.objects.order_by("pk").last()
        assert event is not None
        assert event.prior_discharge_date == death_at
        assert event.new_discharge_date == corrected
        assert ReconciliationEvent.objects.count() == 2

    def test_death_after_recorded_exit_fails_closed(self):
        """A death datetime later than the recorded exit is outside the
        known period: zero candidates -> ``admission_not_found`` (never a
        blind latest/open fallback), and the admission stays untouched."""
        patient = _make_patient("555")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        death_at = datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)
        apply_discharge_exit(
            decision=decide_discharge_match(
                evidence=_death_evidence(exit_datetime=death_at)
            ),
            exit_datetime=death_at,
            exit_type=EXIT_DEATH,
            source_kind="death_record",
            source_id=7,
        )
        later = datetime(2026, 6, 1, 13, 30, tzinfo=TZ_LOCAL)

        decision = decide_discharge_match(
            evidence=_death_evidence(exit_datetime=later)
        )

        assert decision.status == RECONCILIATION_STATUS_ADMISSION_NOT_FOUND
        assert decision.admission is None
        admission.refresh_from_db()
        assert admission.discharge_date == death_at


# =========================================================================
# Evidence-side service entry point (parse + linkage + enqueue policy)
# =========================================================================


@pytest.mark.django_db
class TestReconcileDeathRecord:
    def test_complete_datetime_closes_and_links_evidence(self):
        patient = _make_patient("555")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        record = _make_death_record()

        status = reconcile_death_record(record=record)

        assert status == RECONCILIATION_STATUS_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == datetime(
            2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL
        )
        record.refresh_from_db()
        assert record.admission_id == admission.pk
        assert record.obito_em == datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)
        assert record.reconciliation_status == RECONCILIATION_STATUS_RECONCILED
        assert record.reconciled_at is not None
        event = ReconciliationEvent.objects.get()
        assert event.exit_type == EXIT_DEATH
        assert event.source_kind == "death_record"
        # Deaths never touch the discharge aggregate (integration proves
        # the full extraction flow; here the evidence path is pinned).

    def test_date_only_stays_pending_without_synthesized_hour(self):
        patient = _make_patient("555")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        record = _make_death_record(data_obito="01/06/2026")

        status = reconcile_death_record(record=record)

        assert status == RECONCILIATION_STATUS_PENDING
        admission.refresh_from_db()
        assert admission.discharge_date is None
        record.refresh_from_db()
        assert record.obito_em is None  # no midnight, noon or end of day
        assert record.reconciliation_status == RECONCILIATION_STATUS_PENDING
        assert record.admission_id is None
        assert ReconciliationEvent.objects.count() == 0
        assert (
            IngestionRun.objects.filter(intent="admissions_only").count() == 1
        )
        assert (
            IngestionRun.objects.filter(intent="demographics_only").count() == 0
        )

    def test_unparseable_death_date_stays_pending(self):
        patient = _make_patient("555")
        _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        record = _make_death_record(data_obito="sem data")

        status = reconcile_death_record(record=record)

        assert status == RECONCILIATION_STATUS_PENDING
        record.refresh_from_db()
        assert record.obito_em is None
        assert ReconciliationEvent.objects.count() == 0

    def test_patient_missing_enqueues_admissions_and_demographics(self):
        record = _make_death_record(prontuario="404")

        status = reconcile_death_record(record=record)

        assert status == RECONCILIATION_STATUS_PATIENT_NOT_FOUND
        assert Patient.objects.filter(patient_source_key="404").count() == 0
        assert Admission.objects.count() == 0
        record.refresh_from_db()
        assert record.admission_id is None
        assert (
            IngestionRun.objects.filter(intent="admissions_only").count() == 1
        )
        assert (
            IngestionRun.objects.filter(intent="demographics_only").count() == 1
        )
        assert (
            IngestionRun.objects.filter(intent="admissions_only").get()
            .parameters_json["patient_record"]
            == "404"
        )

    def test_ambiguous_enqueues_only_admissions(self):
        patient = _make_patient("555")
        _make_admission(patient, "ADM-A", "2026-05-01T08:00:00")
        _make_admission(patient, "ADM-B", "2026-05-15T08:00:00")
        record = _make_death_record()

        status = reconcile_death_record(record=record)

        assert status == RECONCILIATION_STATUS_AMBIGUOUS
        record.refresh_from_db()
        assert record.admission_id is None
        assert (
            IngestionRun.objects.filter(intent="admissions_only").count() == 1
        )
        assert (
            IngestionRun.objects.filter(intent="demographics_only").count() == 0
        )

    def test_repeated_reconciliation_is_idempotent(self):
        patient = _make_patient("555")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        record = _make_death_record()

        first = reconcile_death_record(record=record)
        second = reconcile_death_record(record=record)

        assert first == RECONCILIATION_STATUS_RECONCILED
        assert second == RECONCILIATION_STATUS_ALREADY_RECONCILED
        admission.refresh_from_db()
        assert admission.discharge_date == datetime(
            2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL
        )
        assert ReconciliationEvent.objects.count() == 1
        assert record.admission_id == admission.pk

    def test_sync_is_deduplicated_against_active_runs(self):
        IngestionRun.objects.create(
            status="queued",
            intent="admissions_only",
            parameters_json={
                "patient_record": "555",
                "intent": "admissions_only",
            },
        )
        record = _make_death_record(data_obito="01/06/2026")

        reconcile_death_record(record=record)

        assert IngestionRun.objects.filter(intent="admissions_only").count() == 1

    def test_logs_are_identity_safe(self, caplog):
        import logging

        patient = _make_patient("555")
        _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        record = _make_death_record()

        with caplog.at_level(logging.INFO):
            reconcile_death_record(record=record)
            missing = _make_death_record(prontuario="404")
            reconcile_death_record(record=missing)

        joined = caplog.text
        assert "555" not in joined
        assert "404" not in joined
        assert "PACIENTE" not in joined

    def test_audit_payloads_carry_no_patient_identity(self):
        patient = _make_patient("555")
        _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")
        record = _make_death_record()
        reconcile_death_record(record=record)

        event = ReconciliationEvent.objects.get()
        payload = json.dumps(
            {
                "details": event.details_json,
                "reason": event.reason_code,
                "status": event.status,
            }
        )
        assert "555" not in payload
        assert "PACIENTE" not in payload
        assert event.source_kind == "death_record"


# =========================================================================
# Stable-key upsert persistence (process_deaths)
# =========================================================================


@pytest.mark.django_db
class TestDeathUpsertPersistence:
    def test_repeated_persistence_preserves_pk_link_and_status(self):
        patient = _make_patient("555")
        admission = _make_admission(patient, "ADM-1", "2026-05-20T08:00:00")

        first = process_deaths(_snapshot(dict(RECORD_555)), reference_date=REF_DATE)
        record = DeathRecord.objects.get()
        original_pk = record.pk

        assert first["total_records"] == 1
        assert record.admission_id == admission.pk
        assert record.reconciliation_status == RECONCILIATION_STATUS_RECONCILED

        second = process_deaths(_snapshot(dict(RECORD_555)), reference_date=REF_DATE)
        record.refresh_from_db()

        assert second["total_records"] == 1
        assert record.pk == original_pk  # no delete/recreate
        assert record.admission_id == admission.pk
        assert record.reconciliation_status == (
            RECONCILIATION_STATUS_ALREADY_RECONCILED
        )
        assert DeathRecord.objects.count() == 1
        assert DailyDeathCount.objects.get(date=REF_DATE).count == 1

    def test_row_absent_from_repeated_snapshot_is_retained_and_detached(self):
        _make_patient("555")
        _make_admission(_make_patient("556"), "ADM-556", "2026-05-20T08:00:00")
        records = [
            dict(RECORD_555),
            {
                "PRONTUARIO": "556",
                "NOME": "PACIENTE 556",
                "OBITO": "01/06/2026 09:00",
                "DATA OBITO": "01/06/2026 09:00",
            },
        ]
        process_deaths(_snapshot(*records), reference_date=REF_DATE)
        assert DeathRecord.objects.count() == 2

        # Repeated snapshot no longer contains patient 556.
        second = process_deaths(
            _snapshot(dict(RECORD_555)), reference_date=REF_DATE
        )

        assert second["total_records"] == 1
        # The absent row survives as evidence, detached from the aggregate.
        assert DeathRecord.objects.count() == 2
        absent = DeathRecord.objects.get(prontuario="556")
        assert absent.daily_count_id is None
        present = DeathRecord.objects.get(prontuario="555")
        assert present.daily_count_id is not None
        # The aggregate reflects the new snapshot only.
        aggregate = DailyDeathCount.objects.get(date=REF_DATE)
        assert aggregate.count == 1
        assert aggregate.records.count() == 1

    def test_empty_snapshot_detaches_all_and_keeps_evidence(self):
        _make_patient("555")
        process_deaths(_snapshot(dict(RECORD_555)), reference_date=REF_DATE)
        record = DeathRecord.objects.get()

        result = process_deaths(_snapshot(), reference_date=REF_DATE)

        assert result["total_records"] == 0
        record.refresh_from_db()
        assert record.pk is not None  # evidence retained
        assert record.daily_count_id is None
        assert DailyDeathCount.objects.get(date=REF_DATE).count == 0

    def test_corrected_death_datetime_on_re_extraction(self):
        """Corrected datetime still inside the known period (15:00 ->
        12:00): same evidence row (stable PK), updated ``obito_em`` and
        prior/new audit values."""
        _make_patient("555")
        admission = _make_admission(
            Patient.objects.get(patient_source_key="555"),
            "ADM-1",
            "2026-05-20T08:00:00",
        )
        first_snapshot = dict(RECORD_555)
        first_snapshot["OBITO"] = "01/06/2026 15:00"
        first_snapshot["DATA OBITO"] = "01/06/2026 15:00"
        process_deaths(_snapshot(first_snapshot), reference_date=REF_DATE)
        record = DeathRecord.objects.get()
        original_pk = record.pk

        corrected = dict(RECORD_555)
        corrected["OBITO"] = "01/06/2026 12:00"
        corrected["DATA OBITO"] = "01/06/2026 12:00"
        result = process_deaths(_snapshot(corrected), reference_date=REF_DATE)

        assert result["total_records"] == 1
        record.refresh_from_db()
        assert record.pk == original_pk
        assert record.obito_em == datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)
        admission.refresh_from_db()
        assert admission.discharge_date == datetime(
            2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL
        )
        correction = ReconciliationEvent.objects.order_by("pk").last()
        assert correction is not None
        assert correction.prior_discharge_date == datetime(
            2026, 6, 1, 15, 0, tzinfo=TZ_LOCAL
        )
        assert correction.new_discharge_date == datetime(
            2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL
        )

    def test_unresolved_upsert_does_not_create_synthetic_rows(self):
        process_deaths(_snapshot(dict(RECORD_555)), reference_date=REF_DATE)

        assert Patient.objects.count() == 0
        assert Admission.objects.count() == 0
        assert (
            IngestionRun.objects.filter(intent="admissions_only").count() == 1
        )
        assert (
            IngestionRun.objects.filter(intent="demographics_only").count() == 1
        )

    def test_repeated_unresolved_upsert_does_not_duplicate_sync(self):
        process_deaths(_snapshot(dict(RECORD_555)), reference_date=REF_DATE)
        process_deaths(_snapshot(dict(RECORD_555)), reference_date=REF_DATE)

        # Second pass: patient still missing -> dedup keeps a single active
        # run per intent (the first run is still queued).
        assert IngestionRun.objects.filter(
            intent="admissions_only", status="queued"
        ).count() == 1
