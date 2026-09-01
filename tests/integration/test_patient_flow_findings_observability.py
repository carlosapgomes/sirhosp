"""PFIF-S5: aggregate observability for patient-flow findings.

Consolidated integration coverage for the final slice (health + portal +
runbook), all read-only:

- Health: only the exact S1/S2 allowlisted ``encounter_fallback`` evidence
  (succeeded stage, outcome ``recent_encounter_without_admission`` AND
  recency ``recent_confirmed``) excludes a batch-bound empty admissions
  success from the ``empty_success`` invariant and increments the aggregate
  ``recognized_recent_encounter`` counter. Every forged/partial/wrong-stage/
  wrong-recency/failed-stage variant stays an anomaly. Recognized empties
  never require full-sync; non-empty admissions still do.
- Portal: batches whose runs carry allowlisted outcomes derive
  ``Concluído com achados`` / ``Falha parcial`` presentation (history,
  detail and summary) without changing the persisted batch status; the
  technical axis (timeout, failure reasons, filters) stays counted beside
  findings; defaults and authorization are preserved; aggregation is
  bounded, never per-finding.
- Privacy: injected record/name/professional/URL/HTML/cookie/password
  sentinels never appear in command output, derived cards or exceptions.
- Runbook: the aggregate canary procedure (baseline, advance, stop,
  rollback, requeue/backfill prohibition) exists with no identifying
  sequences.

Synthetic fixtures only; no legacy, browser, network or production access.
"""

from __future__ import annotations

import io
import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.ingestion.extractors.patient_flow_snapshot import (
    OUTCOME_RECENT_ENCOUNTER_WITHOUT_ADMISSION,
)
from apps.ingestion.models import (
    CensusExecutionBatch,
    IngestionRun,
    IngestionRunStageMetric,
)
from apps.ingestion.patient_flow_findings import (
    _FINDING_SPECS,
    CODE_RECENT_ENCOUNTER_WITHOUT_ADMISSION,
)
from apps.ingestion.pipeline_health import HealthConfig, evaluate_pipeline_health
from apps.services_portal import views as portal_views

COMMAND_NAME = "check_ingestion_pipeline_health"
METRICS_URL = "services_portal:ingestion_metrics"

LABEL_RECENT = "Atendimento recente sem internação"
LABEL_CONCLUDED = "Concluído com achados"
LABEL_PARTIAL = "Falha parcial"

RECOGNIZED_DETAILS = {
    "outcome": OUTCOME_RECENT_ENCOUNTER_WITHOUT_ADMISSION,
    "recency": "recent_confirmed",
}

# Privacy sentinels (R7): injected into fixtures, asserted absent.
SENT_RECORD = "PRIV-REC-S5-9876543"
SENT_NAME = "PRIV-NOME-S5-BELTRANO"
SENT_PROFESSIONAL = "PRIV-PROFISSIONAL-S5-DRX"
SENT_URL = "https://priv-sentinel-s5.invalid/atendimentos"
SENT_HTML = "<td class='priv-sentinel-s5'>PRIV-HTML-S5</td>"
SENT_COOKIE = "PRIV-COOKIE-S5=sessionprivada"
SENT_PASSWORD = "PRIV-PASSWORD-S5-segred0"
SENT_DATE = "99/99/9999"
ALL_SENTINELS = (
    SENT_RECORD,
    SENT_NAME,
    SENT_PROFESSIONAL,
    SENT_URL,
    SENT_HTML,
    SENT_COOKIE,
    SENT_PASSWORD,
    SENT_DATE,
)


# ── Synthetic fixture builders ────────────────────────────────────────


def _finished_batch(status: str = "succeeded") -> CensusExecutionBatch:
    now = timezone.now()
    return CensusExecutionBatch.objects.create(
        status=status,
        enqueue_finished_at=now - timedelta(hours=2),
        finished_at=now - timedelta(hours=1),
    )


