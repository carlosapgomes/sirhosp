"""Regression tests for realistic connector operational failures (Slice S5).

Covers scenarios where the subprocess exits with code 0 (success) but the
output is unusable — a realistic failure mode when Playwright crashes
mid-extraction or the source system times out silently.

These complement test_worker_lifecycle.py which tests failures at the
extractor mock level.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from apps.ingestion.models import IngestionRun


@pytest.mark.django_db
class TestConnectorOutputCorruptionRegression:
    """Regression: subprocess succeeds but output file is corrupted.

    Real-world scenario: Playwright navigates partially, source system
    returns incomplete HTML, or disk fills up mid-write. The subprocess
    exits 0 but the JSON output is broken.
    """

    def _queue_run(self) -> IngestionRun:
        return IngestionRun.objects.create(
            status="queued",
            max_attempts=1,
            parameters_json={
                "patient_record": "REG_CORRUP",
                "start_date": "2026-04-01",
                "end_date": "2026-04-10",
            },
        )

    def test_truncated_json_causes_run_failure(self):
        """RED: subprocess writes truncated JSON → run must become failed.

        Simulates: path2.py exits 0 but writes '{[{' (truncated output).
        Expected: InvalidJsonError → IngestionRun.status = 'failed'.
        """
        run = self._queue_run()

        def fake_subprocess_run(cmd, **kwargs):
            """Simulate path2 exiting 0 but writing truncated JSON."""
            json_idx = cmd.index("--json-output") + 1
            output_path = Path(cmd[json_idx])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            # Truncated JSON — realistic when Playwright crashes mid-write
            output_path.write_text('[{"createdAt": "2026-04-', encoding="utf-8")
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.run_subprocess",
            side_effect=fake_subprocess_run,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "failed", (
            f"Expected 'failed', got '{run.status}'. "
            "Truncated JSON from extractor should fail the run."
        )
        assert run.error_message, "Failed run must have an error message."
        assert run.finished_at is not None, "Failed run must have finished_at."

    def test_json_is_string_instead_of_array_causes_run_failure(
        self, capsys, caplog
    ):
        """D5: subprocess writes a JSON string (not array) to the
        ``--admissions-output`` path → run must fail with
        ``failure_reason=invalid_payload``.

        D16: the injected sentinel must be absent from DB, stdout, stderr,
        and every log record.
        """
        import logging

        sentinel = "SENSITIVE_INVALID_PAYLOAD"
        run = self._queue_run()

        def fake_subprocess_run(cmd, **kwargs):
            adm_idx = cmd.index("--admissions-output") + 1
            output_path = Path(cmd[adm_idx])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                f'"{sentinel}"', encoding="utf-8"
            )
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.run_subprocess",
            side_effect=fake_subprocess_run,
        ), caplog.at_level(logging.WARNING):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "invalid_payload"
        assert run.timed_out is False
        from apps.ingestion.models import IngestionRunStageMetric

        attempt = run.attempts.order_by("-attempt_number").first()
        # Sentinel absent from all DB error surfaces.
        for blob in [
            run.error_message or "",
            attempt.error_message if attempt else "",
        ]:
            assert sentinel not in blob
        for metric in IngestionRunStageMetric.objects.filter(run=run):
            assert sentinel not in str(metric.details_json or {})
        # D16: sentinel absent from stdout, stderr, and logs.
        captured = capsys.readouterr()
        for stream in (captured.out, captured.err):
            assert sentinel not in stream
        for record in caplog.records:
            assert sentinel not in record.getMessage()

    def test_missing_output_file_causes_run_failure(self):
        """RED: subprocess exits 0 but doesn't create output file → run must fail.

        Simulates: path2.py exits 0 silently without writing output.
        Expected: FileNotFoundError → InvalidJsonError → IngestionRun.status = 'failed'.
        """
        run = self._queue_run()

        def fake_subprocess_run(cmd, **kwargs):
            # Don't write anything — simulate silent failure
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch(
            "apps.ingestion.extractors.playwright_extractor.run_subprocess",
            side_effect=fake_subprocess_run,
        ):
            call_command("process_ingestion_runs")

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.finished_at is not None
