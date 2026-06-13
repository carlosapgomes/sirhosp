"""Tests for the recover_historical_data management command.

Slice C3-S4 requirements (tasks.md 4.1-4.2):
- Tests for CLI argument parsing: --date, --start-date/--end-date, ambiguous
  input, --extractor, --dry-run, --fail-fast.
- Tests for deterministic stdout/stderr summary and exit status.
- Tests ensuring no raw exception text or credential values appear in output.

All orchestration logic is mocked via ``execute_recovery_plan``. No
extractor services, Playwright subprocesses, or management commands
are actually invoked.
"""

from __future__ import annotations

from datetime import date
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.ingestion.historical_recovery import (
    DEFAULT_EXTRACTOR_ORDER,
    RecoveryRunResult,
    RecoveryStepResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(
    date_label: str,
    extractor: str,
    success: bool = True,
    skipped: bool = False,
    failure_reason: str = "",
    error_message: str = "",
) -> RecoveryStepResult:
    day = date(2026, 6, 1) if date_label == "01/06/2026" else date(2026, 6, 2)
    return RecoveryStepResult(
        date=day,
        date_label=date_label,
        extractor=extractor,
        success=success,
        extraction_type=f"{extractor}_extraction",
        metrics={} if skipped else {"total_records": 5},
        skipped=skipped,
        failure_reason=failure_reason,
        error_message=error_message,
        ingestion_run_id=None if skipped else 42,
    )


def _make_success_result() -> RecoveryRunResult:
    sd = date(2026, 6, 1)
    steps = [_make_step("01/06/2026", e) for e in DEFAULT_EXTRACTOR_ORDER]
    return RecoveryRunResult(start_date=sd, end_date=sd, steps=steps)


def _make_failure_result() -> RecoveryRunResult:
    sd = date(2026, 6, 1)
    steps = [
        _make_step("01/06/2026", "discharges", success=True),
        _make_step("01/06/2026", "admissions", success=False,
                    failure_reason="timeout", error_message="Timed out"),
        _make_step("01/06/2026", "deaths", success=True),
        _make_step("01/06/2026", "official_census", success=False,
                    failure_reason="source_unavailable",
                    error_message="Source unavailable"),
    ]
    return RecoveryRunResult(start_date=sd, end_date=sd, steps=steps)


_EXEC_PATH = (
    "apps.ingestion.management.commands.recover_historical_data.execute_recovery_plan"
)


# ---------------------------------------------------------------------------
# Single date
# ---------------------------------------------------------------------------


class TestSingleDateArg:
    """Command accepts --date DD/MM/AAAA for single-day recovery."""

    def test_single_date_runs_successfully(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                stdout=out,
            )
            output = out.getvalue()
            assert "01/06/2026" in output
            assert "Succeeded" in output or "succeeded" in output.lower()

    def test_single_date_passes_correct_plan(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "15/01/2026",
                stdout=out,
            )
            _ = out.getvalue()
            args, _kwargs = mock_exec.call_args
            plan = args[0]
            assert plan.dates == [date(2026, 1, 15)]
            assert plan.extractors == DEFAULT_EXTRACTOR_ORDER
            assert plan.dry_run is False
            assert plan.fail_fast is False


# ---------------------------------------------------------------------------
# Date range
# ---------------------------------------------------------------------------


class TestDateRangeArg:
    """Command accepts --start-date / --end-date for inclusive range."""

    def test_date_range_runs_successfully(self):
        with patch(_EXEC_PATH) as mock_exec:
            result = RecoveryRunResult(
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 3),
                steps=[
                    _make_step("01/06/2026", e) for e in DEFAULT_EXTRACTOR_ORDER
                ] + [
                    _make_step("02/06/2026", e) for e in DEFAULT_EXTRACTOR_ORDER
                ] + [
                    _make_step("03/06/2026", e) for e in DEFAULT_EXTRACTOR_ORDER
                ],
            )
            mock_exec.return_value = result
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--start-date", "01/06/2026",
                "--end-date", "03/06/2026",
                stdout=out,
            )
            output = out.getvalue()
            assert "01/06/2026" in output
            assert "03/06/2026" in output
            assert "Succeeded" in output or "succeeded" in output.lower()

    def test_date_range_passes_correct_plan(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--start-date", "01/06/2026",
                "--end-date", "03/06/2026",
                stdout=out,
            )
            _ = out.getvalue()
            args, _kwargs = mock_exec.call_args
            plan = args[0]
            assert plan.dates == [
                date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3),
            ]


