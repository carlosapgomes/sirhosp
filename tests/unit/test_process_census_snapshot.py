from __future__ import annotations

import pytest
from django.utils import timezone

from apps.census.models import (
    BedStatus,
    CapacityCatalogVersion,
    CapacityGroupDefinition,
    CapacitySectorMembership,
    CensusSnapshot,
    DailyOccupancySummary,
    OccupancyMeasurement,
)
from apps.census.occupancy import OccupancyMaterializationError
from apps.census.services import (
    _sync_admission_ward_bed,
    process_census_snapshot,
)
from apps.ingestion.models import CensusExecutionBatch, IngestionRun
from apps.patients.models import Admission, Patient


def _add_filler_snapshots(
    *,
    captured_at,
    run=None,
    exclude: set[str] | None = None,
    sector_count: int = 40,
) -> None:
    """Add empty-bed snapshots so a group reaches the minimum sector count.

    The GCEC-S2 completeness guard rejects snapshot sets with fewer than 40
    distinct sectors. Tests exercising the happy path build complete sets
    with empty-bed filler rows, which never create patients or ingestion
    runs.

    Args:
        captured_at: Timestamp shared with the scenario snapshots so the
            latest-captured-at group stays complete.
        run: Optional ingestion run to link filler rows to (required when
            exercising the explicit ``run_id`` path).
        exclude: Sector names already used by the scenario snapshots.
        sector_count: Target distinct-sector count (default 40).
    """
    existing = set(exclude or set())
    missing = max(0, sector_count - len(existing))
    for i in range(missing):
        CensusSnapshot.objects.create(
            captured_at=captured_at,
            ingestion_run=run,
            setor=f"SETOR FILLER {i:03d}",
            leito=f"FL{i:03d}",
            prontuario="",
            nome="DESOCUPADO",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )


