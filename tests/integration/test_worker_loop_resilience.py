"""Resilience tests for worker continuous loop startup behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.db.utils import ProgrammingError


@pytest.mark.django_db
def test_worker_loop_retries_when_schema_not_ready(capsys):
    """Loop mode should retry (not crash) when ingestion table is not ready yet."""
    failing_qs = MagicMock()
    failing_qs.count.side_effect = ProgrammingError(
        'relation "ingestion_ingestionrun" does not exist'
    )

    ready_qs = MagicMock()
    ready_qs.count.return_value = 0
    ready_qs.iterator.return_value = iter([])

    with (
        patch(
            "apps.ingestion.management.commands.process_ingestion_runs.IngestionRun.objects.filter",
            side_effect=[failing_qs, ready_qs],
        ),
        patch(
            "apps.ingestion.management.commands.process_ingestion_runs.time.sleep",
            side_effect=[None, KeyboardInterrupt],
        ),
        patch("signal.signal"),
    ):
        with pytest.raises(KeyboardInterrupt):
            call_command("process_ingestion_runs", loop=True, sleep_seconds=1)

    captured = capsys.readouterr()
    assert "Worker startup check failed" in captured.err
    assert "Retrying in 1s" in captured.err
    assert "No queued runs" in captured.out
