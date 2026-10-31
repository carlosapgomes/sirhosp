"""ECD-S2 integration: producer -> temporary artifacts -> command -> PostgreSQL.

The real producer loop runs against synthetic XLSX workbooks with controlled
browser/source boundaries, writes the real temporary CSV and version-1 summary,
and the real management command validates and persists them in isolated
PostgreSQL. Only those external acquisition edges and the subprocess runner are
controlled.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from apps.census.models import (
    CensusSnapshot,
    OccupancyMeasurement,
)
from apps.census.services import process_census_snapshot
from apps.ingestion.models import CensusExecutionBatch, IngestionRun
from apps.patients.models import Admission, Patient, StaleAdmissionCase
from tests.census_artifacts import SUMMARY_FILENAME
from tests.unit.test_extract_census_publication import (
    _run_producer,
    _sectors,
)

SENTINEL = "SENTINEL-ECD-S2-PATIENT"


def _run_command_on(
    directory: Path,
    *,
    returncode: int = 0,
    expect_exit: bool = True,
) -> IngestionRun:
    fake_result = MagicMock()
    fake_result.returncode = returncode
    fake_result.stderr = ""
    fake_tmp_ctx = MagicMock()
    fake_tmp_ctx.__enter__.return_value = str(directory)

    with (
        patch(
            "apps.census.management.commands.extract_census.run_subprocess",
            return_value=fake_result,
        ),
        patch("tempfile.TemporaryDirectory", return_value=fake_tmp_ctx),
    ):
        if expect_exit:
            with pytest.raises(SystemExit):
                call_command("extract_census")
        else:
            call_command("extract_census")

    return IngestionRun.objects.filter(intent="census_extraction").latest("pk")


def _downstream_counts() -> dict[str, int]:
    return {
        "snapshots": CensusSnapshot.objects.count(),
        "batches": CensusExecutionBatch.objects.count(),
        "patients": Patient.objects.count(),
        "admissions": Admission.objects.count(),
        "occupancy": OccupancyMeasurement.objects.count(),
        "stale_cases": StaleAdmissionCase.objects.count(),
        "patient_queues": IngestionRun.objects.filter(
            intent__in=("admissions_only", "demographics_only")
        ).count(),
    }


@pytest.mark.django_db
class TestProducerCommandHandoff:
    def test_complete_synthetic_run_is_accepted_by_the_real_consumer(
        self, monkeypatch, tmp_path, capsys
    ):
        exit_code = _run_producer(
            monkeypatch,
            tmp_path,
            sectors=_sectors(41),
            sentinel=SENTINEL,
        )
        assert exit_code == 0

        run = _run_command_on(tmp_path, expect_exit=False)
        captured = capsys.readouterr()

        assert run.status == "succeeded"
        assert CensusSnapshot.objects.filter(ingestion_run=run).count() == 82
        csv_files = list(tmp_path.glob("censo-*.csv"))
        assert len(csv_files) == 1
        published = sorted(
            path.name
            for path in tmp_path.iterdir()
            if path.suffix in {".csv", ".json", ".png", ".html"}
        )
        assert published == sorted([csv_files[0].name, SUMMARY_FILENAME])
        assert list(tmp_path.glob("*.tmp")) == []
        assert list(tmp_path.glob(".*.tmp")) == []

        persistence = run.stage_metrics.get(stage_name="census_persistence")
        assert persistence.details_json["rows_emitted"] == 82
        assert persistence.details_json["sectors_processed"] == 41
        assert persistence.details_json["scope_complete"] is True
        assert persistence.details_json["sector_count"] == 41

        assert SENTINEL not in captured.out
        assert SENTINEL not in captured.err
        assert SENTINEL not in str(persistence.details_json)
        sentinel_snapshots = CensusSnapshot.objects.filter(
            ingestion_run=run, prontuario=SENTINEL
        )
        assert sentinel_snapshots.count() == 41

    def test_partial_producer_failure_keeps_prior_accepted_census(
        self, monkeypatch, tmp_path
    ):
        baseline_dir = tmp_path / "baseline"
        baseline_dir.mkdir()
        assert (
            _run_producer(
                monkeypatch,
                baseline_dir,
                sectors=_sectors(41),
            )
            == 0
        )
        baseline_run = _run_command_on(baseline_dir, expect_exit=False)
        assert baseline_run.status == "succeeded"
        baseline_count = CensusSnapshot.objects.count()
        assert baseline_count == 82

        failed_dir = tmp_path / "failed"
        failed_dir.mkdir()
        assert (
            _run_producer(
                monkeypatch,
                failed_dir,
                sectors=_sectors(41),
                fail_on="SETOR 041",
            )
            == 1
        )
        assert list(failed_dir.glob("censo-*.csv")) == []

        # The subprocess "lies" with exit code zero; the artifact gate still
        # rejects the run.
        rejected_run = _run_command_on(failed_dir, returncode=0)

        assert rejected_run.status == "failed"
        assert CensusSnapshot.objects.filter(
            ingestion_run=rejected_run
        ).count() == 0
        assert CensusSnapshot.objects.count() == baseline_count
        assert (
            CensusSnapshot.objects.order_by("-captured_at")
            .first()
            .ingestion_run_id
            == baseline_run.pk
        )
        assert not IngestionRun.objects.filter(
            intent="census_extraction",
            status="succeeded",
            pk=rejected_run.pk,
        ).exists()

        result = process_census_snapshot(run_id=rejected_run.pk)
        assert result["rejected"] is True
        assert result["batch_id"] is None
        assert result["runs_enqueued"] == 0
        assert CensusSnapshot.objects.count() == baseline_count

    def test_failure_after_snapshot_insertion_rolls_back_new_set(
        self, monkeypatch, tmp_path
    ):
        baseline_dir = tmp_path / "baseline"
        baseline_dir.mkdir()
        assert (
            _run_producer(
                monkeypatch,
                baseline_dir,
                sectors=_sectors(41),
            )
            == 0
        )
        baseline_run = _run_command_on(baseline_dir, expect_exit=False)
        assert baseline_run.status == "succeeded"
        process_census_snapshot(run_id=baseline_run.pk)
        baseline_counts = _downstream_counts()

        rollback_dir = tmp_path / "rollback"
        rollback_dir.mkdir()
        assert (
            _run_producer(
                monkeypatch,
                rollback_dir,
                sectors=_sectors(42),
            )
            == 0
        )

        injected = "SENTINEL-INJECTED-PUBLICATION-FAILURE"
        original_save = IngestionRun.save

        def failing_save(self, *args, **kwargs):
            if self.status == "succeeded":
                raise RuntimeError(injected)
            return original_save(self, *args, **kwargs)

        with patch.object(IngestionRun, "save", failing_save):
            _run_command_on(rollback_dir)

        rejected_run = IngestionRun.objects.filter(
            intent="census_extraction"
        ).latest("pk")
        assert rejected_run.status == "failed"
        assert injected not in rejected_run.error_message
        assert CensusSnapshot.objects.filter(
            ingestion_run=rejected_run
        ).count() == 0

        after_counts = _downstream_counts()
        assert after_counts == baseline_counts
        assert CensusSnapshot.objects.filter(
            ingestion_run=baseline_run
        ).count() == 82
        assert (
            CensusSnapshot.objects.order_by("-captured_at")
            .first()
            .ingestion_run_id
            == baseline_run.pk
        )

        result = process_census_snapshot(run_id=rejected_run.pk)
        assert result["rejected"] is True
        assert result["batch_id"] is None
        assert _downstream_counts() == baseline_counts
