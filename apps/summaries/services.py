"""Summary services — business logic for progressive admission summaries.

APS-S2: queue_summary_run for on-demand enqueue.
APS-S4: execute_summary_run for worker-driven processing.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Optional

from django.utils import timezone as django_timezone

from apps.patients.models import Admission
from apps.summaries.llm_gateway import call_llm_gateway
from apps.summaries.models import (
    AdmissionSummaryState,
    AdmissionSummaryVersion,
    SummaryRun,
    SummaryRunChunk,
)
from apps.summaries.planner import plan_windows
from apps.summaries.schema import validate_summary_output

if TYPE_CHECKING:
    from django.contrib.auth.models import User

VALID_MODES = {"generate", "update", "regenerate"}


def queue_summary_run(
    *,
    admission: Admission,
    mode: str,
    requested_by: User | None = None,
) -> SummaryRun:
    """Create a queued SummaryRun for an admission.

    Calculates target_end_date:
      - open admission (no discharge_date): today
      - closed admission: min(today, discharge_date)
    """
    today = date.today()

    if admission.discharge_date:
        discharge_date = admission.discharge_date.date()
        target_end_date = min(today, discharge_date)
    else:
        target_end_date = today

    run = SummaryRun.objects.create(
        admission=admission,
        requested_by=requested_by,
        mode=mode,
        target_end_date=target_end_date,
        status=SummaryRun.Status.QUEUED,
    )
    return run


# ---------------------------------------------------------------------------
# Worker execution (APS-S4)
# ---------------------------------------------------------------------------


def execute_summary_run(
    run: SummaryRun,
    *,
    admission: Admission | None = None,
) -> SummaryRun:
    """Execute a single SummaryRun synchronously.

    Lifecycle:
    1. Claim: queued -> running, set pinned_cutoff_happened_at.
    2. Plan windows via ``plan_windows``.
    3. For each window:
       a. Load ClinicalEvents filtered by admission + happened_at <= cutoff.
       b. Create/update SummaryRunChunk (queued -> running).
       c. Call LLM gateway with prior state + new events.
       d. Validate LLM output.
       e. Update AdmissionSummaryState.
       f. Create AdmissionSummaryVersion.
       g. Update chunk to succeeded.
    4. Transition run to succeeded.

    Args:
        run: A SummaryRun in ``queued`` status.
        admission: Pre-fetched Admission (avoids extra query).

    Returns:
        The updated SummaryRun (persisted).
    """
    # ---- 1. Claim -------
    now = django_timezone.now()
    run.status = SummaryRun.Status.RUNNING
    run.pinned_cutoff_happened_at = now
    run.started_at = now
    run.save(
        update_fields=[
            "status",
            "pinned_cutoff_happened_at",
            "started_at",
        ]
    )

    # Load admission if not provided
    if admission is None:
        admission = Admission.objects.select_related("patient").get(
            pk=run.admission_id
        )

    # Determine admission start date
    if admission.admission_date is None:
        admission_start = date.today()
    else:
        admission_start = admission.admission_date.date()

    # ---- 2. Plan windows -------
    # Determine prior_coverage_end for update mode
    prior_coverage_end: Optional[date] = None
    if run.mode == "update":
        try:
            state = AdmissionSummaryState.objects.get(
                admission=admission
            )
            prior_coverage_end = state.coverage_end
        except AdmissionSummaryState.DoesNotExist:
            prior_coverage_end = None

    windows = plan_windows(
        admission_date=admission_start,
        target_end_date=run.target_end_date,
        mode=run.mode,
        prior_coverage_end=prior_coverage_end,
    )

    run.total_chunks = len(windows)
    run.current_chunk_index = 0
    run.save(update_fields=["total_chunks", "current_chunk_index"])

    # ---- 3. Process each window -------
    # Get or create the canonical state for this admission
    state, _created = AdmissionSummaryState.objects.get_or_create(
        admission=admission,
        defaults={
            "coverage_start": admission_start,
            "coverage_end": admission_start,
            "structured_state_json": {},
            "narrative_markdown": "",
            "status": AdmissionSummaryState.Status.DRAFT,
        },
    )

    for idx, (window_start, window_end) in enumerate(windows):
        run.current_chunk_index = idx
        run.save(update_fields=["current_chunk_index"])

        # --- a. Load events for this window ---
        events = _load_events_for_window(
            run=run,
            admission_id=admission.pk,
            window_start=window_start,
            window_end=window_end,
        )

        # --- b. Create/update chunk record ---
        chunk, _ = SummaryRunChunk.objects.get_or_create(
            run=run,
            chunk_index=idx,
            defaults={
                "window_start": window_start,
                "window_end": window_end,
                "status": SummaryRunChunk.Status.RUNNING,
                "attempt_count": 1,
                "input_event_count": len(events),
            },
        )
        chunk.status = SummaryRunChunk.Status.RUNNING
        chunk.attempt_count = 1
        chunk.input_event_count = len(events)
        chunk.save(
            update_fields=["status", "attempt_count", "input_event_count"]
        )

        # --- c. Build input and call LLM gateway ---
        novas_evolucoes = [
            {
                "event_id": getattr(ev, "event_identity_key", str(ev.pk)),
                "happened_at": (
                    ev.happened_at.isoformat()
                    if hasattr(ev, "happened_at")
                    else ""
                ),
                "profession_type": getattr(
                    ev, "profession_type", ""
                ),
                "content_text": getattr(ev, "content_text", ""),
            }
            for ev in events
        ]

        llm_response = call_llm_gateway(
            estado_estruturado_anterior=state.structured_state_json or {},
            resumo_markdown_anterior=state.narrative_markdown or "",
            novas_evolucoes=novas_evolucoes,
        )

        # --- d. Validate output ---
        validation_errors = validate_summary_output(llm_response)
        if validation_errors:
            error_msg = "; ".join(validation_errors)
            chunk.status = SummaryRunChunk.Status.FAILED
            chunk.error_message = error_msg
            chunk.save(update_fields=["status", "error_message"])
            run.status = SummaryRun.Status.FAILED
            run.error_message = f"Chunk {idx}: {error_msg}"
            run.finished_at = django_timezone.now()
            run.save(update_fields=["status", "error_message", "finished_at"])
            return run

        # --- e. Update canonical state ---
        state.coverage_start = min(
            state.coverage_start or window_start, window_start
        )
        state.coverage_end = max(
            state.coverage_end or window_end, window_end
        )
        state.structured_state_json = llm_response["estado_estruturado"]
        state.narrative_markdown = llm_response["resumo_markdown"]
        state.last_source_event_happened_at = run.pinned_cutoff_happened_at
        state.status = AdmissionSummaryState.Status.DRAFT
        state.save()

        # --- f. Create version snapshot ---
        AdmissionSummaryVersion.objects.create(
            admission=admission,
            summary_state=state,
            run=run,
            chunk_index=idx,
            coverage_start=window_start,
            coverage_end=window_end,
            structured_state_json=llm_response["estado_estruturado"],
            narrative_markdown=llm_response["resumo_markdown"],
            changes_json={
                "mudancas": llm_response.get("mudancas_da_rodada", [])
            },
            uncertainties_json={
                "incertezas": llm_response.get("incertezas", [])
            },
            evidences_json=llm_response.get("evidencias", []),
            llm_provider="stub",
            llm_model="stub-v0",
            prompt_version="aps-s4-v1",
        )

        # --- g. Mark chunk succeeded ---
        chunk.status = SummaryRunChunk.Status.SUCCEEDED
        chunk.save(update_fields=["status"])

    # ---- 4. Finalise run -------
    run.status = SummaryRun.Status.SUCCEEDED
    run.current_chunk_index = run.total_chunks
    run.finished_at = django_timezone.now()
    run.save(
        update_fields=["status", "current_chunk_index", "finished_at"]
    )

    return run


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_events_for_window(
    *,
    run: SummaryRun,
    admission_id: int,
    window_start: date,
    window_end: date,
) -> list:
    """Load ClinicalEvents for a window, respecting the pinned cutoff.

    Filters by:
      - admission_id (only events for this admission)
      - happened_at date within [window_start, window_end]
      - happened_at <= pinned_cutoff_happened_at (no new events after
        run start)

    Returns:
        List of ClinicalEvent instances ordered by happened_at.
    """
    from apps.clinical_docs.models import ClinicalEvent

    qs = ClinicalEvent.objects.filter(
        admission_id=admission_id,
    )

    # Date range filter
    qs = qs.filter(
        happened_at__date__gte=window_start,
        happened_at__date__lte=window_end,
    )

    # Cutoff filter — only events that happened at or before the pinned
    # cutoff timestamp.
    if run.pinned_cutoff_happened_at is not None:
        qs = qs.filter(
            happened_at__lte=run.pinned_cutoff_happened_at
        )

    return list(qs.order_by("happened_at"))
