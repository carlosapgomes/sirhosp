"""Unit tests for RPSA-S7 confirmed-zero discharge extraction.

Covers the slice contract matrix:

- non-empty first attempt: single source invocation, ``attempt_count=1``;
- empty/missing XLS plus empty confirmation: confirmed-zero success with
  durable ``zero_confirmed``/``attempt_count`` stage metadata;
- empty/missing XLS plus failed/timeout confirmation: structured,
  credential-safe ``zero_unconfirmed`` failure, prior evidence untouched,
  no aggregate refresh and never ``DailyDischargeCount=0`` from absence;
- empty/missing XLS plus non-empty confirmation: confirmation rows
  processed normally (``attempt_count=2``);
- initial failure/timeout: existing failure semantics, no confirmation
  attempt (maximum two source invocations per service call, proven by
  mock call counting).

The subprocess layer is mocked; each invocation writes its canned output
into the fresh ``--output-dir`` the service passes on the command line,
proving the confirmation runs against a fresh temporary directory. All
fixtures are synthetic.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from apps.discharges.models import DailyDischargeCount, DischargeRecord
from apps.ingestion.extractors.subprocess_utils import SubprocessTimeoutError
from apps.patients.models import (
    RECONCILIATION_STATUS_PENDING,
    Admission,
    Patient,
    ReconciliationEvent,
)

TZ_LOCAL = ZoneInfo("America/Bahia")

XLS_HEADER = (
    "ID", "Prontuario", "Nome", "Internacao", "Equipe",
    "Esp", "Alta Medica", "Local", "Saida",
)

SERVICE_PATH = "apps.discharges.extraction_service"


# ---------------------------------------------------------------------------
# Synthetic XLS helpers
# ---------------------------------------------------------------------------


def _xls_data_rows(prontuarios: list[str]) -> list[tuple]:
    """Build synthetic data rows for the given prontuario list."""
    rows: list[tuple] = []
    for i, prontuario in enumerate(prontuarios):
        rows.append(
            (
                i,
                float(prontuario),
                f"PACIENTE {prontuario}",
                "20/05/2026",
                f"Eq{i}",
                "CLI",
                "01/06/2026 10:00",
                "L:UN01H",
                "01/06/2026 12:00",
            )
        )
    return rows


def _write_xls(dir_path: Path, rows: list[tuple]) -> Path:
    import openpyxl  # noqa: PLC0415

    filepath = dir_path / "altas-01-06-2026-001.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(str(filepath))
    wb.close()
    return filepath


def _make_subprocess_outputs(outputs: list):
    """Build a ``run_subprocess`` side effect with per-call canned output.

    Each element of *outputs* describes one source invocation:

    - ``None``: subprocess succeeds but writes no XLS (empty output);
    - ``list[tuple]``: subprocess writes one XLS carrying these rows
      (without the header);
    - ``{"returncode": N, "stderr": "..."}``: subprocess exits non-zero;
    - ``{"timeout": True}``: subprocess times out;
    - ``{"crash": True}``: subprocess layer raises unexpectedly.

    The side effect records every command line it received so tests can
    count source invocations (mock call-count proof) and inspect the
    fresh ``--output-dir`` per attempt.
    """
    calls: list[list[str]] = []

    def _side_effect(cmd, timeout=None, check=False, env=None, **kwargs):
        # RPSA-S7A: the service now also passes env= (scoped child
        # environment); the fake tolerates it — transport assertions live
        # in tests/unit/test_historical_extractor_credential_transport.py.
        calls.append(list(cmd))
        spec = outputs[len(calls) - 1] if len(calls) <= len(outputs) else None
        out_dir = Path(cmd[cmd.index("--output-dir") + 1])
        proc = MagicMock()
        proc.stdout = ""
        proc.stderr = ""
        proc.returncode = 0
        if isinstance(spec, dict):
            if spec.get("timeout"):
                raise SubprocessTimeoutError(
                    cmd=list(cmd),
                    timeout=timeout if timeout is not None else 600,
                    output="",
                    stderr="Timed out",
                )
            if spec.get("crash"):
                raise RuntimeError("automation crashed")
            proc.returncode = spec.get("returncode", 1)
            proc.stderr = spec.get("stderr", "")
            return proc
        if spec is not None:
            _write_xls(out_dir, [XLS_HEADER, *spec])
        return proc

    _side_effect.calls = calls  # type: ignore[attr-defined]
    return _side_effect


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_credentials():
    with patch(f"{SERVICE_PATH}.resolve_source_credentials") as mock:
        mock.return_value.url = "https://example.com"
        mock.return_value.username = "admin"
        mock.return_value.password = "secret"
        yield mock


@pytest.fixture
def mock_refresh():
    """Patch the aggregate refresh so tests can assert call counts/order."""
    with patch(f"{SERVICE_PATH}.call_command") as mock:
        yield mock


def _make_patient(key: str) -> Patient:
    return Patient.objects.create(
        patient_source_key=key,
        source_system="tasy",
        name=f"PACIENTE {key}",
    )


def _make_admission(patient: Patient, key: str, start: str) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=datetime.fromisoformat(start).replace(tzinfo=TZ_LOCAL),
    )


# =========================================================================
# Contract matrix
# =========================================================================


@pytest.mark.django_db
class TestContractMatrix:
    """One test per contract-matrix row with mock call-count proof."""

    def test_nonempty_first_attempt_single_invocation_no_confirmation(
        self, mock_credentials, mock_refresh,
    ):
        """Row 1: non-empty success is never confirmed; attempt_count=1."""
        from apps.discharges.extraction_service import run_discharge_extraction

        outputs = [_xls_data_rows(["300001", "300002"])]
        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs(outputs),
        ) as mock_subproc:
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        # Mock call-count proof: exactly ONE source invocation.
        assert len(mock_subproc.side_effect.calls) == 1
        assert result.attempt_count == 1
        assert result.zero_confirmed is False
        assert result.metrics["attempt_count"] == 1
        assert result.metrics["zero_confirmed"] is False
        assert result.metrics["total_records"] == 2
        assert DischargeRecord.objects.count() == 2
        mock_refresh.assert_called_once()

    def test_empty_then_empty_confirms_zero(
        self, mock_credentials, mock_refresh,
    ):
        """Row 2: two independent empties confirm zero (success, 2 calls)."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs([None, None]),
        ) as mock_subproc:
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        # Mock call-count proof: exactly TWO invocations, never three.
        assert len(mock_subproc.side_effect.calls) == 2
        assert result.zero_confirmed is True
        assert result.attempt_count == 2
        assert result.metrics["zero_confirmed"] is True
        assert result.metrics["attempt_count"] == 2
        assert result.metrics["total_records"] == 0

        # Refresh still runs exactly once on confirmed success.
        mock_refresh.assert_called_once()
        mock_refresh.assert_called_with("refresh_daily_discharge_counts")

        # No aggregate row and no evidence row may come from absence.
        assert DailyDischargeCount.objects.count() == 0
        assert DischargeRecord.objects.count() == 0

        # Durable metadata: re-query the run's stage metrics fresh.
        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        ext_stage = run.stage_metrics.get(stage_name="discharge_extraction")
        assert ext_stage.status == "succeeded"
        assert ext_stage.details_json["zero_confirmed"] is True
        assert ext_stage.details_json["attempt_count"] == 2
        persist_stage = run.stage_metrics.get(stage_name="discharge_persistence")
        assert persist_stage.details_json["zero_confirmed"] is True
        assert persist_stage.details_json["attempt_count"] == 2

    def test_empty_then_nonempty_processes_confirmation_rows(
        self, mock_credentials, mock_refresh,
    ):
        """Row 4: non-empty confirmation is processed normally (2 calls)."""
        from apps.discharges.extraction_service import run_discharge_extraction

        confirmation_rows = _xls_data_rows(["300010"])
        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs([None, confirmation_rows]),
        ) as mock_subproc:
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        assert len(mock_subproc.side_effect.calls) == 2
        assert result.attempt_count == 2
        assert result.zero_confirmed is False
        assert result.metrics["total_records"] == 1
        record = DischargeRecord.objects.get()
        assert record.prontuario == "300010"
        assert record.saida_em == datetime(2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL)
        mock_refresh.assert_called_once()

    def test_empty_then_failed_confirmation_is_zero_unconfirmed(
        self, mock_credentials, mock_refresh,
    ):
        """Row 3 (failure): unconfirmed zero is a structured failure."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs(
                [None, {"returncode": 1, "stderr": "source unavailable"}]
            ),
        ) as mock_subproc:
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is False
        assert result.failure_reason == "zero_unconfirmed"
        assert len(mock_subproc.side_effect.calls) == 2
        assert result.attempt_count == 2
        assert result.zero_confirmed is False

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.status == "failed"
        assert run.failure_reason == "zero_unconfirmed"

        # Failed extraction never triggers the aggregate refresh.
        mock_refresh.assert_not_called()
        # No aggregate row and no evidence write from absence.
        assert DailyDischargeCount.objects.count() == 0
        assert DischargeRecord.objects.count() == 0

        ext_stage = run.stage_metrics.get(stage_name="discharge_extraction")
        assert ext_stage.status == "failed"
        assert ext_stage.details_json["zero_confirmed"] is False
        assert ext_stage.details_json["attempt_count"] == 2

    def test_empty_then_timeout_confirmation_is_zero_unconfirmed(
        self, mock_credentials, mock_refresh,
    ):
        """Row 3 (timeout): a timed-out confirmation stays failed."""
        from apps.discharges.extraction_service import run_discharge_extraction

        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs([None, {"timeout": True}]),
        ) as mock_subproc:
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is False
        assert result.failure_reason == "zero_unconfirmed"
        assert len(mock_subproc.side_effect.calls) == 2
        mock_refresh.assert_not_called()
        assert DailyDischargeCount.objects.count() == 0

    def test_header_only_xls_on_both_attempts_confirms_zero(
        self, mock_credentials, mock_refresh,
    ):
        """Zero parseable rows is empty: header-only XLS twice confirms."""
        from apps.discharges.extraction_service import run_discharge_extraction

        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs([[], []]),
        ) as mock_subproc:
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        assert len(mock_subproc.side_effect.calls) == 2
        assert result.zero_confirmed is True
        assert result.attempt_count == 2
        mock_refresh.assert_called_once()

    def test_initial_failure_skips_confirmation(
        self, mock_credentials, mock_refresh,
    ):
        """Row 5: initial failure keeps existing semantics, 1 call only."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs(
                [{"returncode": 1, "stderr": "boom"}]
            ),
        ) as mock_subproc:
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is False
        assert result.failure_reason == "source_unavailable"
        # No confirmation after a failed first attempt.
        assert len(mock_subproc.side_effect.calls) == 1
        assert result.attempt_count == 1
        assert result.zero_confirmed is False
        mock_refresh.assert_not_called()

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        ext_stage = run.stage_metrics.get(stage_name="discharge_extraction")
        assert ext_stage.status == "failed"
        assert ext_stage.details_json["attempt_count"] == 1
        assert ext_stage.details_json["zero_confirmed"] is False

    def test_initial_timeout_skips_confirmation(
        self, mock_credentials, mock_refresh,
    ):
        """Row 5 (timeout): no confirmation attempt after a timeout."""
        from apps.discharges.extraction_service import run_discharge_extraction

        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs([{"timeout": True}]),
        ) as mock_subproc:
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is False
        assert result.failure_reason == "timeout"
        assert len(mock_subproc.side_effect.calls) == 1
        mock_refresh.assert_not_called()


