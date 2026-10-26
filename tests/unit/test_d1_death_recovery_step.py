"""Nightly D-1 date-only death step (ODR-S1).

Covers the post-extraction death reconciliation step of
``run_exit_reconciliation_runtime --mode d1``: every ``DeathRecord`` of the
recovered local date is classified read-only first and only a unique
date-granularity match reaches the online ``reconcile_death_record``
writer — it closes the episode on D 00:00 ``America/Bahia`` with the
date-only precision marker plus a lightweight runtime provenance stamp;
non-closable outcomes write nothing and are only counted; one record's
unexpected exception never stops the remaining records; the date scope
is strict.

All fixtures are synthetic; no patient identity may reach step output.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from apps.deaths.models import DeathRecord
from apps.ingestion.models import IngestionRun
from apps.patients.models import (
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    Patient,
    ReconciliationEvent,
)

TZ_LOCAL = ZoneInfo("America/Bahia")
RECOVERED_DATE = date(2026, 6, 14)

pytestmark = pytest.mark.django_db


def _make_patient(key: str) -> Patient:
    return Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE {key}",
    )


def _make_open_admission(patient: Patient, key: str, start: str) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=datetime.fromisoformat(start).replace(tzinfo=TZ_LOCAL),
        discharge_date=None,
    )


def _make_date_only_record(
    prontuario: str,
    *,
    day: date = RECOVERED_DATE,
) -> DeathRecord:
    return DeathRecord.objects.create(
        date=day,
        prontuario=prontuario,
        nome=f"PACIENTE {prontuario}",
        data_obito=day.strftime("%d/%m/%Y"),
    )


def _reconciled_events(record: DeathRecord):
    return ReconciliationEvent.objects.filter(
        source_kind="death_record",
        source_id=record.pk,
        status=RECONCILIATION_STATUS_RECONCILED,
    )


def _all_events(record: DeathRecord):
    return ReconciliationEvent.objects.filter(
        source_kind="death_record",
        source_id=record.pk,
    )


def _row_snapshot(record: DeathRecord) -> tuple:
    record.refresh_from_db()
    return (
        record.reconciliation_status,
        record.admission_id,
        record.reconciled_at,
        record.obito_em,
    )


def _assert_d1_no_writes(record: DeathRecord, before: tuple) -> None:
    """Non-closable D-1 outcomes write nothing: no audit event of any
    status, no evidence-row change, no mirror-sync run enqueued."""
    assert _all_events(record).count() == 0
    assert IngestionRun.objects.count() == 0
    assert _row_snapshot(record) == before


class TestDateOnlyDeathStep:
    def test_unique_match_closes_with_marker_carrier_and_runtime_provenance(
        self,
    ):
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            reconcile_d1_deaths,
        )

        patient = _make_patient("ODR-S1-101")
        admission = _make_open_admission(patient, "ADM-ODR-101", "2026-06-01T08:00:00")
        record = _make_date_only_record("ODR-S1-101")

        summary = reconcile_d1_deaths(day=RECOVERED_DATE)

        assert summary == {
            "reconciled": 1,
            "already_reconciled": 0,
            "pending": 0,
            "failed": 0,
        }
        admission.refresh_from_db()
        assert admission.discharge_date == datetime(2026, 6, 14, 0, 0, tzinfo=TZ_LOCAL)
        record.refresh_from_db()
        assert record.reconciliation_status == RECONCILIATION_STATUS_RECONCILED
        assert record.obito_em is None
        event = _reconciled_events(record).get()
        assert event.details_json["death_exit"] == {
            "precision": "date",
            "local_date": "2026-06-14",
        }
        assert event.details_json["runtime"] == {"mode": "d1"}

    def test_ambiguous_death_is_counted_without_any_write(self):
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            reconcile_d1_deaths,
        )

        patient = _make_patient("ODR-S1-102")
        first = _make_open_admission(patient, "ADM-ODR-102-A", "2026-05-01T08:00:00")
        second = _make_open_admission(patient, "ADM-ODR-102-B", "2026-05-15T08:00:00")
        record = _make_date_only_record("ODR-S1-102")
        before = _row_snapshot(record)

        summary = reconcile_d1_deaths(day=RECOVERED_DATE)

        assert summary == {
            "reconciled": 0,
            "already_reconciled": 0,
            "pending": 1,
            "failed": 0,
        }
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.discharge_date is None
        assert second.discharge_date is None
        _assert_d1_no_writes(record, before)

    def test_patient_not_found_is_counted_without_any_write(self):
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            reconcile_d1_deaths,
        )

        record = _make_date_only_record("ODR-S1-107")
        before = _row_snapshot(record)

        summary = reconcile_d1_deaths(day=RECOVERED_DATE)

        assert summary == {
            "reconciled": 0,
            "already_reconciled": 0,
            "pending": 1,
            "failed": 0,
        }
        _assert_d1_no_writes(record, before)

    def test_admission_not_found_is_counted_without_any_write(self):
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            reconcile_d1_deaths,
        )

        _make_patient("ODR-S1-108")
        record = _make_date_only_record("ODR-S1-108")
        before = _row_snapshot(record)

        summary = reconcile_d1_deaths(day=RECOVERED_DATE)

        assert summary == {
            "reconciled": 0,
            "already_reconciled": 0,
            "pending": 1,
            "failed": 0,
        }
        _assert_d1_no_writes(record, before)

    def test_unparseable_data_obito_is_counted_without_any_write(self):
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            reconcile_d1_deaths,
        )

        record = DeathRecord.objects.create(
            date=RECOVERED_DATE,
            prontuario="ODR-S1-109",
            nome="PACIENTE ODR-S1-109",
            data_obito="not-a-date",
        )
        before = _row_snapshot(record)

        summary = reconcile_d1_deaths(day=RECOVERED_DATE)

        assert summary == {
            "reconciled": 0,
            "already_reconciled": 0,
            "pending": 1,
            "failed": 0,
        }
        _assert_d1_no_writes(record, before)

    def test_out_of_scope_date_record_is_untouched(self):
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            reconcile_d1_deaths,
        )

        patient = _make_patient("ODR-S1-103")
        admission = _make_open_admission(patient, "ADM-ODR-103", "2026-06-01T08:00:00")
        other_day = RECOVERED_DATE - timedelta(days=1)
        record = _make_date_only_record("ODR-S1-103", day=other_day)

        summary = reconcile_d1_deaths(day=RECOVERED_DATE)

        assert summary == {
            "reconciled": 0,
            "already_reconciled": 0,
            "pending": 0,
            "failed": 0,
        }
        admission.refresh_from_db()
        assert admission.discharge_date is None
        record.refresh_from_db()
        assert record.reconciliation_status == RECONCILIATION_STATUS_PENDING

    def test_record_exception_does_not_stop_remaining_records(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        import apps.ingestion.management.commands.run_exit_reconciliation_runtime as runtime
        from apps.deaths import services as death_services

        # One patient per record so each match is unique on its own.
        broken_patient = _make_patient("ODR-S1-104-A")
        broken = _make_open_admission(broken_patient, "ADM-ODR-104-A", "2026-06-01T08:00:00")
        healthy_patient = _make_patient("ODR-S1-104-B")
        healthy = _make_open_admission(healthy_patient, "ADM-ODR-104-B", "2026-06-02T08:00:00")
        failing_record = _make_date_only_record("ODR-S1-104-A")
        closing_record = _make_date_only_record("ODR-S1-104-B")

        real_reconcile = death_services.reconcile_death_record

        def _flaky(*, record: DeathRecord, **kwargs: Any) -> str:
            if record.pk == failing_record.pk:
                raise RuntimeError("synthetic unexpected failure")
            return real_reconcile(record=record, **kwargs)

        monkeypatch.setattr(runtime, "reconcile_death_record", _flaky)

        with caplog.at_level("ERROR", logger=runtime.__name__):
            summary = runtime.reconcile_d1_deaths(day=RECOVERED_DATE)

        assert summary == {
            "reconciled": 1,
            "already_reconciled": 0,
            "pending": 0,
            "failed": 1,
        }
        broken.refresh_from_db()
        healthy.refresh_from_db()
        closing_record.refresh_from_db()
        assert broken.discharge_date is None
        assert healthy.discharge_date == datetime(2026, 6, 14, 0, 0, tzinfo=TZ_LOCAL)
        assert closing_record.reconciliation_status == RECONCILIATION_STATUS_RECONCILED
        assert str(failing_record.pk) in caplog.text
        assert "ODR-S1-104-A" not in caplog.text

    def test_empty_date_returns_zero_counts(self):
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            reconcile_d1_deaths,
        )

        assert reconcile_d1_deaths(day=RECOVERED_DATE) == {
            "reconciled": 0,
            "already_reconciled": 0,
            "pending": 0,
            "failed": 0,
        }

    def test_total_step_failure_propagates_for_caller_containment(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import apps.ingestion.management.commands.run_exit_reconciliation_runtime as runtime

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("synthetic total failure")

        monkeypatch.setattr(runtime.DeathRecord.objects, "filter", _boom)

        with pytest.raises(RuntimeError, match="synthetic total failure"):
            runtime.reconcile_d1_deaths(day=RECOVERED_DATE)

    def test_informative_repeat_counts_without_new_close_event(self):
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            reconcile_d1_deaths,
        )

        patient = _make_patient("ODR-S1-105")
        admission = _make_open_admission(patient, "ADM-ODR-105", "2026-06-01T08:00:00")
        record = _make_date_only_record("ODR-S1-105")

        first = reconcile_d1_deaths(day=RECOVERED_DATE)
        events_after_first = _all_events(record).count()
        record.refresh_from_db()
        reconciled_at_after_first = record.reconciled_at
        second = reconcile_d1_deaths(day=RECOVERED_DATE)

        assert first["reconciled"] == 1
        assert second == {
            "reconciled": 0,
            "already_reconciled": 1,
            "pending": 0,
            "failed": 0,
        }
        assert _all_events(record).count() == events_after_first
        record.refresh_from_db()
        assert record.reconciled_at == reconciled_at_after_first
        assert IngestionRun.objects.count() == 0
        admission.refresh_from_db()
        assert admission.discharge_date == datetime(2026, 6, 14, 0, 0, tzinfo=TZ_LOCAL)


class TestD1DeathStepCommandOutput:
    def test_completion_emits_success_marker_with_aggregate_counts(self):
        from io import StringIO

        from apps.census.orchestration import D1_DEATHS_SUCCESS_MARKER
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            Command,
        )

        patient = _make_patient("ODR-S1-301")
        _make_open_admission(patient, "ADM-ODR-301", "2026-06-01T08:00:00")
        _make_date_only_record("ODR-S1-301")
        ambiguous_patient = _make_patient("ODR-S1-302")
        _make_open_admission(ambiguous_patient, "ADM-ODR-302-A", "2026-05-01T08:00:00")
        _make_open_admission(ambiguous_patient, "ADM-ODR-302-B", "2026-05-15T08:00:00")
        _make_date_only_record("ODR-S1-302")

        cmd = Command()
        cmd.stdout = StringIO()
        cmd._reconcile_d1_deaths(RECOVERED_DATE)

        out = cmd.stdout.getvalue()
        assert D1_DEATHS_SUCCESS_MARKER in out
        assert "reconciled=1" in out
        assert "already_reconciled=0" in out
        assert "pending=1" in out
        assert "failed=0" in out

    def test_all_nonclosable_outcomes_emit_marker_with_pending_counts(self):
        from io import StringIO

        from apps.census.orchestration import D1_DEATHS_SUCCESS_MARKER
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            Command,
        )

        ambiguous_patient = _make_patient("ODR-S1-304")
        _make_open_admission(ambiguous_patient, "ADM-ODR-304-A", "2026-05-01T08:00:00")
        _make_open_admission(ambiguous_patient, "ADM-ODR-304-B", "2026-05-15T08:00:00")
        _make_date_only_record("ODR-S1-304")
        _make_date_only_record("ODR-S1-305")
        _make_patient("ODR-S1-306")
        _make_date_only_record("ODR-S1-306")

        cmd = Command()
        cmd.stdout = StringIO()
        cmd._reconcile_d1_deaths(RECOVERED_DATE)

        out = cmd.stdout.getvalue()
        assert D1_DEATHS_SUCCESS_MARKER in out
        assert "reconciled=0" in out
        assert "already_reconciled=0" in out
        assert "pending=3" in out
        assert "failed=0" in out
        assert ReconciliationEvent.objects.count() == 0
        assert IngestionRun.objects.count() == 0

    def test_total_failure_writes_failed_line_without_marker(self, monkeypatch: pytest.MonkeyPatch):
        from io import StringIO

        import apps.ingestion.management.commands.run_exit_reconciliation_runtime as runtime
        from apps.census.orchestration import D1_DEATHS_SUCCESS_MARKER
        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            Command,
        )

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("synthetic total failure")

        monkeypatch.setattr(runtime, "reconcile_d1_deaths", _boom)

        buf = StringIO()
        cmd = Command(stdout=buf)
        cmd._reconcile_d1_deaths(RECOVERED_DATE)

        out = buf.getvalue()
        assert D1_DEATHS_SUCCESS_MARKER not in out
        assert "mode=d1-deaths result=failed" in out
        assert "RuntimeError" in out

    def test_summary_carries_no_patient_identity(self):
        from io import StringIO

        from apps.ingestion.management.commands.run_exit_reconciliation_runtime import (
            Command,
        )

        sentinel_record = "PRONT-PRIV-ODR-S1"
        sentinel_name = "NOME-PRIV-ODR-S1"
        patient = Patient.objects.create(
            patient_source_key=sentinel_record,
            source_system="tasy",
            name=sentinel_name,
        )
        _make_open_admission(patient, "ADM-ODR-303", "2026-06-01T08:00:00")
        DeathRecord.objects.create(
            date=RECOVERED_DATE,
            prontuario=sentinel_record,
            nome=sentinel_name,
            data_obito=RECOVERED_DATE.strftime("%d/%m/%Y"),
        )

        cmd = Command()
        cmd.stdout = StringIO()
        cmd._reconcile_d1_deaths(RECOVERED_DATE)

        out = cmd.stdout.getvalue()
        assert sentinel_record not in out
        assert sentinel_name not in out


class TestRuntimeProvenancePayload:
    def test_online_path_without_payload_carries_no_runtime_key(self):
        from apps.deaths.services import reconcile_death_record

        patient = _make_patient("ODR-S1-106")
        _make_open_admission(patient, "ADM-ODR-106", "2026-06-01T08:00:00")
        record = _make_date_only_record("ODR-S1-106")

        assert reconcile_death_record(record=record) == RECONCILIATION_STATUS_RECONCILED
        event = _reconciled_events(record).get()
        assert "runtime" not in event.details_json

    def test_payload_scope_resets_after_block(self):
        from apps.patients.reconciliation import (
            current_runtime_payload,
            runtime_provenance_payload,
        )

        assert current_runtime_payload() is None
        with runtime_provenance_payload({"mode": "d1"}):
            assert current_runtime_payload() == {"mode": "d1"}
        assert current_runtime_payload() is None