# ---------------------------------------------------------------------------
# Ambiguous input
# ---------------------------------------------------------------------------


class TestAmbiguousInput:
    """Command rejects combined --date and --start-date/--end-date."""

    def test_rejects_date_with_start_date(self):
        out = StringIO()
        with pytest.raises(CommandError):
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                "--start-date", "01/06/2026",
                stderr=out,
            )

    def test_rejects_date_with_end_date(self):
        out = StringIO()
        with pytest.raises(CommandError):
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                "--end-date", "02/06/2026",
                stderr=out,
            )

    def test_rejects_missing_all_date_args(self):
        out = StringIO()
        with pytest.raises(CommandError):
            call_command(
                "recover_historical_data",
                stderr=out,
            )

    def test_rejects_start_without_end(self):
        out = StringIO()
        with pytest.raises(CommandError):
            call_command(
                "recover_historical_data",
                "--start-date", "01/06/2026",
                stderr=out,
            )

    def test_rejects_end_without_start(self):
        out = StringIO()
        with pytest.raises(CommandError):
            call_command(
                "recover_historical_data",
                "--end-date", "01/06/2026",
                stderr=out,
            )

    def test_rejects_end_before_start(self):
        out = StringIO()
        with pytest.raises(CommandError):
            call_command(
                "recover_historical_data",
                "--start-date", "05/06/2026",
                "--end-date", "01/06/2026",
                stderr=out,
            )

    def test_rejects_invalid_date_format(self):
        out = StringIO()
        with pytest.raises(CommandError):
            call_command(
                "recover_historical_data",
                "--date", "2026-06-01",
                stderr=out,
            )


# ---------------------------------------------------------------------------
# Extractor selection
# ---------------------------------------------------------------------------


class TestExtractorSelection:
    """Repeatable --extractor option selects extractor subset."""

    def test_single_extractor(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = RecoveryRunResult(
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 1),
                steps=[_make_step("01/06/2026", "deaths")],
            )
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                "--extractor", "deaths",
                stdout=out,
            )
            _ = out.getvalue()
            args, _kwargs = mock_exec.call_args
            plan = args[0]
            assert plan.extractors == ["deaths"]

    def test_multiple_extractors_sorted_in_default_order(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = RecoveryRunResult(
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 1),
                steps=[
                    _make_step("01/06/2026", "admissions"),
                    _make_step("01/06/2026", "official_census"),
                ],
            )
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                "--extractor", "admissions",
                "--extractor", "official_census",
                stdout=out,
            )
            _ = out.getvalue()
            args, _kwargs = mock_exec.call_args
            plan = args[0]
            assert plan.extractors == ["admissions", "official_census"]

    def test_unknown_extractor_fails(self):
        out = StringIO()
        with pytest.raises(CommandError):
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                "--extractor", "bogus",
                stderr=out,
            )


# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------


