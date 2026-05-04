"""Summary services — business logic for progressive admission summaries.

APS-S2: queue_summary_run for on-demand enqueue.
APS-S4: execute_summary_run for worker-driven processing.
APS-S5: retry per chunk (MAX_RETRIES_PER_CHUNK=3), partial completion, and
        atomic state+version persistence.
APS-S6: get_admission_summary_context for UI badge/CTA state.
STP-S6: execute_two_phase_pipeline for two-phase orchestration with
        phase-1 reuse and per-step traceability.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone as django_timezone

from apps.patients.models import Admission
from apps.summaries.llm_gateway import (
    GatewayConfig,
    call_llm_gateway,
    call_llm_phase2_render,
)
from apps.summaries.models import (
    AdmissionSummaryState,
    AdmissionSummaryVersion,
    SummaryPipelineRun,
    SummaryPipelineStepRun,
    SummaryRun,
    SummaryRunChunk,
)
from apps.summaries.planner import plan_windows
from apps.summaries.prompt_loader import load_phase1_prompt, load_phase2_prompt
from apps.summaries.schema import validate_summary_output

if TYPE_CHECKING:
    from django.contrib.auth.models import User

VALID_MODES = {"generate", "update", "regenerate"}

MAX_RETRIES_PER_CHUNK = 3
PROMPT_VERSION = "aps-s9-v1"

# ---------------------------------------------------------------------------
# UI context helper (APS-S6)
# ---------------------------------------------------------------------------


def get_admission_summary_context(
    admission: Admission,
) -> dict:
    """Return summary UI context for the admission page.

    Returns a dict with keys:
      - badge_label: "Sem resumo" | "Em processamento" |
                     "Disponível" | "Incompleto"
      - badge_css: Bootstrap badge class
      - cta_label: "Gerar resumo" | "Atualizar resumo" |
                   "Regenerar resumo"
      - cta_mode: "generate" | "update" | "regenerate"
      - is_processing: bool
      - show_ler_resumo: bool
      - latest_run_id: int | None (for "Ler resumo" link)

    # TODO: prefetch se badges forem mostrados para múltiplas
    # admissões no dropdown (até 2 queries por admissão).
    """
    today = date.today()

    # 1. Check for active (queued or running) run → "Em processamento"
    active_run = (
        SummaryRun.objects.filter(
            admission=admission,
            status__in=[
                SummaryRun.Status.QUEUED,
                SummaryRun.Status.RUNNING,
            ],
        )
        .order_by("-created_at")
        .first()
    )

    if active_run is not None:
        return {
            "badge_label": "Em processamento",
            "badge_css": "bg-info text-dark",
            "cta_label": "Regenerar resumo",
            "cta_mode": "regenerate",
            "is_processing": True,
            "show_ler_resumo": False,
            "latest_run_id": active_run.pk,
        }

    # 2. Look up AdmissionSummaryState
    try:
        state = AdmissionSummaryState.objects.get(admission=admission)
    except AdmissionSummaryState.DoesNotExist:
        # No summary at all → "Gerar resumo"
        return {
            "badge_label": "Sem resumo",
            "badge_css": "bg-secondary",
            "cta_label": "Gerar resumo",
            "cta_mode": "generate",
            "is_processing": False,
            "show_ler_resumo": False,
            "latest_run_id": None,
        }

    # 3. Determine if summary is outdated
    #    Outdated = coverage_end < target_end_date
    #    For open admission: target = today
    #    For closed admission: target = min(today, discharge_date)
    if admission.discharge_date:
        target_end = min(today, admission.discharge_date.date())
    else:
        target_end = today

    is_outdated = state.coverage_end < target_end

    # 4. Get latest run for "Ler resumo" link
    latest_run_id: int | None = None
    has_narrative = bool(state.narrative_markdown)
    if has_narrative:
        latest_run = (
            SummaryRun.objects.filter(
                admission=admission,
                status__in=[
                    SummaryRun.Status.SUCCEEDED,
                    SummaryRun.Status.PARTIAL,
                ],
            )
            .order_by("-created_at")
            .first()
        )
        if latest_run is not None:
            latest_run_id = latest_run.pk

    # 5. Build response based on state
    if state.status == AdmissionSummaryState.Status.INCOMPLETE:
        return {
            "badge_label": "Incompleto",
            "badge_css": "bg-warning text-dark",
            "cta_label": "Regenerar resumo",
            "cta_mode": "regenerate",
            "is_processing": False,
            "show_ler_resumo": has_narrative,
            "latest_run_id": latest_run_id,
        }

    # DRAFT or COMPLETE
    if is_outdated:
        cta_label = "Atualizar resumo"
        cta_mode = "update"
    else:
        cta_label = "Regenerar resumo"
        cta_mode = "regenerate"

    return {
        "badge_label": "Disponível",
        "badge_css": "bg-success",
        "cta_label": cta_label,
        "cta_mode": cta_mode,
        "is_processing": False,
        "show_ler_resumo": has_narrative,
        "latest_run_id": latest_run_id,
    }


def queue_summary_run(
    *,
    admission: Admission,
    mode: str,
    requested_by: User | None = None,
    phase2_config_json: dict | None = None,
) -> SummaryRun:
    """Create a queued SummaryRun for an admission.

    Calculates target_end_date:
      - open admission (no discharge_date): today
      - closed admission: min(today, discharge_date)

    Optionally stores ``phase2_config_json`` for the worker to consume
    (STP-S7-F1).
    """
    today = date.today()

    if admission.discharge_date:
        discharge_date = admission.discharge_date.date()
        target_end_date = min(today, discharge_date)
    else:
        target_end_date = today

    kwargs: dict = {
        "admission": admission,
        "requested_by": requested_by,
        "mode": mode,
        "target_end_date": target_end_date,
        "status": SummaryRun.Status.QUEUED,
    }
    if phase2_config_json is not None:
        kwargs["phase2_config_json"] = phase2_config_json

    run = SummaryRun.objects.create(**kwargs)
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
        chunk_days=getattr(settings, "SUMMARY_CHUNK_DAYS", 4),
        overlap_days=getattr(settings, "SUMMARY_OVERLAP_DAYS", 2),
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

        # Build event dicts once (deterministic per window)
        novas_evolucoes = [
            {
                "event_id": getattr(ev, "event_identity_key", str(ev.pk)),
                "happened_at": (
                    ev.happened_at.isoformat()
                    if hasattr(ev, "happened_at")
                    else ""
                ),
                "signed_at": (
                    ev.signed_at.isoformat()
                    if getattr(ev, "signed_at", None)
                    else ""
                ),
                "author_name": getattr(ev, "author_name", ""),
                "profession_type": getattr(
                    ev, "profession_type", ""
                ),
                "content_text": getattr(ev, "content_text", ""),
            }
            for ev in events
        ]

        # --- b. Create/update chunk record ---
        chunk, _ = SummaryRunChunk.objects.get_or_create(
            run=run,
            chunk_index=idx,
            defaults={
                "window_start": window_start,
                "window_end": window_end,
                "status": SummaryRunChunk.Status.QUEUED,
                "attempt_count": 0,
                "input_event_count": len(events),
            },
        )

        # --- c-e. Retry loop: call LLM + validate, up to MAX_RETRIES ---
        llm_response: dict | None = None
        last_error_msg: str = ""

        for attempt in range(1, MAX_RETRIES_PER_CHUNK + 1):
            chunk.status = SummaryRunChunk.Status.RUNNING
            chunk.attempt_count = attempt
            chunk.input_event_count = len(events)
            chunk.save(
                update_fields=[
                    "status", "attempt_count", "input_event_count",
                ]
            )

            llm_response = call_llm_gateway(
                estado_estruturado_anterior=(
                    state.structured_state_json or {}
                ),
                resumo_markdown_anterior=state.narrative_markdown or "",
                novas_evolucoes=novas_evolucoes,
            )

            validation_errors = validate_summary_output(llm_response)
            if not validation_errors:
                # Success — break out of retry loop
                last_error_msg = ""
                break

            # Record failure for this attempt
            last_error_msg = "; ".join(validation_errors)
            chunk.error_message = last_error_msg
            chunk.status = SummaryRunChunk.Status.FAILED
            chunk.save(update_fields=["status", "error_message"])

        # ---- Exhausted retries? ------
        if last_error_msg:
            # All attempts failed for this chunk
            error_msg = (
                f"Chunk {idx} exhausted {MAX_RETRIES_PER_CHUNK} "
                f"retries: {last_error_msg}"
            )
            chunk.status = SummaryRunChunk.Status.FAILED
            chunk.error_message = error_msg
            chunk.save(update_fields=["status", "error_message"])

            run.status = SummaryRun.Status.PARTIAL
            run.error_message = error_msg
            run.finished_at = django_timezone.now()
            run.save(
                update_fields=[
                    "status", "error_message", "finished_at",
                ]
            )

            # Mark canonical state as incomplete (last valid state kept)
            state.status = AdmissionSummaryState.Status.INCOMPLETE
            state.save(update_fields=["status"])

            return run

        # ---- d-e-f. Persist state + version atomically (APS-S5 fix) ----
        # At this point we broke out of the retry loop with a valid
        # response, so llm_response is guaranteed to be a dict.
        assert llm_response is not None
        with transaction.atomic():
            state.coverage_start = min(
                state.coverage_start or window_start, window_start
            )
            state.coverage_end = max(
                state.coverage_end or window_end, window_end
            )
            state.structured_state_json = llm_response["estado_estruturado"]
            state.narrative_markdown = llm_response["resumo_markdown"]
            state.last_source_event_happened_at = (
                run.pinned_cutoff_happened_at
            )
            state.status = AdmissionSummaryState.Status.DRAFT
            state.save()

            AdmissionSummaryVersion.objects.create(
                admission=admission,
                summary_state=state,
                run=run,
                chunk_index=idx,
                coverage_start=window_start,
                coverage_end=window_end,
                structured_state_json=(
                    llm_response["estado_estruturado"]
                ),
                narrative_markdown=llm_response["resumo_markdown"],
                changes_json={
                    "mudancas": llm_response.get(
                        "mudancas_da_rodada", []
                    )
                },
                uncertainties_json={
                    "incertezas": llm_response.get("incertezas", []),
                    "alertas_consistencia": llm_response.get(
                        "alertas_consistencia", []
                    ),
                },
                evidences_json=llm_response.get("evidencias", []),
                llm_provider=llm_response.get("_meta", {}).get("provider", "stub"),
                llm_model=llm_response.get("_meta", {}).get("model", "stub-v0"),
                prompt_version=PROMPT_VERSION,
            )

        # ---- g. Mark chunk succeeded ----
        chunk.status = SummaryRunChunk.Status.SUCCEEDED
        chunk.error_message = ""
        chunk.save(update_fields=["status", "error_message"])

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


# ---------------------------------------------------------------------------
# Two-phase pipeline orchestration (STP-S6)
# ---------------------------------------------------------------------------

# Approximate cost per 1k tokens (USD) — matches llm_gateway defaults.
_PHASE1_INPUT_PRICE_PER_1K = Decimal("0.005")
_PHASE1_OUTPUT_PRICE_PER_1K = Decimal("0.015")


def _compute_phase1_cost_from_tokens(
    input_tokens: int,
    output_tokens: int,
) -> dict[str, Decimal]:
    """Compute phase-1 cost from aggregated token counts."""
    cost_in = (Decimal(input_tokens) / Decimal(1000)) * _PHASE1_INPUT_PRICE_PER_1K
    cost_out = (
        Decimal(output_tokens) / Decimal(1000)
    ) * _PHASE1_OUTPUT_PRICE_PER_1K
    return {
        "cost_input": cost_in,
        "cost_output": cost_out,
        "cost_total": cost_in + cost_out,
    }


def _should_reuse_phase1(
    *,
    admission_id: int,
    mode: str,
    target_end_date: date,
) -> bool:
    """Decide whether phase 1 can be fully reused.

    Phase 1 can be reused when:
    - An ``AdmissionSummaryState`` exists for the admission.
    - Its ``coverage_end`` >= ``target_end_date`` (existing state
      already covers the requested horizon).
    - Mode is ``update`` (generate/regenerate always rebuilds).
    """
    if mode not in ("update",):
        return False

    try:
        state = AdmissionSummaryState.objects.get(admission_id=admission_id)
    except AdmissionSummaryState.DoesNotExist:
        return False

    return state.coverage_end >= target_end_date


def _build_phase2_gateway_config(
    *,
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
) -> GatewayConfig:
    """Build a ``GatewayConfig`` for a phase-2 LLM call.

    When explicit credentials are not provided, falls back to the first
    enabled phase-2 option from environment configuration.
    """
    if not all([provider, model, base_url, api_key]):
        # Fall back to the first enabled phase-2 option.
        from apps.summaries.llm_config import load_phase2_options

        options = load_phase2_options()
        if not options:
            # Fall back to phase-1 config as last resort.
            from apps.summaries.llm_gateway import _load_config

            legacy = _load_config()
            provider = legacy.provider
            model = legacy.model
            base_url = legacy.base_url
            api_key = legacy.api_key
        else:
            opt = options[0]
            provider = opt.provider
            model = opt.model
            base_url = opt.base_url
            api_key = opt.api_key

    timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "120"))
    return GatewayConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
        provider=provider,
    )


def execute_two_phase_pipeline(
    run: SummaryRun,
    *,
    admission: Admission | None = None,
    phase2_prompt_text: str | None = None,
    phase2_provider: str = "",
    phase2_model: str = "",
    phase2_base_url: str = "",
    phase2_api_key: str = "",
) -> SummaryPipelineRun:
    """Execute a two-phase summary pipeline for a ``SummaryRun``.

    Lifecycle:

    1. Create a ``SummaryPipelineRun`` as the parent audit record.
    2. Decide phase-1 reuse: if an ``AdmissionSummaryState`` already
       covers the target period and mode is ``update``, phase 1 is
       skipped with cost zero.
    3. Execute phase 1 (canonical base) by delegating to
       ``execute_summary_run``, or create a skipped step record.
    4. Execute phase 2 (render) using the canonical narrative and
       a prompt (default from file or custom text).
    5. Persist ``SummaryPipelineStepRun`` records with prompt
       snapshots, payloads, costs, and timing.
    6. Update the ``SummaryPipelineRun`` with aggregated costs and
       final status.

    Args:
        run: A ``SummaryRun`` in ``queued`` or ``running`` status.
        admission: Pre-fetched ``Admission`` (avoids extra query).
        phase2_prompt_text: Custom prompt for phase 2.  When ``None``,
            the default prompt is loaded from the versioned file.
        phase2_provider: Phase-2 provider name (optional; falls back
            to first enabled phase-2 env option or, ultimately, phase-1
            config).
        phase2_model: Phase-2 model name (optional).
        phase2_base_url: Phase-2 base URL (optional).
        phase2_api_key: Phase-2 API key (optional).

    Returns:
        The persisted ``SummaryPipelineRun``.
    """
    now = django_timezone.now()

    # Load admission if not provided
    if admission is None:
        admission = Admission.objects.select_related("patient").get(
            pk=run.admission_id
        )

    # ---- 1. Create pipeline run ----
    pipeline_run = SummaryPipelineRun.objects.create(
        admission_id=run.admission_id,
        requested_by=run.requested_by,
        mode=run.mode,
        status=SummaryPipelineRun.Status.RUNNING,
        started_at=now,
        currency="USD",
    )

    # ---- 2. Decide phase-1 reuse ----
    phase1_reused = _should_reuse_phase1(
        admission_id=run.admission_id,
        mode=run.mode,
        target_end_date=run.target_end_date,
    )

    if phase1_reused:
        pipeline_run.phase1_reused = True
        pipeline_run.phase1_cost_total = Decimal("0.00")
        pipeline_run.save(
            update_fields=["phase1_reused", "phase1_cost_total"]
        )

        # Load phase-1 prompt for snapshot (even when skipped)
        phase1_prompt_text = ""
        try:
            phase1_prompt_text = load_phase1_prompt()
        except Exception:
            pass

        SummaryPipelineStepRun.objects.create(
            pipeline_run=pipeline_run,
            step_type=SummaryPipelineStepRun.StepType.PHASE1_CANONICAL,
            status=SummaryPipelineStepRun.Status.SKIPPED,
            provider_name="",
            model_name="",
            base_url="",
            prompt_version=PROMPT_VERSION,
            prompt_text_snapshot=phase1_prompt_text,
            request_payload_json={},
            response_payload_json={},
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            cost_input=Decimal("0.00"),
            cost_output=Decimal("0.00"),
            cost_total=Decimal("0.00"),
            latency_ms=0,
            started_at=now,
            finished_at=now,
        )
    else:
        # ---- 3. Execute phase 1 ----
        phase1_step = SummaryPipelineStepRun.objects.create(
            pipeline_run=pipeline_run,
            step_type=SummaryPipelineStepRun.StepType.PHASE1_CANONICAL,
            status=SummaryPipelineStepRun.Status.RUNNING,
            started_at=now,
        )

        try:
            execute_summary_run(run, admission=admission)
        except Exception as exc:
            # Phase 1 failed — mark pipeline as failed
            phase1_step.status = SummaryPipelineStepRun.Status.FAILED
            phase1_step.error_message = str(exc)
            phase1_step.finished_at = django_timezone.now()
            phase1_step.save(
                update_fields=["status", "error_message", "finished_at"]
            )

            pipeline_run.status = SummaryPipelineRun.Status.FAILED
            pipeline_run.error_message = str(exc)
            pipeline_run.finished_at = django_timezone.now()
            pipeline_run.save(
                update_fields=["status", "error_message", "finished_at"]
            )

            run.status = SummaryRun.Status.FAILED
            run.error_message = str(exc)
            run.finished_at = django_timezone.now()
            run.save(update_fields=["status", "error_message", "finished_at"])
            return pipeline_run

        # ---- Collect phase-1 metadata ----
        phase1_versions = AdmissionSummaryVersion.objects.filter(run=run)
        total_input = sum(
            (v.input_tokens or 0) for v in phase1_versions
        )
        total_output = sum(
            (v.output_tokens or 0) for v in phase1_versions
        )
        phase1_costs = _compute_phase1_cost_from_tokens(
            input_tokens=total_input,
            output_tokens=total_output,
        )

        # Load phase-1 prompt for the snapshot
        phase1_prompt_text = ""
        try:
            phase1_prompt_text = load_phase1_prompt()
        except Exception:
            pass

        # Provider/model from the first version (or stub)
        first_version = phase1_versions.first()
        phase1_provider = (
            first_version.llm_provider if first_version else "stub"
        )
        phase1_model = (
            first_version.llm_model if first_version else "stub-v0"
        )

        phase1_step.status = SummaryPipelineStepRun.Status.SUCCEEDED
        phase1_step.provider_name = phase1_provider
        phase1_step.model_name = phase1_model
        phase1_step.prompt_version = PROMPT_VERSION
        phase1_step.prompt_text_snapshot = phase1_prompt_text
        phase1_step.input_tokens = total_input
        phase1_step.output_tokens = total_output
        phase1_step.cost_input = phase1_costs["cost_input"]
        phase1_step.cost_output = phase1_costs["cost_output"]
        phase1_step.cost_total = phase1_costs["cost_total"]
        phase1_step.finished_at = django_timezone.now()
        phase1_step.save(
            update_fields=[
                "status", "provider_name", "model_name",
                "prompt_version", "prompt_text_snapshot",
                "input_tokens", "output_tokens",
                "cost_input", "cost_output", "cost_total",
                "finished_at",
            ]
        )

        pipeline_run.phase1_cost_total = phase1_costs["cost_total"]
        pipeline_run.save(update_fields=["phase1_cost_total"])

    # ---- 4. Execute phase 2 ----
    phase2_start = django_timezone.now()
    phase2_step = SummaryPipelineStepRun.objects.create(
        pipeline_run=pipeline_run,
        step_type=SummaryPipelineStepRun.StepType.PHASE2_RENDER,
        status=SummaryPipelineStepRun.Status.RUNNING,
        started_at=phase2_start,
    )

    # Load canonical state/narrative
    try:
        state = AdmissionSummaryState.objects.get(
            admission_id=run.admission_id
        )
        canonical_narrative = state.narrative_markdown
        canonical_state = state.structured_state_json or {}
    except AdmissionSummaryState.DoesNotExist:
        canonical_narrative = ""
        canonical_state = {}

    # Resolve prompt
    if phase2_prompt_text is not None:
        phase2_prompt = phase2_prompt_text
        phase2_prompt_version = "custom"
    else:
        phase2_prompt_version = "phase2_default_v1"
        try:
            phase2_prompt = load_phase2_prompt()
        except Exception:
            phase2_prompt = "Render the clinical summary as clean Markdown."

    # Build gateway config
    gateway_config = _build_phase2_gateway_config(
        provider=phase2_provider,
        model=phase2_model,
        base_url=phase2_base_url,
        api_key=phase2_api_key,
    )

    try:
        phase2_result = call_llm_phase2_render(
            canonical_narrative=canonical_narrative,
            canonical_state=canonical_state,
            prompt_text=phase2_prompt,
            config=gateway_config,
        )

        phase2_step.status = SummaryPipelineStepRun.Status.SUCCEEDED
        phase2_step.provider_name = gateway_config.provider
        phase2_step.model_name = gateway_config.model
        phase2_step.base_url = gateway_config.base_url
        phase2_step.prompt_version = phase2_prompt_version
        phase2_step.prompt_text_snapshot = phase2_prompt
        phase2_step.request_payload_json = phase2_result["request_payload"]
        phase2_step.response_payload_json = phase2_result["response_payload"]
        phase2_step.input_tokens = phase2_result["input_tokens"]
        phase2_step.output_tokens = phase2_result["output_tokens"]
        phase2_step.cached_tokens = phase2_result["cached_tokens"]
        phase2_step.cost_input = phase2_result["cost_input"]
        phase2_step.cost_output = phase2_result["cost_output"]
        phase2_step.cost_total = phase2_result["cost_total"]
        phase2_step.latency_ms = phase2_result.get("latency_ms", 0)
        phase2_step.finished_at = django_timezone.now()
        phase2_step.save(
            update_fields=[
                "status", "provider_name", "model_name", "base_url",
                "prompt_version", "prompt_text_snapshot",
                "request_payload_json", "response_payload_json",
                "input_tokens", "output_tokens", "cached_tokens",
                "cost_input", "cost_output", "cost_total",
                "latency_ms", "finished_at",
            ]
        )

        pipeline_run.phase2_cost_total = phase2_result["cost_total"]

    except Exception as exc:
        # Phase 2 failed — mark pipeline as partial (phase 1 succeeded)
        phase2_step.status = SummaryPipelineStepRun.Status.FAILED
        phase2_step.error_message = str(exc)
        phase2_step.finished_at = django_timezone.now()
        phase2_step.save(
            update_fields=["status", "error_message", "finished_at"]
        )

        pipeline_run.status = SummaryPipelineRun.Status.PARTIAL
        pipeline_run.error_message = str(exc)
        pipeline_run.finished_at = django_timezone.now()
        pipeline_run.save(
            update_fields=["status", "error_message", "finished_at"]
        )

        # Save partial costs: phase1 succeeded, phase2 = 0
        pipeline_run.phase2_cost_total = Decimal("0.00")
        pipeline_run.save(update_fields=["phase2_cost_total"])

        run.status = SummaryRun.Status.PARTIAL
        run.error_message = str(exc)
        run.finished_at = django_timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        return pipeline_run

    # ---- 5. Finalise pipeline run ----
    pipeline_run.status = SummaryPipelineRun.Status.SUCCEEDED
    pipeline_run.finished_at = django_timezone.now()
    pipeline_run.save(
        update_fields=[
            "status", "phase2_cost_total", "finished_at",
        ]
    )

    run.status = SummaryRun.Status.SUCCEEDED
    run.error_message = ""
    run.finished_at = django_timezone.now()
    run.save(update_fields=["status", "error_message", "finished_at"])

    return pipeline_run
