"""
Unit tests for extract_census command lifecycle metrics and stage recording
(Slice S4 / IRMD).

Tests cover success, timeout, non-zero exit, and unexpected exception paths,
using mocked subprocess.run and synthetic CSV fixture (no real Playwright).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from apps.ingestion.extractors.subprocess_utils import SubprocessTimeoutError
from apps.ingestion.models import IngestionRun


def _synthetic_csv_rows() -> list[dict]:
    """Return minimal synthetic rows matching parse_census_csv contract."""
    return [
        {
            "setor": "UTI A",
            "leito": "UG01A",
            "prontuario": "14160147",
            "nome": "JOSE MERCES",
            "especialidade": "NEF",
            "bed_status": "occupied",
        },
        {
            "setor": "UTI A",
            "leito": "UG02B",
            "prontuario": "",
            "nome": "DESOCUPADO",
            "especialidade": "",
            "bed_status": "empty",
        },
    ]


@pytest.mark.django_db
class TestExtractCensusLifecycleMetrics:
    """Verify lifecycle timestamps, failure categorisation, and stage metrics
    for every execution path of the extract_census management command."""

    # ------------------------------------------------------------------
    # Success path
    # ------------------------------------------------------------------

    def test_success_flow_records_lifecycle_and_stages(self):
        """Happy path: subprocess succeeds, CSV is parsed, metrics persisted."""
        # Arrange -----------------------------------------------------------
        csv_rows = _synthetic_rows_n_sectors(45, rows_per_sector=2)

        with tempfile.TemporaryDirectory() as real_tmp:
            tmp_path = Path(real_tmp)
            # Create a CSV inside the temp dir (simulating subprocess output)
            csv_path = tmp_path / "censo-20260426.csv"
            csv_path.write_text("setor_codigo,setor,qrt_leito,prontuario,nome,esp,dt_mvt,alta,origem\n")

            # Mock subprocess.run to return success
            fake_result = MagicMock()
            fake_result.returncode = 0

            # TemporaryDirectory() returns a context manager
            fake_tmp_ctx = MagicMock()
            fake_tmp_ctx.__enter__.return_value = str(real_tmp)

            with (
                patch(
                    "apps.census.management.commands.extract_census.run_subprocess",
                    return_value=fake_result,
                ),
                patch(
                    "apps.census.management.commands.extract_census.parse_census_csv",
                    return_value=csv_rows,
                ),
                patch(
                    "pathlib.Path.exists",
                    return_value=True,
                ),
                patch(
                    "tempfile.TemporaryDirectory",
                    return_value=fake_tmp_ctx,
                ),
            ):
                # Act -------------------------------------------------------
                call_command("extract_census")

            # Assert --------------------------------------------------------
            run = IngestionRun.objects.first()
            assert run is not None
            assert run.status == "succeeded"
            assert run.intent == "census_extraction"
            assert run.processing_started_at is not None
            assert run.finished_at is not None
            assert run.finished_at >= run.processing_started_at
            assert run.failure_reason == ""
            assert run.timed_out is False
            assert run.error_message == ""

            # Stages
            stages = list(
                run.stage_metrics.order_by("started_at").values(
                    "stage_name", "status"
                )
            )
            assert len(stages) >= 2, f"Expected >=2 stages, got {stages}"

            extraction = [
                s for s in stages if s["stage_name"] == "census_extraction"
            ]
            persistence = [
                s for s in stages if s["stage_name"] == "census_persistence"
            ]
            assert len(extraction) == 1
            assert extraction[0]["status"] == "succeeded"
            assert len(persistence) == 1
            assert persistence[0]["status"] == "succeeded"

    # ------------------------------------------------------------------
    # Timeout path
    # ------------------------------------------------------------------

    def test_subprocess_timeout_classifies_as_timeout(self):
        """TimeoutExpired → failure_reason='timeout', timed_out=True."""
        # Arrange -----------------------------------------------------------
        with tempfile.TemporaryDirectory() as real_tmp:
            fake_tmp_ctx = MagicMock()
            fake_tmp_ctx.__enter__.return_value = str(real_tmp)
            with (
                patch(
                    "apps.census.management.commands.extract_census.run_subprocess",
                    side_effect=SubprocessTimeoutError(
                        cmd=["python", "script.py"], timeout=1800,
                    ),
                ),
                patch(
                    "pathlib.Path.exists",
                    return_value=True,
                ),
                patch(
                    "tempfile.TemporaryDirectory",
                    return_value=fake_tmp_ctx,
                ),
            ):
                # Act -------------------------------------------------------
                with pytest.raises(SystemExit):
                    call_command("extract_census")

            # Assert --------------------------------------------------------
            run = IngestionRun.objects.first()
            assert run is not None
            assert run.status == "failed"
            assert run.failure_reason == "timeout"
            assert run.timed_out is True
            assert run.error_message
            assert run.finished_at is not None

            # At least the extraction stage should be recorded as failed
            stages = list(
                run.stage_metrics.filter(stage_name="census_extraction")
            )
            assert len(stages) == 1
            assert stages[0].status == "failed"

    # ------------------------------------------------------------------
    # Non-zero exit path
    # ------------------------------------------------------------------

    def test_subprocess_non_zero_exit_classifies_as_source_unavailable(self):
        """Non-zero exit code → failure_reason='source_unavailable'."""
        # Arrange -----------------------------------------------------------
        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stderr = "Connection refused"

        with tempfile.TemporaryDirectory() as real_tmp:
            fake_tmp_ctx = MagicMock()
            fake_tmp_ctx.__enter__.return_value = str(real_tmp)
            with (
                patch(
                    "apps.census.management.commands.extract_census.run_subprocess",
                    return_value=fake_result,
                ),
                patch("pathlib.Path.exists", return_value=True),
                patch(
                    "tempfile.TemporaryDirectory",
                    return_value=fake_tmp_ctx,
                ),
            ):
                # Act -------------------------------------------------------
                with pytest.raises(SystemExit):
                    call_command("extract_census")

            # Assert --------------------------------------------------------
            run = IngestionRun.objects.first()
            assert run is not None
            assert run.status == "failed"
            assert run.failure_reason == "source_unavailable"
            assert run.timed_out is False
            assert "Exit code 1" in run.error_message
            assert run.finished_at is not None

    # ------------------------------------------------------------------
    # Unexpected exception path
    # ------------------------------------------------------------------

    def test_unexpected_exception_classifies_as_unexpected(self):
        """Non-subprocess exception → failure_reason='unexpected_exception'."""
        # Arrange -----------------------------------------------------------
        with tempfile.TemporaryDirectory() as real_tmp:
            fake_tmp_ctx = MagicMock()
            fake_tmp_ctx.__enter__.return_value = str(real_tmp)
            with (
                patch(
                    "apps.census.management.commands.extract_census.run_subprocess",
                    side_effect=RuntimeError("Boom!"),
                ),
                patch("pathlib.Path.exists", return_value=True),
                patch(
                    "tempfile.TemporaryDirectory",
                    return_value=fake_tmp_ctx,
                ),
            ):
                # Act -------------------------------------------------------
                with pytest.raises(SystemExit):
                    call_command("extract_census")

            # Assert --------------------------------------------------------
            run = IngestionRun.objects.first()
            assert run is not None
            assert run.status == "failed"
            assert run.failure_reason == "unexpected_exception"
            assert run.timed_out is False
            assert "Boom!" in run.error_message

    # ------------------------------------------------------------------
    # Stage metric ordering
    # ------------------------------------------------------------------

    def test_stage_finished_before_run_finished(self):
        """Stages must be completed before (or at same time as) run finish."""
        csv_rows = _synthetic_rows_n_sectors(45, rows_per_sector=2)

        with tempfile.TemporaryDirectory() as real_tmp:
            tmp_path = Path(real_tmp)
            csv_path = tmp_path / "censo-20260426.csv"
            csv_path.write_text("setor_codigo,setor,qrt_leito,prontuario,nome,esp,dt_mvt,alta,origem\n")

            fake_result = MagicMock()
            fake_result.returncode = 0
            fake_tmp_ctx = MagicMock()
            fake_tmp_ctx.__enter__.return_value = str(real_tmp)

            with (
                patch(
                    "apps.census.management.commands.extract_census.run_subprocess",
                    return_value=fake_result,
                ),
                patch(
                    "apps.census.management.commands.extract_census.parse_census_csv",
                    return_value=csv_rows,
                ),
                patch("pathlib.Path.exists", return_value=True),
                patch(
                    "tempfile.TemporaryDirectory",
                    return_value=fake_tmp_ctx,
                ),
            ):
                call_command("extract_census")

            run = IngestionRun.objects.first()
            assert run is not None

            for stage in run.stage_metrics.all():
                assert (
                    stage.finished_at <= run.finished_at
                ), (
                    f"Stage '{stage.stage_name}' finished at {stage.finished_at} "
                    f"but run finished at {run.finished_at}"
                )


# ---------------------------------------------------------------------------
# Completeness gate tests (GCEC-S1)
# ---------------------------------------------------------------------------


def _synthetic_rows_n_sectors(num_sectors: int, rows_per_sector: int = 2) -> list[dict]:
    """Generate synthetic census rows for N distinct sectors.

    Each sector has ``rows_per_sector`` rows: one occupied and one empty.
    No real patient data is used.
    """
    rows: list[dict] = []
    for i in range(1, num_sectors + 1):
        sector = f"SETOR {i:03d}"
        rows.append({
            "setor": sector,
            "leito": f"LEITO{i:03d}A",
            "prontuario": f"PRONT{i:05d}",
            "nome": f"PACIENTE {i}",
            "especialidade": "CLI",
            "bed_status": "occupied",
            "setor_codigo": str(i),
            "data_internacao": "01/01/2026",
            "tempo_internacao": 10,
            "data_movimentacao": "",
            "tipo_alta": "",
            "origem": "",
        })
        rows.append({
            "setor": sector,
            "leito": f"LEITO{i:03d}B",
            "prontuario": "",
            "nome": "DESOCUPADO",
            "especialidade": "",
            "bed_status": "empty",
            "setor_codigo": str(i),
            "data_internacao": "",
            "tempo_internacao": None,
            "data_movimentacao": "",
            "tipo_alta": "",
            "origem": "",
        })
    return rows


@pytest.mark.django_db
class TestExtractCensusCompletenessGate:
    """Verify the completeness gate rejects CSVs with < 40 distinct sectors."""

    # ------------------------------------------------------------------
    # Helper to set up mocks for completeness tests
    # ------------------------------------------------------------------

    def _run_command(self, csv_rows: list[dict], expect_failure: bool = True):
        """Run extract_census with mocked subprocess and parse_census_csv.

        Args:
            csv_rows: Rows that parse_census_csv should return.
            expect_failure: If True, expect SystemExit; if False, run cleanly.
        """
        with tempfile.TemporaryDirectory() as real_tmp:
            tmp_path = Path(real_tmp)
            csv_path = tmp_path / "censo-20260426.csv"
            csv_path.write_text(
                "setor_codigo,setor,qrt_leito,prontuario,nome,esp,dt_mvt,alta,origem\n"
            )

            fake_result = MagicMock()
            fake_result.returncode = 0
            fake_tmp_ctx = MagicMock()
            fake_tmp_ctx.__enter__.return_value = str(real_tmp)

            with (
                patch(
                    "apps.census.management.commands.extract_census.run_subprocess",
                    return_value=fake_result,
                ),
                patch(
                    "apps.census.management.commands.extract_census.parse_census_csv",
                    return_value=csv_rows,
                ),
                patch("pathlib.Path.exists", return_value=True),
                patch(
                    "tempfile.TemporaryDirectory",
                    return_value=fake_tmp_ctx,
                ),
            ):
                if expect_failure:
                    with pytest.raises(SystemExit):
                        call_command("extract_census")
                else:
                    call_command("extract_census")

    # ------------------------------------------------------------------
    # Scenario 1: 39 sectors fails
    # ------------------------------------------------------------------

    def test_39_sectors_rejected(self):
        """39 distinct sectors must fail the command."""
        rows = _synthetic_rows_n_sectors(39)
        self._run_command(rows, expect_failure=True)

    # ------------------------------------------------------------------
    # Scenario 2: zero CensusSnapshot rows persisted after failure
    # ------------------------------------------------------------------

    def test_39_sectors_creates_zero_snapshots(self):
        """After rejection, no CensusSnapshot rows should exist."""
        rows = _synthetic_rows_n_sectors(39)
        self._run_command(rows, expect_failure=True)
        from apps.census.models import CensusSnapshot
        assert CensusSnapshot.objects.count() == 0

    # ------------------------------------------------------------------
    # Scenario 3: IngestionRun marked failed with invalid_payload
    # ------------------------------------------------------------------

    def test_39_sectors_marks_run_failed(self):
        """After rejection, IngestionRun.status='failed' with invalid_payload."""
        rows = _synthetic_rows_n_sectors(39)
        self._run_command(rows, expect_failure=True)

        run = IngestionRun.objects.first()
        assert run is not None
        assert run.status == "failed"
        assert run.failure_reason == "invalid_payload"
        assert run.timed_out is False

    # ------------------------------------------------------------------
    # Scenario 4: stage metrics include aggregate values (no PII)
    # ------------------------------------------------------------------

    def test_39_sectors_records_aggregate_metrics(self):
        """Stage metrics for rejected extraction include safe aggregate values."""
        rows = _synthetic_rows_n_sectors(39)
        self._run_command(rows, expect_failure=True)

        run = IngestionRun.objects.first()
        assert run is not None

        # Find persistence stage metric
        pers_metrics = run.stage_metrics.filter(
            stage_name="census_persistence"
        )
        assert pers_metrics.count() == 1
        pm = pers_metrics.first()
        assert pm.status == "failed"

        details = pm.details_json
        assert details.get("sector_count") == 39
        assert details.get("row_count") == len(rows)
        assert details.get("minimum_required_sectors") == 40
        assert "completeness_status" in details

        # Ensure no PII in details
        flat = str(details).lower()
        assert "pront" not in flat
        assert "paciente" not in flat

    # ------------------------------------------------------------------
    # Scenario 5: 40+ sectors still succeeds
    # ------------------------------------------------------------------

    def test_40_sectors_accepted(self):
        """40 distinct sectors must pass the completeness gate."""
        rows = _synthetic_rows_n_sectors(40)
        self._run_command(rows, expect_failure=False)

        run = IngestionRun.objects.first()
        assert run is not None
        assert run.status == "succeeded", (
            f"Expected succeeded, got status={run.status}"
        )

    def test_45_sectors_accepted(self):
        """45 distinct sectors must pass the completeness gate."""
        rows = _synthetic_rows_n_sectors(45)
        self._run_command(rows, expect_failure=False)

        run = IngestionRun.objects.first()
        assert run is not None
        assert run.status == "succeeded"
