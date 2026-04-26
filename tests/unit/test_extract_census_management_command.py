"""
Unit tests for extract_census command lifecycle metrics and stage recording
(Slice S4 / IRMD).

Tests cover success, timeout, non-zero exit, and unexpected exception paths,
using mocked subprocess.run and synthetic CSV fixture (no real Playwright).
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

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
        csv_rows = _synthetic_csv_rows()

        with tempfile.TemporaryDirectory() as real_tmp:
            tmp_path = Path(real_tmp)
            # Create a CSV inside the temp dir (simulating subprocess output)
            csv_path = tmp_path / "censo-20260426.csv"
            csv_path.write_text("setor,qrt_leito,prontuario,nome,esp\n")

            # Mock subprocess.run to return success
            fake_result = MagicMock()
            fake_result.returncode = 0

            # TemporaryDirectory() returns a context manager
            fake_tmp_ctx = MagicMock()
            fake_tmp_ctx.__enter__.return_value = str(real_tmp)

            with (
                patch("subprocess.run", return_value=fake_result),
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
                    "subprocess.run",
                    side_effect=subprocess.TimeoutExpired(
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
            assert "timed out" in run.error_message.lower()
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
                patch("subprocess.run", return_value=fake_result),
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
                    "subprocess.run",
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
        csv_rows = _synthetic_csv_rows()

        with tempfile.TemporaryDirectory() as real_tmp:
            tmp_path = Path(real_tmp)
            csv_path = tmp_path / "censo-20260426.csv"
            csv_path.write_text("setor,qrt_leito,prontuario,nome,esp\n")

            fake_result = MagicMock()
            fake_result.returncode = 0
            fake_tmp_ctx = MagicMock()
            fake_tmp_ctx.__enter__.return_value = str(real_tmp)

            with (
                patch("subprocess.run", return_value=fake_result),
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