def _run(
    batch: CensusExecutionBatch | None,
    *,
    intent: str = "admissions_only",
    status: str = "succeeded",
    admissions_seen: int = 0,
    failure_reason: str = "",
    timed_out: bool = False,
    patient_record: str = "77770001",
    error_message: str = "",
    parameters_extra: dict | None = None,
) -> IngestionRun:
    parameters: dict = {"patient_record": patient_record, "intent": intent}
    if parameters_extra:
        parameters.update(parameters_extra)
    now = timezone.now()
    return IngestionRun.objects.create(
        batch=batch,
        intent=intent,
        status=status,
        admissions_seen=admissions_seen,
        failure_reason=failure_reason,
        timed_out=timed_out,
        error_message=error_message,
        parameters_json=parameters,
        queued_at=now - timedelta(minutes=70),
        finished_at=now - timedelta(minutes=30),
    )


def _stage(
    run: IngestionRun,
    *,
    stage_name: str = "encounter_fallback",
    status: str = "succeeded",
    details: dict | None = None,
) -> IngestionRunStageMetric:
    started = timezone.now() - timedelta(minutes=31)
    return IngestionRunStageMetric.objects.create(
        run=run,
        stage_name=stage_name,
        status=status,
        started_at=started,
        finished_at=started + timedelta(minutes=1),
        details_json=dict(details) if details is not None else {},
    )


def _recognized_stage(run: IngestionRun) -> IngestionRunStageMetric:
    return _stage(run, details=dict(RECOGNIZED_DETAILS))


def _recognized_empty_run(batch: CensusExecutionBatch) -> IngestionRun:
    run = _run(batch, admissions_seen=0)
    _recognized_stage(run)
    return run