@pytest.mark.django_db
class TestProcessCensusSnapshot:
    def test_empty_snapshot_returns_zero(self):
        """When no CensusSnapshot exists, all counts are zero."""
        result = process_census_snapshot()
        assert result["patients_total"] == 0
        assert result["patients_new"] == 0
        assert result["runs_enqueued"] == 0
        assert result["demographics_runs_enqueued"] == 0

    def test_only_empty_beds_no_patients(self):
        """Beds without prontuario are skipped (complete snapshot set)."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run,
            setor="UTI A",
            leito="01",
            prontuario="",
            nome="DESOCUPADO",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        _add_filler_snapshots(captured_at=now, run=run, exclude={"UTI A"})
        result = process_census_snapshot()
        assert result["patients_total"] == 0
        assert result["runs_enqueued"] == 0
        assert result["demographics_runs_enqueued"] == 0
        assert Patient.objects.count() == 0

    def test_new_patient_created_and_run_enqueued(self):
        """New prontuario → Patient created + admissions_only enqueued."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        _add_filler_snapshots(captured_at=now, run=run, exclude={"UTI A"})
        result = process_census_snapshot()
        assert result["patients_new"] == 1
        assert result["patients_total"] == 1
        assert result["runs_enqueued"] == 1
        assert result["demographics_runs_enqueued"] == 1

        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="14160147"
        )
        assert patient.name == "JOSE AUGUSTO MERCES"

        # Verify IngestionRun was enqueued
        queued_run = IngestionRun.objects.filter(
            intent="admissions_only", status="queued"
        ).first()
        assert queued_run is not None
        assert queued_run.parameters_json["patient_record"] == "14160147"

    def test_existing_patient_not_duplicated(self):
        """Patient already exists → no duplicate, but run is still enqueued."""
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="14160147",
            name="JOSE AUGUSTO MERCES",
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        _add_filler_snapshots(captured_at=now, run=run, exclude={"UTI A"})
        result = process_census_snapshot()
        assert result["patients_new"] == 0
        assert result["patients_updated"] == 0
        assert result["runs_enqueued"] == 1
        assert result["demographics_runs_enqueued"] == 1
        assert Patient.objects.count() == 1

    def test_existing_patient_name_updated(self):
        """Patient exists with different name → name updated."""
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="14160147",
            name="NOME ANTIGO",
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="NOME NOVO",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        _add_filler_snapshots(captured_at=now, run=run, exclude={"UTI A"})
        result = process_census_snapshot()
        assert result["patients_updated"] == 1
        assert result["runs_enqueued"] == 1
        assert result["demographics_runs_enqueued"] == 1

        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="14160147"
        )
        assert patient.name == "NOME NOVO"

    def test_duplicate_prontuario_in_same_run_deduplicated(self):
        """Same prontuario appears twice → only 1 run enqueued."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        snap_time = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=snap_time,
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=snap_time,
            ingestion_run=run,
            setor="UTI A",
            leito="UG01B",
            prontuario="14160147",
            nome="JOSE MERCES UPDATED",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        _add_filler_snapshots(
            captured_at=snap_time, run=run, exclude={"UTI A"}
        )
        result = process_census_snapshot()
        assert result["runs_enqueued"] == 1
        assert result["demographics_runs_enqueued"] == 1
        assert result["patients_total"] == 1
        assert result["patients_skipped_duplicate"] == 1
        assert result["patients_skipped_no_pront"] == 0

        # Name should be from the LAST occupied occurrence (both have equal esp)
        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="14160147"
        )
        last_occupied = (
            CensusSnapshot.objects.filter(bed_status=BedStatus.OCCUPIED)
            .order_by("-pk")
            .first()
        )
        assert patient.name == last_occupied.nome

    def test_duplicate_prontuario_prefers_non_empty_especialidade(self):
        """When duplicate prontuario exists, prefer the entry with
        non-empty especialidade over one with empty especialidade."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        snap_time = timezone.now()
        # First: empty especialidade (simulates the RN duplicate pattern)
        CensusSnapshot.objects.create(
            captured_at=snap_time,
            ingestion_run=run,
            setor="OBSTETRICIA",
            leito="302AD",
            prontuario="19673094",
            nome="RN NOEMI SILVA PEREIRA",
            especialidade="",
            bed_status=BedStatus.OCCUPIED,
        )
        # Second: same prontuario, with NEO especialidade
        CensusSnapshot.objects.create(
            captured_at=snap_time,
            ingestion_run=run,
            setor="OBSTETRICIA",
            leito="302AE",
            prontuario="19673094",
            nome="RN NOEMI SILVA PEREIRA",
            especialidade="NEO",
            bed_status=BedStatus.OCCUPIED,
        )
        _add_filler_snapshots(
            captured_at=snap_time, run=run, exclude={"OBSTETRICIA"}
        )
        result = process_census_snapshot()
        assert result["runs_enqueued"] == 1
        assert result["patients_total"] == 1
        assert result["patients_skipped_duplicate"] == 1
        assert result["patients_skipped_no_pront"] == 0

        # The patient should have the name from the entry with NEO esp
        # (even if it's not the last by pk, the NEO entry is preferred)
        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="19673094"
        )
        # Both have same name in this case, but we care about the logic
        assert patient.name == "RN NOEMI SILVA PEREIRA"

    def test_specific_run_id(self):
        """Can process a specific run by ID."""
        run1 = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        old_now = timezone.now() - timezone.timedelta(hours=2)
        CensusSnapshot.objects.create(
            captured_at=old_now,
            ingestion_run=run1,
            setor="OLD",
            leito="01",
            prontuario="111",
            nome="OLD PATIENT",
            especialidade="TST",
            bed_status=BedStatus.OCCUPIED,
        )
        _add_filler_snapshots(captured_at=old_now, run=run1, exclude={"OLD"})

        run2 = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            ingestion_run=run2,
            setor="NEW",
            leito="01",
            prontuario="222",
            nome="NEW PATIENT",
            especialidade="TST",
            bed_status=BedStatus.OCCUPIED,
        )

        # Process only run1
        result = process_census_snapshot(run_id=run1.pk)
        assert result["patients_total"] == 1
        assert result["runs_enqueued"] == 1
        assert result["demographics_runs_enqueued"] == 1
        assert Patient.objects.filter(patient_source_key="111").exists()
        assert not Patient.objects.filter(patient_source_key="222").exists()

    def test_multiple_patients_in_snapshot(self):
        """Multiple occupied beds → multiple patients + runs."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        for i, (pront, nome) in enumerate(
            [("111", "A"), ("222", "B"), ("333", "C")]
        ):
            CensusSnapshot.objects.create(
                captured_at=now,
                ingestion_run=run,
                setor=f"UTI {i}",
                leito=f"L{i}",
                prontuario=pront,
                nome=nome,
                especialidade="TST",
                bed_status=BedStatus.OCCUPIED,
            )
        _add_filler_snapshots(
            captured_at=now,
            run=run,
            exclude={"UTI 0", "UTI 1", "UTI 2"},
        )
        result = process_census_snapshot()
        assert result["patients_total"] == 3
        assert result["patients_new"] == 3
        assert result["runs_enqueued"] == 3
        assert result["demographics_runs_enqueued"] == 3
        assert Patient.objects.count() == 3
        assert IngestionRun.objects.filter(
            intent="admissions_only", status="queued"
        ).count() == 3

    def test_demographics_run_enqueued_for_new_patient(self):
        """New patient → demographics_only run is also enqueued."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        _add_filler_snapshots(captured_at=now, run=run, exclude={"UTI A"})
        result = process_census_snapshot()

        assert result["demographics_runs_enqueued"] == 1

        # Verify demographics run exists
        demo_run = IngestionRun.objects.filter(
            intent="demographics_only", status="queued"
        ).first()
        assert demo_run is not None
        assert demo_run.parameters_json["patient_record"] == "14160147"

        # Verify admissions run also exists (existing behavior)
        adm_run = IngestionRun.objects.filter(
            intent="admissions_only", status="queued"
        ).first()
        assert adm_run is not None

    def test_demographics_run_enqueued_for_existing_patient(self):
        """Existing patient → demographics_only run is still enqueued."""
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="14160147",
            name="JOSE MERCES",
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        _add_filler_snapshots(captured_at=now, run=run, exclude={"UTI A"})
        result = process_census_snapshot()

        # Demographics run should be enqueued even for existing patients
        assert result["demographics_runs_enqueued"] == 1
        assert IngestionRun.objects.filter(
            intent="demographics_only", status="queued"
        ).exists()

    def test_multiple_patients_get_demographics_runs(self):
        """Multiple occupied beds → one demographics run per patient."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        for i, (pront, nome) in enumerate(
            [("111", "A"), ("222", "B"), ("333", "C")]
        ):
            CensusSnapshot.objects.create(
                captured_at=now,
                ingestion_run=run,
                setor=f"UTI {i}",
                leito=f"L{i}",
                prontuario=pront,
                nome=nome,
                especialidade="TST",
                bed_status=BedStatus.OCCUPIED,
            )
        _add_filler_snapshots(
            captured_at=now,
            run=run,
            exclude={"UTI 0", "UTI 1", "UTI 2"},
        )
        result = process_census_snapshot()
        assert result["demographics_runs_enqueued"] == 3
        assert result["runs_enqueued"] == 3  # admissions runs
        assert IngestionRun.objects.filter(
            intent="demographics_only", status="queued"
        ).count() == 3

    def test_demographics_not_enqueued_for_empty_beds(self):
        """Empty beds → no demographics runs."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run,
            setor="UTI A",
            leito="01",
            prontuario="",
            nome="DESOCUPADO",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        _add_filler_snapshots(captured_at=now, run=run, exclude={"UTI A"})
        result = process_census_snapshot()
        assert result["demographics_runs_enqueued"] == 0
        assert not IngestionRun.objects.filter(
            intent="demographics_only"
        ).exists()

    # --- Ward/bed sync tests (ward-from-census) ---

    def test_sync_ward_updates_active_admission(self):
        """Census processing updates ward/bed on active admission."""
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="14160147",
            name="JOSE MERCES",
        )
        # Create an active admission (no discharge date)
        admission = Admission.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key="adm-001",
            admission_date=timezone.now() - timezone.timedelta(days=5),
            discharge_date=None,
            ward="",
            bed="",
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        _add_filler_snapshots(captured_at=now, run=run, exclude={"UTI A"})

        process_census_snapshot()

        admission.refresh_from_db()
        assert admission.ward == "UTI A"
        assert admission.bed == "UG01A"

    def test_sync_ward_does_not_update_discharged_admission(self):
        """Census processing only updates admissions without discharge date."""
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="14160147",
            name="JOSE MERCES",
        )
        # Create a discharged admission
        Admission.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key="adm-001",
            admission_date=timezone.now() - timezone.timedelta(days=10),
            discharge_date=timezone.now() - timezone.timedelta(days=3),
            ward="OLD WARD",
            bed="OLD BED",
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        _add_filler_snapshots(captured_at=now, run=run, exclude={"UTI A"})

        process_census_snapshot()

        # Discharged admission should keep its original ward
        discharged = Admission.objects.get(source_admission_key="adm-001")
        assert discharged.ward == "OLD WARD"
        assert discharged.bed == "OLD BED"

    def test_sync_ward_no_admission_no_error(self):
        """Calling _sync_admission_ward_bed with no admissions is a no-op."""
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="999",
            name="NO ADMISSIONS",
        )
        # Should not raise
        _sync_admission_ward_bed(patient, "UTI", "L01")

    def test_sync_ward_empty_values_do_not_overwrite(self):
        """Empty census ward/bed should not overwrite existing values."""
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="14160147",
            name="JOSE MERCES",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key="adm-001",
            admission_date=timezone.now() - timezone.timedelta(days=5),
            discharge_date=None,
            ward="EXISTING",
            bed="B01",
        )

        _sync_admission_ward_bed(patient, "", "")

        admission.refresh_from_db()
        assert admission.ward == "EXISTING"
        assert admission.bed == "B01"

    def test_sync_ward_updates_most_recent_active_only(self):
        """Only the most recent active admission gets ward/bed from census."""
        patient = Patient.objects.create(
            source_system="tasy",
            patient_source_key="14160147",
            name="JOSE MERCES",
        )
        # Older active admission (should NOT be updated)
        old_adm = Admission.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key="adm-old",
            admission_date=timezone.now() - timezone.timedelta(days=30),
            discharge_date=None,
            ward="",
            bed="",
        )
        # More recent active admission (SHOULD be updated)
        new_adm = Admission.objects.create(
            patient=patient,
            source_system="tasy",
            source_admission_key="adm-new",
            admission_date=timezone.now() - timezone.timedelta(days=5),
            discharge_date=None,
            ward="",
            bed="",
        )
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run,
            setor="UTI B",
            leito="L02",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        _add_filler_snapshots(captured_at=now, run=run, exclude={"UTI B"})

        process_census_snapshot()

        old_adm.refresh_from_db()
        new_adm.refresh_from_db()
        # Older admission should NOT get updated
        assert old_adm.ward == ""
        assert old_adm.bed == ""
        # Most recent active admission SHOULD get updated
        assert new_adm.ward == "UTI B"
        assert new_adm.bed == "L02"


