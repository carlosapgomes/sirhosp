"""RPSA-S10 unit tests for the daily integrity report command.

``report_admission_reconciliation_integrity`` is a thin daily wrapper: it
runs the SAME evaluation as ``check_ingestion_pipeline_health`` with the
default configuration, always renders the reconciliation block and exits
nonzero on violations. These tests prove the thinness (one shared
evaluation, zero duplicated logic), the aggregate-safe output, the
read-only behaviour and the absence of any source/queue/automation call.
All fixtures are synthetic.
"""

from __future__ import annotations

import io
from datetime import timedelta
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.ingestion import pipeline_health
from apps.ingestion.models import IngestionRun
from apps.ingestion.pipeline_health import HealthConfig, evaluate_pipeline_health

WRAPPER_MODULE = (
    "apps.ingestion.management.commands."
    "report_admission_reconciliation_integrity"
)
COMMAND_NAME = "report_admission_reconciliation_integrity"

pytestmark = pytest.mark.django_db

SENTINEL_PRONT = "PRONT-PRIV-S10-WRAP"
SENTINEL_NAME = "NOME-PRIV-S10-WRAP"


def _hours_ago(hours: int):
    return timezone.now() - timedelta(hours=hours)


def _run_wrapper(*args: str) -> str:
    out = io.StringIO()
    err = io.StringIO()
    call_command(COMMAND_NAME, *args, stdout=out, stderr=err)
    return out.getvalue()


def _run_wrapper_unhealthy(*args: str) -> tuple[str, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with pytest.raises(CommandError) as exc:
        call_command(COMMAND_NAME, *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue(), str(exc.value)


class TestThinDailyWrapper:
    def test_wrapper_uses_the_single_shared_evaluation(self):
        from apps.ingestion.management.commands import (
            report_admission_reconciliation_integrity as wrapper_module,
        )

        assert (
            wrapper_module.evaluate_pipeline_health
            is pipeline_health.evaluate_pipeline_health
        )

    def test_wrapper_runs_one_evaluation_with_default_config(self):
        with mock.patch(
            f"{WRAPPER_MODULE}.evaluate_pipeline_health",
            wraps=evaluate_pipeline_health,
        ) as mock_evaluate:
            _run_wrapper()
        mock_evaluate.assert_called_once()
        config = mock_evaluate.call_args.args[0]
        assert config == HealthConfig()
        assert config.missing_dates_max == 7
        assert config.backlog_age_max_hours == 48
        assert config.conflict_max_count == 0
        assert config.duplicate_max_count == 0

    def test_wrapper_renders_reconciliation_block_when_healthy(self):
        output = _run_wrapper()
        assert "admission reconciliation integrity: healthy=true" in output
        assert (
            "reconciliation_backlog: group=pending count=0 "
            "oldest_age_hours=none" in output
        )
        assert "reconciliation_duplicates: pairs=0" in output
        assert "reconciliation_census: open_outside_census=0" in output
        assert "extraction_coverage: dates=0 complete=0" in output

    def test_wrapper_exits_nonzero_on_violation(self):
        from apps.discharges.models import DischargeRecord
        from apps.patients.models import RECONCILIATION_STATUS_PENDING

        DischargeRecord.objects.create(
            prontuario=SENTINEL_PRONT,
            data_internacao="PRIV-DI-WRAP-1",
            saida_em=_hours_ago(72),
            nome=SENTINEL_NAME,
            reconciliation_status=RECONCILIATION_STATUS_PENDING,
        )
        out, _err, error = _run_wrapper_unhealthy()
        assert "admission reconciliation integrity: healthy=false" in out
        assert "group=pending count=1" in out
        assert "reconciliation_backlog_age=1" in error


class TestWrapperSafety:
    def test_wrapper_never_touches_source_queue_or_commands(self):
        from apps.discharges.models import DischargeRecord
        from apps.patients.models import RECONCILIATION_STATUS_CONFLICT

        DischargeRecord.objects.create(
            prontuario=SENTINEL_PRONT,
            data_internacao="PRIV-DI-WRAP-2",
            saida_em=_hours_ago(72),
            nome=SENTINEL_NAME,
            reconciliation_status=RECONCILIATION_STATUS_CONFLICT,
        )
        runs_before = IngestionRun.objects.count()
        with (
            mock.patch(
                "subprocess.Popen", side_effect=AssertionError("Popen called")
            ),
            mock.patch(
                "subprocess.run", side_effect=AssertionError("subprocess called")
            ),
            mock.patch(
                "urllib.request.urlopen", side_effect=AssertionError("urllib called")
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
            _run_wrapper_unhealthy()
        assert IngestionRun.objects.count() == runs_before

    def test_wrapper_is_read_only(self):
        from apps.deaths.models import DeathRecord
        from apps.discharges.models import DischargeRecord
        from apps.patients.models import (
            RECONCILIATION_STATUS_AMBIGUOUS,
            RECONCILIATION_STATUS_PENDING,
        )

        DischargeRecord.objects.create(
            prontuario=SENTINEL_PRONT,
            data_internacao="PRIV-DI-WRAP-3",
            saida_em=_hours_ago(72),
            nome=SENTINEL_NAME,
            reconciliation_status=RECONCILIATION_STATUS_PENDING,
        )
        DeathRecord.objects.create(
            date=timezone.localdate(),
            prontuario=SENTINEL_PRONT,
            nome=SENTINEL_NAME,
            reconciliation_status=RECONCILIATION_STATUS_AMBIGUOUS,
        )
        before = (
            DischargeRecord.objects.count(),
            DeathRecord.objects.count(),
            IngestionRun.objects.count(),
        )
        _run_wrapper_unhealthy()
        after = (
            DischargeRecord.objects.count(),
            DeathRecord.objects.count(),
            IngestionRun.objects.count(),
        )
        assert before == after

    def test_wrapper_output_is_identity_safe(self):
        from apps.discharges.models import DischargeRecord
        from apps.patients.models import RECONCILIATION_STATUS_PENDING

        DischargeRecord.objects.create(
            prontuario=SENTINEL_PRONT,
            data_internacao="PRIV-DI-WRAP-4",
            saida_em=_hours_ago(72),
            nome=SENTINEL_NAME,
            reconciliation_status=RECONCILIATION_STATUS_PENDING,
        )
        out, _err, error = _run_wrapper_unhealthy()
        combined = out + error
        assert SENTINEL_PRONT not in combined
        assert SENTINEL_NAME not in combined