def _health_output(*args: str) -> str:
    out = io.StringIO()
    err = io.StringIO()
    call_command(COMMAND_NAME, *args, stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


def _health_failure(*args: str) -> tuple[str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with pytest.raises(CommandError) as exc:
        call_command(COMMAND_NAME, *args, stdout=out, stderr=err)
    return out.getvalue() + err.getvalue(), str(exc.value)


def _minutes_ago(minutes: int):
    return timezone.now() - timedelta(minutes=minutes)


# ── R1/R2: health accepts only the exact allowlisted outcome ─────────


@pytest.mark.django_db
class TestHealthRecognizedRecentEncounter:
    def test_exact_outcome_is_recognized_healthy_not_empty_success(self):
        batch = _finished_batch()
        _recognized_empty_run(batch)
        output = _health_output()
        assert "healthy=true" in output
        assert "empty_success=0" in output
        assert "missing_full_sync=0" in output
        assert "recognized_recent_encounter=1" in output

    def test_service_dto_counts_recognized_separately(self):
        batch = _finished_batch()
        _recognized_empty_run(batch)
        result = evaluate_pipeline_health(HealthConfig())
        assert result.invariants.recognized_recent_encounter_count == 1
        assert result.invariants.empty_success_count == 0
        assert result.healthy

    @pytest.mark.parametrize(
        ("scenario", "stage_name", "stage_status", "details"),
        [
            ("unknown_outcome", "encounter_fallback", "succeeded",
             {"outcome": "patient_probably_ok", "recency": "recent_confirmed"}),
            ("missing_recency", "encounter_fallback", "succeeded",
             {"outcome": OUTCOME_RECENT_ENCOUNTER_WITHOUT_ADMISSION}),
            ("boundary_recency", "encounter_fallback", "succeeded",
             {"outcome": OUTCOME_RECENT_ENCOUNTER_WITHOUT_ADMISSION,
              "recency": "boundary"}),
            ("stale_recency", "encounter_fallback", "succeeded",
             {"outcome": OUTCOME_RECENT_ENCOUNTER_WITHOUT_ADMISSION,
              "recency": "stale"}),
            ("none_recency", "encounter_fallback", "succeeded",
             {"outcome": OUTCOME_RECENT_ENCOUNTER_WITHOUT_ADMISSION,
              "recency": "none"}),
            ("null_recency", "encounter_fallback", "succeeded",
             {"outcome": OUTCOME_RECENT_ENCOUNTER_WITHOUT_ADMISSION,
              "recency": None}),
            ("wrong_stage", "admissions_capture", "succeeded",
             dict(RECOGNIZED_DETAILS)),
            ("failed_stage", "encounter_fallback", "failed",
             dict(RECOGNIZED_DETAILS)),
            ("skipped_stage", "encounter_fallback", "skipped",
             dict(RECOGNIZED_DETAILS)),
            ("empty_details", "encounter_fallback", "succeeded", {}),
        ],
    )
    def test_forged_or_partial_variants_remain_anomalies(
        self, scenario, stage_name, stage_status, details
    ):
        batch = _finished_batch()
        run = _run(batch, admissions_seen=0)
        _stage(run, stage_name=stage_name, status=stage_status, details=details)
        output, error = _health_failure()
        combined = output + error
        assert "healthy=false" in combined
        assert "empty_success=1" in combined
        assert "recognized_recent_encounter=0" in combined

    def test_recognized_empty_does_not_require_full_sync(self):
        batch = _finished_batch()
        run = _run(batch, admissions_seen=0)
        run.finished_at = _minutes_ago(90)
        run.save()
        _recognized_stage(run)
        output = _health_output("--settling-minutes", "30")
        assert "healthy=true" in output
        assert "missing_full_sync=0" in output
        assert "recognized_recent_encounter=1" in output

    def test_non_empty_without_full_sync_still_missing(self):
        batch = _finished_batch()
        run = _run(batch, admissions_seen=2)
        run.finished_at = _minutes_ago(90)
        run.save()
        output, error = _health_failure("--settling-minutes", "30")
        combined = output + error
        assert "missing_full_sync=1" in combined
        assert "recognized_recent_encounter=0" in combined

    def test_outcome_on_non_empty_run_does_not_satisfy_follow_up(self):
        batch = _finished_batch()
        run = _run(batch, admissions_seen=3)
        run.finished_at = _minutes_ago(90)
        run.save()
        _recognized_stage(run)
        output, error = _health_failure("--settling-minutes", "30")
        combined = output + error
        assert "missing_full_sync=1" in combined

    def test_mixed_window_counts_each_axis_separately(self):
        recognized_batch = _finished_batch()
        _recognized_empty_run(recognized_batch)
        anomalous_batch = _finished_batch()
        _run(anomalous_batch, admissions_seen=0)
        non_empty_batch = _finished_batch()
        run = _run(non_empty_batch, admissions_seen=1)
        run.finished_at = _minutes_ago(90)
        run.save()
        output, error = _health_failure("--settling-minutes", "30")
        combined = output + error
        assert "empty_success=1" in combined
        assert "recognized_recent_encounter=1" in combined
        assert "missing_full_sync=1" in combined

    def test_recognition_counter_is_batch_bound_only(self):
        standalone = _run(None, admissions_seen=0)
        _recognized_stage(standalone)
        output = _health_output()
        assert "recognized_recent_encounter=0" in output
        assert "healthy=true" in output


# ── R2/R7: command output stays aggregate and sanitized ──────────────


@pytest.mark.django_db
class TestHealthCommandAggregatePrivacy:
    def test_recognized_output_is_aggregate_and_never_leaks_sentinels(self):
        batch = _finished_batch()
        # Sentinel-bearing recognized run: identity lives only in storage.
        run = _run(
            batch,
            patient_record=SENT_RECORD,
            error_message=(
                f"erro bruto {SENT_URL} {SENT_HTML} {SENT_COOKIE} "
                f"{SENT_PASSWORD} {SENT_DATE}"
            ),
            parameters_extra={
                "nome": SENT_NAME,
                "profissional": SENT_PROFESSIONAL,
            },
        )
        _recognized_stage(run)
        # Forged second run: sentinels as forged outcome values.
        forged = _run(batch, patient_record=SENT_RECORD)
        _stage(
            forged,
            details={"outcome": SENT_PROFESSIONAL, "recency": SENT_HTML},
        )
        output, error = _health_failure()
        combined = output + error
        assert "recognized_recent_encounter=1" in combined
        assert "empty_success=1" in combined
        for sentinel in ALL_SENTINELS:
            assert sentinel not in combined, f"sentinel leaked: {sentinel}"


# ── R3/R4/R5: portal derived presentation ────────────────────────────


@pytest.mark.django_db
class TestPortalDerivedPresentation:
    def test_succeeded_batch_with_finding_shows_concluded_with_findings(
        self, admin_client
    ):
        batch = _finished_batch("succeeded")
        _recognized_empty_run(batch)

        summary = admin_client.get(reverse(METRICS_URL), {"tab": "patients"})
        assert summary.status_code == 200
        content = summary.content.decode()
        assert LABEL_CONCLUDED in content
        assert LABEL_RECENT in content
        assert LABEL_PARTIAL not in content

        history = admin_client.get(reverse(METRICS_URL), {"tab": "runs"})
        assert LABEL_CONCLUDED in history.content.decode()

        detail = admin_client.get(
            reverse(METRICS_URL), {"tab": "runs", "batch_id": batch.pk}
        )
        assert detail.status_code == 200
        assert LABEL_CONCLUDED in detail.content.decode()

    def test_failed_batch_with_finding_and_timeout_shows_partial(
        self, admin_client
    ):
        batch = _finished_batch("failed")
        _recognized_empty_run(batch)
        _run(
            batch,
            intent="full_sync",
            status="failed",
            failure_reason="timeout",
            timed_out=True,
        )
        detail = admin_client.get(
            reverse(METRICS_URL), {"tab": "runs", "batch_id": batch.pk}
        )
        assert detail.status_code == 200
        content = detail.content.decode()
        assert LABEL_PARTIAL in content
        assert LABEL_CONCLUDED not in content
        # Technical axis stays visible: timeout row and Timeout reason.
        assert "Timeout" in content

    def test_timeout_stays_counted_beside_finding(self, admin_client):
        batch = _finished_batch("failed")
        _recognized_empty_run(batch)
        timeout_run = _run(
            batch,
            intent="full_sync",
            status="failed",
            failure_reason="timeout",
            timed_out=True,
        )
        # Failure reason filter keeps returning the timeout run.
        filtered = admin_client.get(
            reverse(METRICS_URL),
            {
                "tab": "runs",
                "batch_id": batch.pk,
                "failure_reason": "timeout",
            },
        )
        content = filtered.content.decode()
        assert f">{timeout_run.pk}<" in content
        # History keeps both axes: partial label + findings + failures.
        history = admin_client.get(reverse(METRICS_URL), {"tab": "runs"})
        history_content = history.content.decode()
        assert LABEL_PARTIAL in history_content
        assert "Achados: 1" in history_content

    def test_batch_without_findings_keeps_existing_labels(self, admin_client):
        batch = _finished_batch("succeeded")
        _run(batch, intent="full_sync", status="succeeded", admissions_seen=3)
        history = admin_client.get(reverse(METRICS_URL), {"tab": "runs"})
        content = history.content.decode()
        assert LABEL_CONCLUDED not in content
        assert LABEL_PARTIAL not in content
        assert "Sucesso" in content

    def test_no_batch_uses_complete_defaults(self, admin_client):
        response = admin_client.get(reverse(METRICS_URL), {"tab": "patients"})
        assert response.status_code == 200
        content = response.content.decode()
        assert LABEL_CONCLUDED not in content
        assert LABEL_PARTIAL not in content
        assert "Nenhum lote de censo finalizado" in content

    def test_anonymous_user_redirected_to_login(self, client):
        response = client.get(reverse(METRICS_URL))
        assert response.status_code == 302
        assert "/login/" in response.url


@pytest.mark.django_db
class TestPortalQueryBudget:
    def test_history_aggregation_is_bounded_not_per_finding(
        self, admin_client
    ):
        batch = _finished_batch("succeeded")
        base_run = _run(batch, admissions_seen=0)

        def _seed_findings(count: int) -> None:
            for _ in range(count):
                _recognized_stage(base_run)

        url = reverse(METRICS_URL)
        _seed_findings(1)
        with CaptureQueriesContext(connection) as ctx_small:
            assert admin_client.get(url, {"tab": "runs"}).status_code == 200
        queries_small = len(ctx_small.captured_queries)

        _seed_findings(30)
        with CaptureQueriesContext(connection) as ctx_big:
            assert admin_client.get(url, {"tab": "runs"}).status_code == 200
        queries_big = len(ctx_big.captured_queries)

        assert queries_big - queries_small <= 2, (
            f"query budget exceeded: {queries_small} -> {queries_big}"
        )


# ── R7: portal derived cards never leak sentinels ────────────────────


@pytest.mark.django_db
class TestPortalPrivacySentinels:
    def test_derived_cards_show_only_counts_never_sentinels(
        self, admin_client
    ):
        batch = _finished_batch("succeeded")
        _run(
            batch,
            admissions_seen=0,
            patient_record=SENT_RECORD,
            error_message=(
                f"erro bruto {SENT_URL} {SENT_HTML} {SENT_COOKIE} "
                f"{SENT_PASSWORD} {SENT_DATE}"
            ),
            parameters_extra={
                "nome": SENT_NAME,
                "profissional": SENT_PROFESSIONAL,
            },
        )
        recognized = IngestionRun.objects.filter(batch=batch).first()
        assert recognized is not None
        _recognized_stage(recognized)

        for params in (
            {"tab": "patients"},
            {"tab": "runs"},
            {"tab": "runs", "batch_id": batch.pk},
        ):
            response = admin_client.get(reverse(METRICS_URL), params)
            content = response.content.decode()
            assert LABEL_CONCLUDED in content
            if params != {"tab": "runs"}:
                # Summary and detail show per-label counts; history shows
                # only the aggregate findings total.
                assert LABEL_RECENT in content
            for sentinel in ALL_SENTINELS:
                assert sentinel not in content, (
                    f"sentinel leaked on {params}: {sentinel}"
                )


# ── R6: aggregate canary runbook exists, no identifying sequences ────


class TestRunbookCanary:
    def test_runbook_documents_baseline_advance_stop_rollback(self):
        runbook = Path(__file__).resolve().parents[2] / "deploy" / "README.md"
        text = runbook.read_text(encoding="utf-8")
        lowered = text.lower()
        for keyword in (
            "canário",
            "baseline",
            "avanço",
            "parada",
            "rollback",
            "requeue",
            "backfill",
        ):
            assert keyword in lowered, f"runbook missing keyword: {keyword}"
        # Requeue/backfill must appear as prohibitions, not procedures.
        assert "proibido" in lowered or "nunca" in lowered
        # No identifying sequences (long numeric identifiers).
        assert re.search(r"\b\d{7,}\b", text) is None


# ── Consistency: portal label mirrors the S3 closed presentation ─────


class TestPresentationLabelConsistency:
    def test_portal_labels_match_classifier_specs(self):
        assert portal_views._FINDING_OUTCOME_LABELS == {
            OUTCOME_RECENT_ENCOUNTER_WITHOUT_ADMISSION: _FINDING_SPECS[
                CODE_RECENT_ENCOUNTER_WITHOUT_ADMISSION
            ][0],
        }