# ---------------------------------------------------------------------------
# GCEC-S2: completeness guard on snapshot processing
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestProcessCensusSnapshotCompletenessGuard:
    """Snapshot processing must refuse incomplete (<40 sectors) census data.

    The guard is defense in depth on top of the GCEC-S1 ``extract_census``
    gate: even if incomplete snapshots were already persisted, direct
    processing must not create a batch or enqueue patient runs from them.
    """

    def _make_run_with_sectors(self, sector_count: int) -> IngestionRun:
        """Create a census run with ``sector_count`` distinct sectors."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        _add_filler_snapshots(
            captured_at=now,
            run=run,
            exclude={"UTI A"},
            sector_count=sector_count,
        )
        return run

    def test_run_id_with_39_sectors_rejected(self):
        """Explicit run_id with 39 distinct sectors rejects processing."""
        run = self._make_run_with_sectors(sector_count=39)

        result = process_census_snapshot(run_id=run.pk)

        assert result["rejected"] is True
        assert result["rejection_reason"] == "incomplete_snapshot"
        assert result["sector_count"] == 39
        assert result["minimum_required_sectors"] == 40
        assert result["batch_id"] is None
        assert result["runs_enqueued"] == 0
        assert result["demographics_runs_enqueued"] == 0

    def test_rejected_run_id_creates_no_batch(self):
        """Rejected explicit-run path creates no CensusExecutionBatch."""
        run = self._make_run_with_sectors(sector_count=39)

        process_census_snapshot(run_id=run.pk)

        assert CensusExecutionBatch.objects.count() == 0

    def test_rejected_run_id_enqueues_no_patient_runs(self):
        """Rejected explicit-run path enqueues no admissions/demographics runs."""
        run = self._make_run_with_sectors(sector_count=39)

        process_census_snapshot(run_id=run.pk)

        assert IngestionRun.objects.filter(status="queued").count() == 0
        assert not IngestionRun.objects.filter(
            intent="admissions_only"
        ).exists()
        assert not IngestionRun.objects.filter(
            intent="demographics_only"
        ).exists()
        assert Patient.objects.count() == 0

    def test_latest_path_with_39_sectors_rejected(self):
        """Latest-snapshot path applies the same guard without run_id."""
        self._make_run_with_sectors(sector_count=39)

        result = process_census_snapshot()

        assert result["rejected"] is True
        assert result["sector_count"] == 39
        assert result["batch_id"] is None
        assert CensusExecutionBatch.objects.count() == 0

    def test_complete_snapshot_happy_path_unchanged(self):
        """A snapshot set with at least 40 sectors keeps the happy path."""
        run = self._make_run_with_sectors(sector_count=40)

        result = process_census_snapshot(run_id=run.pk)

        assert result["rejected"] is False
        assert result["patients_total"] == 1
        assert result["patients_new"] == 1
        assert result["batch_id"] is not None
        assert result["runs_enqueued"] == 1
        assert result["demographics_runs_enqueued"] == 1

    def test_command_reports_rejection_and_exits_nonzero(self):
        """Management command reports sector coverage and exits non-zero."""
        from io import StringIO

        from django.core.management import call_command

        run = self._make_run_with_sectors(sector_count=39)
        out = StringIO()
        err = StringIO()

        with pytest.raises(SystemExit) as exc_info:
            call_command(
                "process_census_snapshot",
                "--run-id",
                str(run.pk),
                stdout=out,
                stderr=err,
            )

        assert exc_info.value.code == 1
        message = err.getvalue()
        assert "rejected" in message.lower()
        assert "39" in message
        assert "40" in message
        assert "No batch created" in message
        assert CensusExecutionBatch.objects.count() == 0

    def test_command_succeeds_for_complete_snapshot(self):
        """Management command succeeds when the snapshot set is complete."""
        from io import StringIO

        from django.core.management import call_command

        run = self._make_run_with_sectors(sector_count=40)
        out = StringIO()
        err = StringIO()

        call_command(
            "process_census_snapshot",
            "--run-id",
            str(run.pk),
            stdout=out,
            stderr=err,
        )

        assert "Census snapshot processed" in out.getvalue()
        assert CensusExecutionBatch.objects.count() == 1


# ---------------------------------------------------------------------------
# SCOH-S3: occupancy materialization integration
# ---------------------------------------------------------------------------


def _scoh3_catalog(capture_date):
    """Create one standard capacity group (code 100, capacity 10)."""
    catalog = CapacityCatalogVersion.objects.create(
        effective_from=capture_date,
        source_reference="synthetic scoh-s3 test catalog",
        source_sha256=(f"{capture_date:%Y%m%d}" + "b" * 64)[:64],
        schema_version="1.0",
    )
    group = CapacityGroupDefinition.objects.create(
        catalog=catalog,
        stable_key="A",
        display_name="Group A",
        official_capacity=10,
        calculation_policy="standard",
    )
    CapacitySectorMembership.objects.create(
        catalog=catalog,
        group=group,
        source_code="100",
        configured_source_name="Sector A",
    )
    return catalog


@pytest.mark.django_db
class TestSCOH3OccupancyIntegration:
    """Materialization must run after the GCEC guard and before clinical effects."""

    def _complete_run(self, sector_count: int = 40, occupied_code: str = "100"):
        """Create a complete census run with one occupied patient."""
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
            setor_codigo=occupied_code,
        )
        _add_filler_snapshots(
            captured_at=now,
            run=run,
            exclude={"UTI A"},
            sector_count=sector_count,
        )
        return run

    def test_complete_explicit_post_activation_run_materializes_before_batch(self):
        _scoh3_catalog(timezone.localdate())
        run = self._complete_run()

        result = process_census_snapshot(run_id=run.pk)

        assert OccupancyMeasurement.objects.filter(census_run=run).exists()
        measurement = OccupancyMeasurement.objects.get(census_run=run)
        assert result.get("materialization_status") == "created"
        assert result.get("occupancy_measurement_id") == measurement.pk
        assert DailyOccupancySummary.objects.filter(
            local_date=timezone.localdate()
        ).exists()
        assert result.get("batch_id") is not None
        assert result["patients_total"] == 1

    def test_materialization_failure_leaves_zero_clinical_side_effects(self):
        from unittest import mock

        _scoh3_catalog(timezone.localdate())
        run = self._complete_run()

        with mock.patch(
            "apps.census.services.materialize_occupancy_measurement",
            create=True,
            side_effect=OccupancyMaterializationError(
                "synthetic structural failure"
            ),
        ):
            with pytest.raises(OccupancyMaterializationError):
                process_census_snapshot(run_id=run.pk)

        assert CensusExecutionBatch.objects.count() == 0
        assert IngestionRun.objects.filter(status="queued").count() == 0
        assert Patient.objects.count() == 0
        assert OccupancyMeasurement.objects.count() == 0
        assert DailyOccupancySummary.objects.count() == 0

    def test_complete_zero_occupied_run_still_gets_measurement_and_no_batch(self):
        _scoh3_catalog(timezone.localdate())
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        _add_filler_snapshots(captured_at=now, run=run, sector_count=40)

        result = process_census_snapshot(run_id=run.pk)

        assert OccupancyMeasurement.objects.filter(census_run=run).exists()
        assert DailyOccupancySummary.objects.filter(
            local_date=timezone.localdate()
        ).exists()
        assert result.get("materialization_status") == "created"
        assert result.get("batch_id") is None
        assert result["patients_total"] == 0

    def test_pre_activation_run_has_no_measurement_and_preserves_clinical_processing(self):
        run = self._complete_run()

        result = process_census_snapshot(run_id=run.pk)

        assert OccupancyMeasurement.objects.count() == 0
        assert DailyOccupancySummary.objects.count() == 0
        assert result.get("materialization_status") == "pre_activation"
        assert result.get("batch_id") is not None
        assert result["patients_total"] == 1

    def test_unknown_sector_does_not_block_clinical_processing(self):
        _scoh3_catalog(timezone.localdate())
        run = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
            setor_codigo="100",
        )
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run,
            setor="UNKNOWN SECTOR",
            leito="UG02A",
            prontuario="22222222",
            nome="PACIENTE DESCONHECIDO",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
            setor_codigo="999",
        )
        _add_filler_snapshots(
            captured_at=now,
            run=run,
            exclude={"UTI A", "UNKNOWN SECTOR"},
        )

        result = process_census_snapshot(run_id=run.pk)

        assert OccupancyMeasurement.objects.filter(census_run=run).exists()
        measurement = OccupancyMeasurement.objects.get(census_run=run)
        assert measurement.groups.filter(calculation_status="unmapped").exists()
        assert result.get("batch_id") is not None
        assert result["patients_total"] == 2

    def test_explicit_39_sector_run_never_invokes_materialization(self):
        _scoh3_catalog(timezone.localdate())
        run = self._complete_run(sector_count=39)

        result = process_census_snapshot(run_id=run.pk)

        assert result["rejected"] is True
        assert result.get("materialization_status") is None
        assert OccupancyMeasurement.objects.count() == 0
        assert DailyOccupancySummary.objects.count() == 0
        assert CensusExecutionBatch.objects.count() == 0

    def test_legacy_39_sector_path_never_invokes_materialization(self):
        _scoh3_catalog(timezone.localdate())
        self._complete_run(sector_count=39)

        result = process_census_snapshot()

        assert result["rejected"] is True
        assert result.get("materialization_status") is None
        assert OccupancyMeasurement.objects.count() == 0
        assert DailyOccupancySummary.objects.count() == 0
        assert CensusExecutionBatch.objects.count() == 0

    def test_legacy_latest_set_with_one_run_materializes_by_that_run(self):
        _scoh3_catalog(timezone.localdate())
        run = self._complete_run()

        result = process_census_snapshot()

        assert OccupancyMeasurement.objects.filter(census_run=run).exists()
        measurement = OccupancyMeasurement.objects.get(census_run=run)
        assert result.get("materialization_status") == "created"
        assert result.get("occupancy_measurement_id") == measurement.pk
        assert DailyOccupancySummary.objects.filter(
            local_date=timezone.localdate()
        ).exists()
        assert result.get("batch_id") is not None

    def test_missing_provenance_skips_history_and_preserves_legacy_processing(self):
        _scoh3_catalog(timezone.localdate())
        now = timezone.now()
        CensusSnapshot.objects.create(
            captured_at=now,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        _add_filler_snapshots(captured_at=now, exclude={"UTI A"})

        result = process_census_snapshot()

        assert result.get("materialization_status") == "missing_provenance"
        assert OccupancyMeasurement.objects.count() == 0
        assert DailyOccupancySummary.objects.count() == 0
        assert result.get("batch_id") is not None
        assert result["patients_total"] == 1

    def test_ambiguous_provenance_skips_history_and_preserves_legacy_processing(self):
        _scoh3_catalog(timezone.localdate())
        now = timezone.now()
        run_a = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        run_b = IngestionRun.objects.create(
            status="succeeded", intent="census_extraction"
        )
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run_a,
            setor="UTI A",
            leito="UG01A",
            prontuario="14160147",
            nome="JOSE AUGUSTO MERCES",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=now,
            ingestion_run=run_b,
            setor="UTI B",
            leito="UG01B",
            prontuario="22222222",
            nome="PACIENTE B",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        _add_filler_snapshots(
            captured_at=now, exclude={"UTI A", "UTI B"}
        )

        result = process_census_snapshot()

        assert result.get("materialization_status") == "missing_provenance"
        assert OccupancyMeasurement.objects.count() == 0
        assert DailyOccupancySummary.objects.count() == 0
        assert result.get("batch_id") is not None
        assert result["patients_total"] == 2