# =========================================================================
# Evidence, aggregate and metadata safety
# =========================================================================


@pytest.mark.django_db
class TestEvidenceAndAggregateSafety:
    """Prior evidence survives; absence never writes aggregate zeros."""

    def test_unconfirmed_zero_never_writes_daily_count_zero(
        self, mock_credentials, mock_refresh,
    ):
        """A pre-seeded aggregate row survives an unconfirmed zero intact."""
        from apps.discharges.extraction_service import run_discharge_extraction

        seeded = DailyDischargeCount.objects.create(
            date=datetime(2026, 6, 1).date(), count=7,
        )

        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs(
                [None, {"returncode": 1, "stderr": "down"}]
            ),
        ):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is False
        mock_refresh.assert_not_called()
        assert DailyDischargeCount.objects.count() == 1
        seeded.refresh_from_db()
        assert seeded.count == 7

    def test_prior_evidence_untouched_on_unconfirmed_zero(
        self, mock_credentials, mock_refresh,
    ):
        """Unconfirmed zero must not overwrite or delete prior evidence."""
        from apps.discharges.extraction_service import run_discharge_extraction

        record = DischargeRecord.objects.create(
            prontuario="424242",
            nome="PACIENTE 424242",
            data_internacao="20/05/2026",
            saida_em=datetime(2026, 5, 30, 9, 0, tzinfo=TZ_LOCAL),
            reconciliation_status=RECONCILIATION_STATUS_PENDING,
        )

        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs(
                [None, {"crash": True}]
            ),
        ):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is False
        assert result.failure_reason == "zero_unconfirmed"
        record.refresh_from_db()
        assert record.saida_em == datetime(2026, 5, 30, 9, 0, tzinfo=TZ_LOCAL)
        assert record.reconciliation_status == RECONCILIATION_STATUS_PENDING
        assert ReconciliationEvent.objects.count() == 0

    def test_prior_evidence_untouched_before_confirmed_zero(
        self, mock_credentials, mock_refresh,
    ):
        """Confirmed zero also leaves prior evidence exactly as it was."""
        from apps.discharges.extraction_service import run_discharge_extraction

        record = DischargeRecord.objects.create(
            prontuario="424243",
            nome="PACIENTE 424243",
            data_internacao="20/05/2026",
            saida_em=datetime(2026, 5, 30, 9, 0, tzinfo=TZ_LOCAL),
        )

        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs([None, None]),
        ):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        record.refresh_from_db()
        assert record.saida_em == datetime(2026, 5, 30, 9, 0, tzinfo=TZ_LOCAL)
        assert DischargeRecord.objects.count() == 1


