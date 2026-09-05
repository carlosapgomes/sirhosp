"""RPSA-S10 integration tests for the reconciliation health commands.

Proves the end-to-end command contracts against the isolated test
database:

- ``check_ingestion_pipeline_health`` gains the reconciliation sections;
- ``report_admission_reconciliation_integrity`` is a thin daily wrapper
  running the same evaluation with the default config;
- healthy dataset exits 0, any violation exits 1 (both commands);
- named thresholds are overridable through command options;
- evaluation is read-only (identical DB counts before/after);
- zero source/queue/automation calls occur;
- output is strictly aggregate-safe.

All fixtures are synthetic; production and source automation are never
touched.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.deaths.models import DeathRecord
from apps.discharges.models import DailyDischargeCount, DischargeRecord
from apps.ingestion.models import IngestionRun, IngestionRunStageMetric
from apps.patients.models import (
    RECONCILIATION_STATUS_AMBIGUOUS,
    RECONCILIATION_STATUS_CONFLICT,
    RECONCILIATION_STATUS_PENDING,
    Admission,
    Patient,
    ReconciliationEvent,
    StaleAdmissionCase,
)

CHECK_COMMAND = "check_ingestion_pipeline_health"
DAILY_COMMAND = "report_admission_reconciliation_integrity"

TZ_LOCAL = ZoneInfo("America/Bahia")
T_BASE = datetime(2026, 3, 10, 9, 0, 0, tzinfo=TZ_LOCAL)

SENTINEL_PRONT = "PRONT-PRIV-S10-INT"
SENTINEL_NAME = "NOME-PRIV-S10-INT"
SENTINEL_ADM = "ADM-PRIV-S10-INT"
SENTINEL_BED = "LEITO-PRIV-S10-INT"

pytestmark = pytest.mark.django_db


def _hours_ago(hours: int):
    return timezone.now() - timedelta(hours=hours)


def _make_patient(key: str) -> Patient:
    return Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE SINTETICO {key}",
    )


def _make_admission(
    patient: Patient,
    key: str,
    *,
    discharge_date=None,
) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=T_BASE,
        discharge_date=discharge_date,
    )


def _make_census_run(captured_at) -> IngestionRun:
    return IngestionRun.objects.create(
        status="succeeded",
        intent="census_extraction",
        queued_at=captured_at,
        processing_started_at=captured_at,
        finished_at=captured_at,
    )


def _make_occupied_census(prontuario: str) -> None:
    captured_at = _hours_ago(1)
    CensusSnapshot.objects.create(
        captured_at=captured_at,
        ingestion_run=_make_census_run(captured_at),
        setor="SETOR SINTETICO",
        setor_codigo="1000",
        leito=SENTINEL_BED,
        prontuario=prontuario,
        nome=f"PACIENTE SINTETICO {prontuario}",
        bed_status=BedStatus.OCCUPIED,
    )


def _make_case(*, first_absence_at) -> StaleAdmissionCase:
    patient = _make_patient(f"{SENTINEL_PRONT}-CASE")
    admission = _make_admission(patient, f"{SENTINEL_ADM}-CASE")
    last_absence_at = first_absence_at + timedelta(minutes=45)
    return StaleAdmissionCase.objects.create(
        admission=admission,
        first_absence_run=_make_census_run(first_absence_at),
        first_absence_at=first_absence_at,
        last_absence_run=_make_census_run(last_absence_at),
        last_absence_at=last_absence_at,
    )


def _make_violating_dataset() -> None:
    """Synthetic dataset breaching backlog, conflict and duplicate rules."""
    discharge = DischargeRecord.objects.create(
        prontuario=f"{SENTINEL_PRONT}-D1",
        data_internacao="01/03/2026",
        saida_em=_hours_ago(72),
        nome=SENTINEL_NAME,
        reconciliation_status=RECONCILIATION_STATUS_PENDING,
    )
    del discharge
    DeathRecord.objects.create(
        date=timezone.localdate(),
        prontuario=f"{SENTINEL_PRONT}-X1",
        nome=SENTINEL_NAME,
        reconciliation_status=RECONCILIATION_STATUS_AMBIGUOUS,
    )
    DischargeRecord.objects.create(
        prontuario=f"{SENTINEL_PRONT}-C1",
        data_internacao="02/03/2026",
        saida_em=_hours_ago(2),
        nome=SENTINEL_NAME,
        reconciliation_status=RECONCILIATION_STATUS_CONFLICT,
    )
    patient = _make_patient(f"{SENTINEL_PRONT}-DUP")
    opened = _make_admission(patient, f"{SENTINEL_ADM}-OPEN")
    closed = _make_admission(
        patient,
        f"{SENTINEL_ADM}-CLOSED",
        discharge_date=T_BASE + timedelta(days=3),
    )
    Admission.objects.filter(pk=closed.pk).update(updated_at=_hours_ago(1))
    Admission.objects.filter(pk=opened.pk).update(updated_at=_hours_ago(10))
    _make_case(first_absence_at=_hours_ago(72))


def _make_healthy_dataset() -> None:
    """Synthetic dataset with fresh evidence and full coverage."""
    patient = _make_patient(f"{SENTINEL_PRONT}-OK")
    _make_admission(patient, f"{SENTINEL_ADM}-OK")
    _make_occupied_census(f"{SENTINEL_PRONT}-OK")
    DischargeRecord.objects.create(
        prontuario=f"{SENTINEL_PRONT}-OK-D",
        data_internacao="03/03/2026",
        saida_em=_hours_ago(2),
        nome=SENTINEL_NAME,
        reconciliation_status=RECONCILIATION_STATUS_PENDING,
    )
    run = IngestionRun.objects.create(
        status="succeeded",
        intent="discharge_extraction",
        queued_at=_hours_ago(2),
        processing_started_at=_hours_ago(2),
        finished_at=_hours_ago(1),
        parameters_json={"date": "01/06/2026", "ref_date": "2026-06-01"},
    )
    IngestionRunStageMetric.objects.create(
        run=run,
        stage_name="discharge_persistence",
        started_at=_hours_ago(2),
        status="succeeded",
        details_json={"total_records": 3, "attempt_count": 1},
    )


def _call(command: str, *args: str) -> str:
    out = io.StringIO()
    err = io.StringIO()
    call_command(command, *args, stdout=out, stderr=err)
    return out.getvalue()


def _call_unhealthy(command: str, *args: str) -> tuple[str, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with pytest.raises(CommandError) as exc:
        call_command(command, *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue(), str(exc.value)


def _all_model_counts() -> dict[str, int]:
    models = (
        IngestionRun,
        IngestionRunStageMetric,
        CensusSnapshot,
        Admission,
        Patient,
        StaleAdmissionCase,
        ReconciliationEvent,
        DischargeRecord,
        DeathRecord,
        DailyDischargeCount,
    )
    return {model._meta.label: model.objects.count() for model in models}


class TestExitCodes:
    def test_healthy_dataset_check_command_exits_zero(self):
        _make_healthy_dataset()
        output = _call(CHECK_COMMAND)
        assert "healthy=true" in output
        assert "group=pending count=1" in output
        assert "open_outside_census=0" in output

    def test_healthy_dataset_daily_report_exits_zero(self):
        _make_healthy_dataset()
        output = _call(DAILY_COMMAND)
        assert "admission reconciliation integrity: healthy=true" in output

    def test_violating_dataset_check_command_exits_one(self):
        _make_violating_dataset()
        out, _err, error = _call_unhealthy(CHECK_COMMAND)
        assert "healthy=false" in out
        for code in (
            "reconciliation_backlog_age=1",
            "reconciliation_conflict_evidence=1",
            "reconciliation_duplicate_pair=1",
        ):
            assert code in out
            assert code in error

    def test_violating_dataset_daily_report_exits_one(self):
        _make_violating_dataset()
        out, _err, error = _call_unhealthy(DAILY_COMMAND)
        assert "admission reconciliation integrity: healthy=false" in out
        assert "reconciliation_duplicate_pair=1" in error
        assert "group=pending count=1 oldest_age_hours=" in out


class TestThresholdOptions:
    def test_backlog_age_default_keeps_fresh_evidence_healthy(self):
        patient = _make_patient(f"{SENTINEL_PRONT}-FRESH")
        del patient
        DischargeRecord.objects.create(
            prontuario=f"{SENTINEL_PRONT}-FRESH-D",
            data_internacao="04/03/2026",
            saida_em=_hours_ago(2),
            nome=SENTINEL_NAME,
            reconciliation_status=RECONCILIATION_STATUS_PENDING,
        )
        _call(CHECK_COMMAND)  # default 48h: healthy
        out, _err, _error = _call_unhealthy(
            CHECK_COMMAND, "--backlog-age-max-hours", "1"
        )
        assert "reconciliation_backlog_age=1" in out

    def test_missing_dates_option_lowers_the_operator_boundary(self):
        for ref_date in ("2026-06-01", "2026-06-02"):
            run = IngestionRun.objects.create(
                status="succeeded",
                intent="discharge_extraction",
                queued_at=_hours_ago(2),
                finished_at=_hours_ago(1),
                parameters_json={
                    "date": "01/06/2026",
                    "ref_date": ref_date,
                },
            )
            IngestionRunStageMetric.objects.create(
                run=run,
                stage_name="discharge_persistence",
                started_at=_hours_ago(2),
                status="succeeded",
                details_json={"total_records": 0, "attempt_count": 1},
            )
        _call(CHECK_COMMAND)  # default 7: gap of 2 stays healthy
        out, _err, _error = _call_unhealthy(
            CHECK_COMMAND, "--missing-dates-max", "1"
        )
        assert "extraction_coverage_gap=2" in out


class TestReadOnlyAndSafety:
    def test_both_commands_leave_the_database_identical(self):
        _make_violating_dataset()
        before = _all_model_counts()
        _call_unhealthy(CHECK_COMMAND)
        _call_unhealthy(DAILY_COMMAND)
        assert _all_model_counts() == before

    def test_both_commands_make_no_source_queue_or_automation_calls(self):
        _make_violating_dataset()
        with (
            mock.patch(
                "subprocess.Popen",
                side_effect=AssertionError("Popen called"),
            ),
            mock.patch(
                "subprocess.run",
                side_effect=AssertionError("subprocess.run called"),
            ),
            mock.patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("urllib called"),
            ),
            mock.patch(
                "django.core.management.call_command",
                side_effect=AssertionError("call_command called"),
            ),
            mock.patch(
                "playwright.sync_api.sync_playwright",
                side_effect=AssertionError("playwright called"),
            ),
            mock.patch(
                "apps.ingestion.services.queue_admissions_only_run",
                side_effect=AssertionError("queue write called"),
            ),
        ):
            _call_unhealthy(CHECK_COMMAND)
            _call_unhealthy(DAILY_COMMAND)


class TestIdentitySafeOutput:
    def test_aggregate_output_carries_no_identity(self):
        _make_violating_dataset()
        _make_occupied_census(f"{SENTINEL_PRONT}-SOMEONE-ELSE")
        out, err, error = _call_unhealthy(CHECK_COMMAND)
        daily_out, daily_err, daily_error = _call_unhealthy(DAILY_COMMAND)
        combined = out + err + error + daily_out + daily_err + daily_error
        for sentinel in (
            SENTINEL_PRONT,
            SENTINEL_NAME,
            SENTINEL_ADM,
            SENTINEL_BED,
        ):
            assert sentinel not in combined, f"sentinel leaked: {sentinel}"
        assert "group=pending count=1" in out
        assert "group=stale_cases count=1" in out
        assert "reconciliation_duplicates: pairs=1" in out