class TestDryRunMode:
    """--dry-run must not call real services."""

    def test_dry_run_flag_passed_to_plan(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                "--dry-run",
                stdout=out,
            )
            _ = out.getvalue()
            args, _kwargs = mock_exec.call_args
            plan = args[0]
            assert plan.dry_run is True

    def test_dry_run_output_indicates_dry_run(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = RecoveryRunResult(
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 1),
                steps=[
                    RecoveryStepResult(
                        date=date(2026, 6, 1),
                        date_label="01/06/2026",
                        extractor="discharges",
                        success=True,
                        extraction_type="discharge_extraction",
                        skipped=True,
                    ),
                ],
            )
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                "--dry-run",
                stdout=out,
            )
            output = out.getvalue()
            assert "DRY RUN" in output.upper() or "dry" in output.lower()

    def test_dry_run_exits_successfully(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            try:
                call_command(
                    "recover_historical_data",
                    "--date", "01/06/2026",
                    "--dry-run",
                    stdout=out,
                )
            except SystemExit:
                pytest.fail("Dry-run should not raise SystemExit")


# ---------------------------------------------------------------------------
# Fail-fast mode
# ---------------------------------------------------------------------------


class TestFailFast:
    """--fail-fast propagates to the plan."""

    def test_fail_fast_flag_passed_to_plan(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                "--fail-fast",
                stdout=out,
            )
            _ = out.getvalue()
            args, _kwargs = mock_exec.call_args
            plan = args[0]
            assert plan.fail_fast is True


# ---------------------------------------------------------------------------
# Exit status — success
# ---------------------------------------------------------------------------


class TestExitSuccess:
    """Command exits zero when all steps succeed."""

    def test_all_successful_exit_zero(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            try:
                call_command(
                    "recover_historical_data",
                    "--date", "01/06/2026",
                    stdout=out,
                )
            except SystemExit as exc:
                pytest.fail(f"Unexpected SystemExit({exc.code})")


# ---------------------------------------------------------------------------
# Exit status — failure
# ---------------------------------------------------------------------------


class TestExitFailure:
    """Command exits non-zero when steps fail."""

    def test_failure_exit_nonzero(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_failure_result()
            with pytest.raises(SystemExit) as exc_info:
                call_command(
                    "recover_historical_data",
                    "--date", "01/06/2026",
                )
            assert exc_info.value.code != 0

    def test_failure_prints_summary_with_failed_count(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_failure_result()
            out = StringIO()
            with pytest.raises(SystemExit):
                call_command(
                    "recover_historical_data",
                    "--date", "01/06/2026",
                    stdout=out,
                )
            output = out.getvalue()
            assert "failed" in output.lower()


# ---------------------------------------------------------------------------
# Output determinism and safety
# ---------------------------------------------------------------------------


class TestOutputDeterminism:
    """Operator output must be deterministic and safe."""

    def test_output_contains_extractor_names(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                stdout=out,
            )
            output = out.getvalue()
            for extractor in DEFAULT_EXTRACTOR_ORDER:
                assert extractor in output.lower()

    def test_output_contains_date_labels(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                stdout=out,
            )
            output = out.getvalue()
            assert "01/06/2026" in output

    def test_output_summary_format(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                stdout=out,
            )
            output = out.getvalue()
            assert "Days:" in output or "days" in output.lower()
            assert "Steps:" in output

    def test_output_no_raw_exceptions(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_failure_result()
            out = StringIO()
            with pytest.raises(SystemExit):
                call_command(
                    "recover_historical_data",
                    "--date", "01/06/2026",
                    stdout=out,
                )
            output = out.getvalue()
            assert "Traceback" not in output
            assert "RuntimeError" not in output

    def test_output_no_credentials(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_failure_result()
            out = StringIO()
            with pytest.raises(SystemExit):
                call_command(
                    "recover_historical_data",
                    "--date", "01/06/2026",
                    stdout=out,
                )
            output = out.getvalue()
            assert "password" not in output.lower()
            assert "SECRET" not in output.upper()

    def test_output_header_contains_range_and_extractors_info(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                stdout=out,
            )
            output = out.getvalue()
            assert "01/06/2026" in output
            assert "Extractors:" in output or "extractors" in output.lower()


# ---------------------------------------------------------------------------
# Default extractor order
# ---------------------------------------------------------------------------


class TestDefaultExtractorOrderInCommand:
    """Default recovery includes all four extractors."""

    def test_default_extractors_all_four(self):
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                stdout=out,
            )
            _ = out.getvalue()
            args, _kwargs = mock_exec.call_args
            plan = args[0]
            assert plan.extractors == DEFAULT_EXTRACTOR_ORDER


# ---------------------------------------------------------------------------
# Optional dry-run end-to-end: exercises command + orchestrator without
# mocking execute_recovery_plan. Mocks individual service functions to
# prove no extractor is called during dry-run.
# ---------------------------------------------------------------------------


class TestDryRunEndToEnd:
    """
    Exercises the command and orchestrator together in dry-run mode.

    Unlike other command tests that mock ``execute_recovery_plan``, this
    test lets the real command and orchestrator run, while patching the
    four extractor service functions so they raise if called. The
    assertion proves the dry-run completes successfully without invoking
    any extractor service.

    This validates the wiring between the command and orchestrator is
    correct without relying on Playwright automation or real credentials.
    """

    # Patch paths for each service function (the module where the function
    # lives, not where it is imported).
    _DISCHARGE_PATH = (
        "apps.discharges.extraction_service.run_discharge_extraction"
    )
    _ADMISSION_PATH = "apps.admissions.services.run_admission_extraction"
    _DEATH_PATH = "apps.deaths.services.run_death_extraction"
    _CENSUS_PATH = "apps.census.services.run_official_census_extraction"

    @patch(_DISCHARGE_PATH, side_effect=RuntimeError("should not be called"))
    @patch(_ADMISSION_PATH, side_effect=RuntimeError("should not be called"))
    @patch(_DEATH_PATH, side_effect=RuntimeError("should not be called"))
    @patch(_CENSUS_PATH, side_effect=RuntimeError("should not be called"))
    def test_dry_run_exercises_command_and_orchestrator_without_calling_services(
        self,
        mock_census: object,
        mock_death: object,
        mock_admission: object,
        mock_discharge: object,
    ):
        """Dry-run with real orchestrator wiring — no service called."""
        out = StringIO()
        call_command(
            "recover_historical_data",
            "--date", "01/06/2026",
            "--dry-run",
            stdout=out,
        )
        output = out.getvalue()

        # Command ran to completion and dry-run label is present.
        assert "DRY RUN" in output.upper()
        assert "01/06/2026" in output
        assert "discharges" in output
        assert "admissions" in output
        assert "deaths" in output
        assert "official_census" in output

    @patch(_DISCHARGE_PATH, side_effect=RuntimeError("should not be called"))
    @patch(_ADMISSION_PATH, side_effect=RuntimeError("should not be called"))
    @patch(_DEATH_PATH, side_effect=RuntimeError("should not be called"))
    @patch(_CENSUS_PATH, side_effect=RuntimeError("should not be called"))
    def test_dry_run_exits_successfully_with_real_orchestrator(
        self,
        mock_census: object,
        mock_death: object,
        mock_admission: object,
        mock_discharge: object,
    ):
        """Dry-run via real orchestrator does not call any service."""
        out = StringIO()
        try:
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                "--dry-run",
                stdout=out,
            )
        except SystemExit as exc:
            pytest.fail(f"Dry-run should not cause SystemExit, got {exc.code}")

        output = out.getvalue()
        assert "Skipped" in output or "SKIPPED" in output or "skipped" in output.lower()
        assert "Failed: 0" in output or "failed: 0" in output.lower()

    @patch(_DISCHARGE_PATH, side_effect=RuntimeError("should not be called"))
    @patch(_ADMISSION_PATH, side_effect=RuntimeError("should not be called"))
    @patch(_DEATH_PATH, side_effect=RuntimeError("should not be called"))
    @patch(_CENSUS_PATH, side_effect=RuntimeError("should not be called"))
    def test_dry_run_range_exercises_orchestrator(
        self,
        mock_census: object,
        mock_death: object,
        mock_admission: object,
        mock_discharge: object,
    ):
        """Dry-run with date range via real orchestrator."""
        out = StringIO()
        try:
            call_command(
                "recover_historical_data",
                "--start-date", "01/06/2026",
                "--end-date", "03/06/2026",
                "--dry-run",
                stdout=out,
            )
        except SystemExit as exc:
            pytest.fail(f"Dry-run range should not cause SystemExit, got {exc.code}")

        output = out.getvalue()
        assert "DRY RUN" in output.upper()
        assert "01/06/2026" in output
        assert "03/06/2026" in output


# ---------------------------------------------------------------------------
# Retry argument tests
# ---------------------------------------------------------------------------


class TestRetryArgument:
    """--max-retries argument parsing and validation."""

    def test_default_max_retries_is_three(self):
        """Default max_retries should be 3."""
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                stdout=out,
            )
            _ = out.getvalue()
            args, _kwargs = mock_exec.call_args
            plan = args[0]
            assert plan.max_retries == 3

    def test_custom_max_retries_passed_to_plan(self):
        """Explicit --max-retries value is passed to the plan."""
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                "--max-retries", "5",
                stdout=out,
            )
            _ = out.getvalue()
            args, _kwargs = mock_exec.call_args
            plan = args[0]
            assert plan.max_retries == 5

    def test_max_retries_zero_disables_retries(self):
        """--max-retries 0 disables retries."""
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                "--max-retries", "0",
                stdout=out,
            )
            _ = out.getvalue()
            args, _kwargs = mock_exec.call_args
            plan = args[0]
            assert plan.max_retries == 0

    def test_negative_max_retries_fails(self):
        """Negative --max-retries fails before extraction."""
        with pytest.raises(CommandError) as exc_info:
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                "--max-retries", "-1",
            )
        assert "non-negative" in str(exc_info.value).lower()