# =========================================================================
# Refresh ordering and durable metadata
# =========================================================================


@pytest.mark.django_db
class TestRefreshOrderingAndDurability:
    """Refresh runs after reconciliation; metadata survives re-query."""

    def test_refresh_invoked_after_reconciliation_completes(
        self, mock_credentials, mock_refresh,
    ):
        """At refresh-call time the confirmation row is already reconciled."""
        from apps.discharges.extraction_service import run_discharge_extraction

        patient = _make_patient("900001")
        admission = _make_admission(patient, "ADM-900001", "2026-05-20T08:00:00")

        observed: dict = {}

        def _record_refresh_state(command, *args, **kwargs):
            admission.refresh_from_db()
            observed["discharge_date"] = admission.discharge_date
            observed["events"] = ReconciliationEvent.objects.count()

        mock_refresh.side_effect = _record_refresh_state

        confirmation_rows = _xls_data_rows(["900001"])
        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs([None, confirmation_rows]),
        ):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        mock_refresh.assert_called_once()
        mock_refresh.assert_called_with("refresh_daily_discharge_counts")
        # Reconciliation had completed before the refresh was invoked.
        assert observed["discharge_date"] == datetime(
            2026, 6, 1, 12, 0, tzinfo=TZ_LOCAL
        )
        assert observed["events"] == 1

    def test_confirmed_zero_refresh_called_exactly_once(
        self, mock_credentials, mock_refresh,
    ):
        """Confirmed zero also refreshes exactly once (included case)."""
        from apps.discharges.extraction_service import run_discharge_extraction

        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs([None, None]),
        ):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        assert result.zero_confirmed is True
        mock_refresh.assert_called_once()

    def test_durable_metadata_survives_new_query(
        self, mock_credentials, mock_refresh,
    ):
        """Stage metadata persists beyond the service call (fresh re-query)."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun, IngestionRunStageMetric

        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs([None, None]),
        ):
            result = run_discharge_extraction(date="01/06/2026")

        # Independent fresh queries by run id, not in-memory objects.
        run_id = result.ingestion_run_id
        metrics = IngestionRunStageMetric.objects.filter(run_id=run_id)
        ext_details = metrics.get(stage_name="discharge_extraction").details_json
        persist_details = metrics.get(
            stage_name="discharge_persistence"
        ).details_json
        run = IngestionRun.objects.get(pk=run_id)

        assert ext_details["zero_confirmed"] is True
        assert ext_details["attempt_count"] == 2
        assert persist_details["zero_confirmed"] is True
        assert persist_details["attempt_count"] == 2
        assert run.status == "succeeded"
        assert result.metrics["zero_confirmed"] is True

    def test_metrics_carry_reconciliation_counters_alongside_zero_metadata(
        self, mock_credentials, mock_refresh,
    ):
        """RPSA-S2 counters and RPSA-S7 metadata coexist in details_json."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        patient = _make_patient("900002")
        _make_admission(patient, "ADM-900002", "2026-05-20T08:00:00")

        confirmation_rows = _xls_data_rows(["900002"])
        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs([None, confirmation_rows]),
        ):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is True
        assert result.metrics["reconciliation_reconciled"] == 1
        assert result.metrics["zero_confirmed"] is False
        assert result.metrics["attempt_count"] == 2

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        persist_details = run.stage_metrics.get(
            stage_name="discharge_persistence"
        ).details_json
        assert persist_details["reconciliation_reconciled"] == 1
        assert persist_details["zero_confirmed"] is False
        assert persist_details["attempt_count"] == 2


