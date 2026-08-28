"""CFC-S1 unit tests: read-only characterization of the fail-only
full-sync failure cohort.

Covers the vertical slice requirements:

- R1: window/min-attempts/max-per-stage-rows validation before any query;
- R2: fail-only cohort detection (count, failed runs, attempt median/max,
  first/last failure age) with the ``--min-attempts`` floor;
- R3: failure reason distribution of the cohort and of the fail-then-ok
  contrast cohort (empty reasons aggregated as ``none``);
- R4: per-stage duration profiles (median/p90 seconds) with the
  per-stage row ceiling, terminal failing stage distribution and the
  aggregated 24-bucket hourly histogram;
- R5: sanitized stdout (no identifiers/parameters/clinical text/URL/raw
  error) and provably read-only evaluation (model counts + spies).
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.ingestion.fullsync_failure_characterization import (
    CharacterizationConfig,
    characterize_fullsync_failures,
)
from apps.ingestion.models import (
    CensusExecutionBatch,
    FinalRunFailure,
    IngestionRun,
    IngestionRunAttempt,
    IngestionRunStageMetric,
)

COMMAND_NAME = "characterize_fullsync_failures"

pytestmark = pytest.mark.django_db

SENTINEL_PATIENT = "PRIV-PAT-CFC-042"
SENTINEL_TEXT = "PRIV-TEXTO-CLINICO-CFC"
SENTINEL_URL = "https://priv-sentinel-cfc.invalid/x"
SENTINEL_ERROR = f"erro bruto {SENTINEL_URL} {SENTINEL_TEXT}"

_COUNTED_MODELS = (
    IngestionRun,
    CensusExecutionBatch,
    IngestionRunAttempt,
    FinalRunFailure,
    IngestionRunStageMetric,
)


def _model_counts() -> dict[str, int]:
    return {model._meta.label: model.objects.count() for model in _COUNTED_MODELS}


def _hours_ago(hours: int) -> datetime:
    return timezone.now() - timedelta(hours=hours)


def _utc(hour: int) -> datetime:
    return datetime(2026, 1, 5, hour, 15, tzinfo=dt_timezone.utc)


def _full_sync_run(
    *,
    patient_record: str,
    status: str = "failed",
    failure_reason: str = "",
    finished_at: datetime | None = None,
    queued_at: datetime | None = None,
    error_message: str = "",
) -> IngestionRun:
    return IngestionRun.objects.create(
        intent="full_sync",
        status=status,
        failure_reason=failure_reason,
        finished_at=finished_at or _hours_ago(1),
        queued_at=queued_at or _hours_ago(2),
        error_message=error_message,
        parameters_json={
            "patient_record": patient_record,
            "intent": "full_sync",
        },
    )


def _stage(
    run: IngestionRun,
    stage_name: str,
    duration_seconds: int,
    *,
    status: str = "succeeded",
    started_at: datetime | None = None,
) -> IngestionRunStageMetric:
    started = started_at or _hours_ago(3)
    return IngestionRunStageMetric.objects.create(
        run=run,
        stage_name=stage_name,
        started_at=started,
        finished_at=started + timedelta(seconds=duration_seconds),
        status=status,
    )


def _seed_cohort_dataset(now: datetime) -> dict[str, list[IngestionRun]]:
    """Build the canonical CFC-S1 dataset.

    Layout (all full_sync runs, window = 168h ending at ``now``):

    - PRIV-PAT-A: fail-only, 4 failed runs
      (timeout x3, invalid_payload x1; finished 100/96/90/80h ago);
    - PRIV-PAT-B: fail-only, 6 failed runs
      (invalid_payload x5, none x1; finished 70/60/50/40/30/20h ago);
    - PRIV-PAT-C: 2 failed runs, zero successes -> below --min-attempts
      (excluded from cohort and from contrast);
    - PRIV-PAT-D: 4 failed + 1 succeeded -> fail-then-ok contrast;
    - PRIV-PAT-E: succeeded only (nothing).
    """
    runs: dict[str, list[IngestionRun]] = {}

    a_specs = (
        ("timeout", 100, 3),
        ("timeout", 96, 3),
        ("timeout", 90, 3),
        ("invalid_payload", 80, 7),
    )
    runs["A"] = [
        _full_sync_run(
            patient_record="PRIV-PAT-A",
            status="failed",
            failure_reason=reason,
            finished_at=now - timedelta(hours=age),
            queued_at=_utc(hour),
        )
        for reason, age, hour in a_specs
    ]

    b_specs = (
        ("invalid_payload", 70, 7),
        ("invalid_payload", 60, 7),
        ("invalid_payload", 50, 7),
        ("invalid_payload", 40, 12),
        ("invalid_payload", 30, 12),
        ("", 20, 12),
    )
    runs["B"] = [
        _full_sync_run(
            patient_record="PRIV-PAT-B",
            status="failed",
            failure_reason=reason,
            finished_at=now - timedelta(hours=age),
            queued_at=_utc(hour),
        )
        for reason, age, hour in b_specs
    ]

    _full_sync_run(
        patient_record="PRIV-PAT-C",
        status="failed",
        failure_reason="timeout",
        finished_at=now - timedelta(hours=10),
        queued_at=_utc(15),
    )
    _full_sync_run(
        patient_record="PRIV-PAT-C",
        status="failed",
        failure_reason="timeout",
        finished_at=now - timedelta(hours=9),
        queued_at=_utc(15),
    )

    runs["D"] = [
        _full_sync_run(
            patient_record="PRIV-PAT-D",
            status="failed",
            failure_reason=reason,
            finished_at=now - timedelta(hours=age),
            queued_at=_utc(18),
        )
        for reason, age in (
            ("timeout", 22),
            ("timeout", 21),
            ("timeout", 20),
            ("invalid_payload", 19),
        )
    ]
    _full_sync_run(
        patient_record="PRIV-PAT-D",
        status="succeeded",
        finished_at=now - timedelta(hours=18),
        queued_at=_utc(18),
    )
    _full_sync_run(
        patient_record="PRIV-PAT-E",
        status="succeeded",
        finished_at=now - timedelta(hours=5),
        queued_at=_utc(20),
    )

    # Stage metrics on the fail-only cohort runs.
    _stage(
        runs["A"][0],
        "admissions_capture",
        30,
        started_at=now - timedelta(hours=3),
    )
    _stage(
        runs["A"][0],
        "evolution_extraction",
        10,
        status="failed",
        started_at=now - timedelta(hours=2, minutes=50),
    )
    for run in runs["A"][1:]:
        _stage(
            run,
            "evolution_extraction",
            10 * (runs["A"].index(run) + 1),
            status="failed",
            started_at=now - timedelta(hours=2),
        )
    _stage(
        runs["B"][0],
        "evolution_extraction",
        45,
        status="failed",
        started_at=now - timedelta(hours=2),
    )
    _stage(
        runs["B"][1],
        "admissions_capture",
        60,
        started_at=now - timedelta(hours=3),
    )
    return runs


def _run_command(*args: str) -> str:
    out = io.StringIO()
    err = io.StringIO()
    call_command(COMMAND_NAME, *args, stdout=out, stderr=err)
    return out.getvalue()


class TestFailOnlyCohort:
    def test_cohort_detected_with_counts_attempts_and_ages(self):
        now = timezone.now()
        _seed_cohort_dataset(now)
        result = characterize_fullsync_failures(
            CharacterizationConfig(window_hours=168, min_attempts=3),
            now=now,
        )
        assert result.cohort.cohort_patients == 2
        assert result.cohort.cohort_failed_runs == 10
        assert result.cohort.attempts_median == 5
        assert result.cohort.attempts_max == 6
        assert result.cohort.first_failure_age_hours == 100
        assert result.cohort.last_failure_age_hours == 20

    def test_min_attempts_excludes_patient_with_few_terminal_runs(self):
        now = timezone.now()
        _seed_cohort_dataset(now)
        # PRIV-PAT-C has only 2 terminal runs: excluded at min_attempts=3.
        result = characterize_fullsync_failures(
            CharacterizationConfig(window_hours=168, min_attempts=3),
            now=now,
        )
        assert result.cohort.cohort_patients == 2
        # Lowering the floor to 2 admits PRIV-PAT-C into the cohort.
        result = characterize_fullsync_failures(
            CharacterizationConfig(window_hours=168, min_attempts=2),
            now=now,
        )
        assert result.cohort.cohort_patients == 3
        assert result.cohort.cohort_failed_runs == 12

    def test_fail_then_ok_patient_outside_cohort_and_in_contrast(self):
        now = timezone.now()
        _seed_cohort_dataset(now)
        result = characterize_fullsync_failures(
            CharacterizationConfig(window_hours=168, min_attempts=3),
            now=now,
        )
        # PRIV-PAT-D has 5 terminal runs (4 failed + 1 succeeded): not
        # fail-only, so it must never enter the cohort...
        assert result.cohort.cohort_patients == 2
        # ...but its failed runs are the contrast baseline.
        contrast = dict(result.reasons.contrast)
        assert contrast == {"invalid_payload": 1, "timeout": 3}

    def test_success_only_patient_contributes_nothing(self):
        now = timezone.now()
        _seed_cohort_dataset(now)
        result = characterize_fullsync_failures(
            CharacterizationConfig(window_hours=168, min_attempts=3),
            now=now,
        )
        assert result.cohort.cohort_failed_runs == 10
        assert dict(result.reasons.contrast) == {"invalid_payload": 1, "timeout": 3}


class TestReasonDistribution:
    def test_cohort_and_contrast_reasons_include_none(self):
        now = timezone.now()
        _seed_cohort_dataset(now)
        result = characterize_fullsync_failures(
            CharacterizationConfig(window_hours=168, min_attempts=3),
            now=now,
        )
        cohort = dict(result.reasons.cohort)
        assert cohort == {"invalid_payload": 6, "none": 1, "timeout": 3}
        assert result.reasons.cohort == tuple(
            sorted(result.reasons.cohort)
        )

    def test_empty_database_has_empty_reason_distributions(self):
        now = timezone.now()
        result = characterize_fullsync_failures(
            CharacterizationConfig(window_hours=168, min_attempts=3),
            now=now,
        )
        assert result.reasons.cohort == ()
        assert result.reasons.contrast == ()


class TestStageTiming:
    def test_stage_profiles_median_p90_and_terminal_stage(self):
        now = timezone.now()
        _seed_cohort_dataset(now)
        result = characterize_fullsync_failures(
            CharacterizationConfig(window_hours=168, min_attempts=3),
            now=now,
        )
        profiles = {profile.stage_name: profile for profile in result.stage_profiles}
        evo = profiles["evolution_extraction"]
        assert evo.samples == 5
        assert evo.duration_median_seconds == 30.0
        assert evo.duration_p90_seconds == 45.0
        adm = profiles["admissions_capture"]
        assert adm.samples == 2
        assert adm.duration_median_seconds == 45.0
        assert adm.duration_p90_seconds == 60.0
        assert dict(result.terminal_failing_stages) == {
            "evolution_extraction": 5,
            "none": 5,
        }

    def test_max_per_stage_rows_caps_the_sample(self):
        now = timezone.now()
        # Three runs; each carries six stage rows with distinct minute
        # offsets so the most recent rows are unambiguous. The cap is a
        # global safety ceiling per stage profile (the 5 most recent
        # rows across all runs).
        for run_index in range(3):
            run = _full_sync_run(
                patient_record="PRIV-PAT-CAP",
                status="failed",
                failure_reason="timeout",
                finished_at=now - timedelta(hours=4),
                queued_at=_utc(9),
            )
            for index in range(6):
                _stage(
                    run,
                    "evolution_extraction",
                    10 * (index + 1),
                    status="failed",
                    started_at=(
                        now - timedelta(hours=3) + timedelta(minutes=10 * run_index + index)
                    ),
                )
        result = characterize_fullsync_failures(
            CharacterizationConfig(
                window_hours=168,
                min_attempts=3,
                max_per_stage_rows=5,
            ),
            now=now,
        )
        profiles = {profile.stage_name: profile for profile in result.stage_profiles}
        evo = profiles["evolution_extraction"]
        # 18 rows total; the ceiling keeps the 5 most recent (by
        # started_at): 20,30,40,50,60 -> median 40, p90 60.
        assert evo.samples == 5
        assert evo.duration_median_seconds == 40.0
        assert evo.duration_p90_seconds == 60.0


class TestHourlyHistogram:
    def test_24_bucket_histogram_of_failed_cohort_queued_at(self):
        now = timezone.now()
        _seed_cohort_dataset(now)
        result = characterize_fullsync_failures(
            CharacterizationConfig(window_hours=168, min_attempts=3),
            now=now,
        )
        buckets = dict(result.hourly.hours)
        assert len(buckets) == 24
        assert buckets[3] == 3
        assert buckets[7] == 4
        assert buckets[12] == 3
        assert sum(buckets.values()) == 10


class TestArgumentValidation:
    @pytest.mark.parametrize(
        "args",
        [
            ("--window-hours", "0"),
            ("--window-hours", "-5"),
            ("--min-attempts", "0"),
            ("--min-attempts", "-2"),
            ("--max-per-stage-rows", "0"),
            ("--max-per-stage-rows", "-1"),
        ],
    )
    @mock.patch(
        "apps.ingestion.management.commands."
        "characterize_fullsync_failures.characterize_fullsync_failures"
    )
    def test_invalid_arguments_fail_before_any_query(
        self, mock_service: mock.Mock, args: tuple[str, str]
    ):
        with pytest.raises(CommandError):
            call_command(COMMAND_NAME, *args)
        mock_service.assert_not_called()


class TestCommandOutput:
    def test_empty_database_reports_zeros_and_exits_zero(self):
        output = _run_command()
        assert "window_hours=168" in output
        assert "min_attempts=3" in output
        assert "cohort: patients=0 failed_runs=0" in output
        assert "attempts_median=none attempts_max=0" in output
        assert "first_failure_age_hours=none last_failure_age_hours=none" in output
        assert "cohort_failure_reasons: none" in output
        assert "contrast_failure_reasons: none" in output
        assert "stage_profiles: none" in output
        assert "terminal_failing_stages: none" in output
        assert "hourly_histogram: hour=0=0" in output
        assert "hour=23=0" in output

    def test_full_output_is_aggregate_and_deterministic(self):
        _seed_cohort_dataset(timezone.now())
        output = _run_command("--window-hours", "168", "--min-attempts", "3")
        assert (
            "cohort: patients=2 failed_runs=10 attempts_median=5 attempts_max=6 "
            "first_failure_age_hours=100 last_failure_age_hours=20"
        ) in output
        assert "cohort_failure_reasons: invalid_payload=6,none=1,timeout=3" in output
        assert "contrast_failure_reasons: invalid_payload=1,timeout=3" in output
        assert (
            "stage_profiles: "
            "admissions_capture:median_seconds=45.0,p90_seconds=60.0,samples=2|"
            "evolution_extraction:median_seconds=30.0,p90_seconds=45.0,samples=5"
        ) in output
        assert "terminal_failing_stages: evolution_extraction=5,none=5" in output
        assert "hourly_histogram:" in output
        assert "hour=3=3" in output
        assert "hour=7=4" in output
        assert "hour=12=3" in output


class TestReadOnlyEvaluation:
    def test_model_counts_unchanged_with_cohort(self):
        now = timezone.now()
        _seed_cohort_dataset(now)
        before = _model_counts()
        _run_command()
        assert _model_counts() == before

    def test_model_counts_unchanged_when_empty(self):
        before = _model_counts()
        _run_command()
        assert _model_counts() == before

    def test_no_playwright_network_or_command_execution(self):
        _seed_cohort_dataset(timezone.now())
        with (
            mock.patch(
                "subprocess.Popen", side_effect=AssertionError("subprocess.Popen called")
            ),
            mock.patch(
                "subprocess.run", side_effect=AssertionError("subprocess.run called")
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
        ):
            _run_command()


class TestOutputPrivacy:
    def test_sentinels_never_appear_in_stdout_stderr_or_error(self):
        now = timezone.now()
        _seed_cohort_dataset(now)
        # Sentinel-laden fail-only patient with raw error text and a
        # sentinel-bearing stage metric: identity and content must never
        # cross the output boundary even though its reasons are aggregated.
        for index in range(3):
            run = _full_sync_run(
                patient_record=SENTINEL_PATIENT,
                status="failed",
                failure_reason="invalid_payload",
                finished_at=now - timedelta(hours=12 - index),
                queued_at=_utc(16),
                error_message=SENTINEL_ERROR,
            )
            _stage(
                run,
                "evolution_extraction",
                10,
                status="failed",
                started_at=now - timedelta(hours=2),
            )
        IngestionRunStageMetric.objects.filter(run__parameters_json__patient_record=SENTINEL_PATIENT).update(
            details_json={"sentinel": SENTINEL_TEXT}
        )
        batch = CensusExecutionBatch.objects.create(status="failed")
        FinalRunFailure.objects.create(
            batch=batch,
            run=IngestionRun.objects.filter(
                parameters_json__patient_record=SENTINEL_PATIENT
            ).first(),
            patient_record=SENTINEL_PATIENT,
            intent="full_sync",
            attempts_exhausted=3,
        )
        out = _run_command()
        combined = out
        for sentinel in (
            SENTINEL_PATIENT,
            SENTINEL_TEXT,
            SENTINEL_URL,
            SENTINEL_ERROR,
        ):
            assert sentinel not in combined, f"sentinel leaked: {sentinel}"
        assert "invalid_payload=9" in out