class TestRetryCommandOutput:
    """Command output shows retry rounds when they occur."""

    def test_retry_rounds_in_output_when_retries_used(self):
        """Output includes 'Retry rounds' line when retries happened."""
        result = RecoveryRunResult(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            steps=[
                RecoveryStepResult(
                    date=date(2026, 6, 1),
                    date_label="01/06/2026",
                    extractor="discharges",
                    success=True,
                    extraction_type="discharge_extraction",
                    metrics={"total_records": 5},
                ),
            ],
            retry_rounds_used=2,
            retry_attempts=2,
        )
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = result
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                stdout=out,
            )
            output = out.getvalue()
            assert "Retry rounds" in output
            assert "2 attempt(s)" in output

    def test_no_retry_output_when_no_retries(self):
        """Output does not mention retries when none occurred."""
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = _make_success_result()
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                stdout=out,
            )
            output = out.getvalue()
            assert "Retry" not in output

    def test_retry_output_with_successful_retries_exits_zero(self):
        """With retries that succeed, the command should exit zero."""
        result = RecoveryRunResult(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            steps=[
                RecoveryStepResult(
                    date=date(2026, 6, 1),
                    date_label="01/06/2026",
                    extractor="discharges",
                    success=True,
                    extraction_type="discharge_extraction",
                    metrics={"total_records": 5},
                ),
            ],
            retry_rounds_used=1,
            retry_attempts=1,
        )
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = result
            out = StringIO()
            try:
                call_command(
                    "recover_historical_data",
                    "--date", "01/06/2026",
                    stdout=out,
                )
            except SystemExit as exc:
                pytest.fail(
                    f"Successful retries should not cause SystemExit, got {exc.code}"
                )

    def test_retry_output_with_failure_after_retries_exits_nonzero(self):
        """With retries exhausted, the command exits non-zero."""
        result = RecoveryRunResult(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            steps=[
                RecoveryStepResult(
                    date=date(2026, 6, 1),
                    date_label="01/06/2026",
                    extractor="discharges",
                    success=False,
                    extraction_type="discharge_extraction",
                    failure_reason="timeout",
                    error_message="Timed out",
                ),
            ],
            retry_rounds_used=3,
            retry_attempts=3,
        )
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = result
            with pytest.raises(SystemExit) as exc_info:
                call_command(
                    "recover_historical_data",
                    "--date", "01/06/2026",
                )
            assert exc_info.value.code != 0

    def test_summary_includes_retry_fields_when_retried(self):
        """Command output summary includes retry rounds and attempts."""
        result = RecoveryRunResult(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            steps=[
                RecoveryStepResult(
                    date=date(2026, 6, 1),
                    date_label="01/06/2026",
                    extractor="discharges",
                    success=True,
                    extraction_type="discharge_extraction",
                    metrics={"total_records": 5},
                ),
            ],
            retry_rounds_used=1,
            retry_attempts=1,
        )
        with patch(_EXEC_PATH) as mock_exec:
            mock_exec.return_value = result
            out = StringIO()
            call_command(
                "recover_historical_data",
                "--date", "01/06/2026",
                stdout=out,
            )
            output = out.getvalue()
            assert "Retry rounds: 1" in output
            assert "(1 attempt(s))" in output