# =========================================================================
# Credential safety
# =========================================================================


@pytest.mark.django_db
class TestCredentialSafety:
    """Zero-confirmation failure metadata stays credential-safe."""

    def test_unconfirmed_zero_metadata_has_no_credentials(
        self, mock_credentials, mock_refresh,
    ):
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs(
                [None, {"returncode": 1, "stderr": "password=secret leaked"}]
            ),
        ):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is False
        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        dumped = json.dumps(
            {
                "result_error": result.error_message,
                "stages": [
                    s.details_json for s in run.stage_metrics.all()
                ],
                "run_error": run.error_message,
            }
        )
        assert "secret" not in dumped
        assert "admin" not in dumped
        assert "example.com" not in dumped
        # The structured reason is present and readable.
        assert result.failure_reason == "zero_unconfirmed"


# =========================================================================
# RPSA-S7 deferred P2s (landed in RPSA-S7A)
# =========================================================================


@pytest.mark.django_db
class TestDeferredP2Metadata:
    """RPSA-S7 deferred P2 observability gaps, closed tests-first.

    - failure-stage ``discharge_persistence`` details_json carries
      ``attempt_count``/``zero_confirmed`` alongside the error;
    - a confirmation attempt that times out marks the run
      ``timed_out=True`` exactly like the first-attempt timeout path,
      keeping ``confirmation_failure_reason="timeout"`` structured and
      credential-safe.
    """

    def test_persistence_failure_stage_carries_attempt_count_and_zero_confirmed(
        self, mock_credentials, mock_refresh,
    ):
        """A failed persistence stage keeps the attempt metadata durable."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs(
                [_xls_data_rows(["777001"])]
            ),
        ), patch(
            f"{SERVICE_PATH}._persist_discharge_records",
            side_effect=RuntimeError("persistence boom"),
        ):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is False
        mock_refresh.assert_not_called()

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        stage = run.stage_metrics.get(
            stage_name="discharge_persistence", status="failed",
        )
        assert stage.details_json["error"]
        assert stage.details_json["attempt_count"] == 1
        assert stage.details_json["zero_confirmed"] is False

    def test_confirmation_timeout_marks_run_timed_out(
        self, mock_credentials, mock_refresh,
    ):
        """Confirmation timeout propagates ``timed_out=True`` to the run."""
        from apps.discharges.extraction_service import run_discharge_extraction
        from apps.ingestion.models import IngestionRun

        with patch(
            f"{SERVICE_PATH}.run_subprocess",
            side_effect=_make_subprocess_outputs([None, {"timeout": True}]),
        ):
            result = run_discharge_extraction(date="01/06/2026")

        assert result.success is False
        assert result.failure_reason == "zero_unconfirmed"
        mock_refresh.assert_not_called()

        run = IngestionRun.objects.get(pk=result.ingestion_run_id)
        assert run.status == "failed"
        # Deferred P2: propagate the confirmation timeout to the run
        # exactly like the first-attempt timeout path.
        assert run.timed_out is True
        assert run.failure_reason == "zero_unconfirmed"

        stage = run.stage_metrics.get(
            stage_name="discharge_extraction", status="failed",
        )
        assert stage.details_json["confirmation_failure_reason"] == "timeout"
        dumped = json.dumps(
            {
                "result_error": result.error_message,
                "stage": stage.details_json,
                "run_error": run.error_message,
            }
        )
        assert "secret" not in dumped
        assert "admin" not in dumped
