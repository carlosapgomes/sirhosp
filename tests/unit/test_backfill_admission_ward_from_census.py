"""Tests for the shared backfill_admission_ward_from_census service (PSW-S8).

Covers:
- active admission receives ward/bed from the latest occupied CensusSnapshot;
- absence of census leaves admissions unchanged;
- discharged admissions are never altered;
- the legacy worker's wrapper delegates to the shared service.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from apps.census.models import BedStatus, CensusSnapshot
from apps.ingestion.services import backfill_admission_ward_from_census
from apps.patients.models import Admission, Patient

UTC = ZoneInfo("UTC")
TZ_INSTITUTIONAL = ZoneInfo("America/Sao_Paulo")


def _make_patient(*, key: str = "PT001") -> Patient:
    return Patient.objects.create(
        source_system="tasy",
        patient_source_key=key,
        name="Sintético",
    )


def _make_admission(
    patient: Patient,
    *,
    discharge_date: datetime | None = None,
    ward: str = "",
    bed: str = "",
    key: str = "ADM-001",
) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_admission_key=key,
        source_system="tasy",
        admission_date=datetime(2024, 1, 1, 9, 0, tzinfo=TZ_INSTITUTIONAL),
        discharge_date=discharge_date,
        ward=ward,
        bed=bed,
    )


def _make_census(
    *,
    prontuario: str,
    setor: str,
    leito: str,
    captured_at: datetime,
    bed_status: str = BedStatus.OCCUPIED,
) -> CensusSnapshot:
    return CensusSnapshot.objects.create(
        captured_at=captured_at,
        setor=setor,
        leito=leito,
        prontuario=prontuario,
        nome="Sintético",
        especialidade="TEST",
        bed_status=bed_status,
    )


@pytest.mark.django_db
class TestBackfillAdmissionWardFromCensus:
    def test_active_admission_receives_ward_and_bed_from_latest_census(self) -> None:
        """An active admission is updated with the latest census ward/bed."""
        patient = _make_patient()
        adm = _make_admission(patient, ward="", bed="")

        now = datetime.now(tz=TZ_INSTITUTIONAL)
        # Older census
        _make_census(
            prontuario=patient.patient_source_key,
            setor="Enfermaria Antiga",
            leito="001",
            captured_at=now - timedelta(days=2),
        )
        # Latest census (should win)
        _make_census(
            prontuario=patient.patient_source_key,
            setor="UTI",
            leito="005",
            captured_at=now,
        )

        backfill_admission_ward_from_census(patient)

        adm.refresh_from_db()
        assert adm.ward == "UTI"
        assert adm.bed == "005"

    def test_absence_of_census_leaves_admission_unchanged(self) -> None:
        """No census for the patient -> admission is not modified."""
        patient = _make_patient()
        adm = _make_admission(patient, ward="Original", bed="010")

        backfill_admission_ward_from_census(patient)

        adm.refresh_from_db()
        assert adm.ward == "Original"
        assert adm.bed == "010"

    def test_discharged_admission_is_not_altered(self) -> None:
        """Admissions with discharge_date set are skipped even if census exists."""
        patient = _make_patient()
        discharged = datetime(2024, 1, 10, 12, 0, tzinfo=TZ_INSTITUTIONAL)
        adm = _make_admission(
            patient, ward="", bed="", discharge_date=discharged, key="ADM-DISCH"
        )

        _make_census(
            prontuario=patient.patient_source_key,
            setor="UTI",
            leito="005",
            captured_at=datetime.now(tz=TZ_INSTITUTIONAL),
        )

        backfill_admission_ward_from_census(patient)

        adm.refresh_from_db()
        assert adm.ward == ""
        assert adm.bed == ""

    def test_empty_bed_census_is_ignored(self) -> None:
        """Only occupied beds feed the backfill."""
        patient = _make_patient()
        adm = _make_admission(patient, ward="Keep", bed="Keep")

        _make_census(
            prontuario=patient.patient_source_key,
            setor="UTI",
            leito="005",
            captured_at=datetime.now(tz=TZ_INSTITUTIONAL),
            bed_status=BedStatus.EMPTY,
        )

        backfill_admission_ward_from_census(patient)

        adm.refresh_from_db()
        assert adm.ward == "Keep"
        assert adm.bed == "Keep"


class TestLegacyWorkerWrapperDelegation:
    """The legacy worker's staticmethod delegates to the shared service."""

    def test_legacy_wrapper_calls_shared_service(self) -> None:
        """process_ingestion_runs._backfill_admission_ward_from_census delegates."""
        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )

        sentinel = object()
        with patch(
            "apps.ingestion.services.backfill_admission_ward_from_census"
        ) as mock_service:
            Command._backfill_admission_ward_from_census(sentinel)

        mock_service.assert_called_once_with(sentinel)
