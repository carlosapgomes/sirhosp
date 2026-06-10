"""Shared contract for historical extraction services.

Provides the `ExtractionResult` dataclass used by admission and death
historical extraction services to return structured success/failure
metadata without relying on CLI exit codes or stdout parsing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from django.conf import settings as django_settings
from django.utils import timezone

from apps.ingestion.models import IngestionRun, IngestionRunStageMetric

# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------


@dataclass
class SourceCredentials:
    """Resolved source-system credentials for historical extraction.

    Attributes:
        url: Base URL of the source system.
        username: Authentication username.
        password: Authentication password.

    The ``password`` field is excluded from ``repr()`` to prevent
    accidental credential exposure in logs or error messages.
    """

    url: str
    username: str
    password: str = field(repr=False)


def resolve_source_credentials() -> SourceCredentials:
    """Resolve source-system credentials from Django settings or environment.

    Checks ``settings.SOURCE_SYSTEM_URL``,
    ``settings.SOURCE_SYSTEM_USERNAME``, and
    ``settings.SOURCE_SYSTEM_PASSWORD`` first. Falls back to
    environment variables with the same names when a setting is empty.

    Returns:
        A ``SourceCredentials`` with all three fields populated.

    Raises:
        ValueError: If any required credential is missing both from
            settings and environment.
    """
    source_url = getattr(django_settings, "SOURCE_SYSTEM_URL", "") or os.getenv(
        "SOURCE_SYSTEM_URL", ""
    )
    username = getattr(django_settings, "SOURCE_SYSTEM_USERNAME", "") or os.getenv(
        "SOURCE_SYSTEM_USERNAME", ""
    )
    password = getattr(django_settings, "SOURCE_SYSTEM_PASSWORD", "") or os.getenv(
        "SOURCE_SYSTEM_PASSWORD", ""
    )

    missing: list[str] = []
    if not source_url:
        missing.append("SOURCE_SYSTEM_URL")
    if not username:
        missing.append("SOURCE_SYSTEM_USERNAME")
    if not password:
        missing.append("SOURCE_SYSTEM_PASSWORD")

    if missing:
        raise ValueError(
            "Missing source system credential(s): " + ", ".join(missing)
        )

    return SourceCredentials(url=source_url, username=username, password=password)


# ---------------------------------------------------------------------------
# IngestionRun lifecycle helpers
# ---------------------------------------------------------------------------


def create_stage_metric(
    run: IngestionRun,
    stage_name: str,
    status: str,
    started_at,
    finished_at=None,
    details_json: dict[str, Any] | None = None,
) -> IngestionRunStageMetric:
    """Create and persist an ``IngestionRunStageMetric`` for a run stage.

    Args:
        run: The ``IngestionRun`` this stage belongs to.
        stage_name: Machine-readable stage identifier
            (e.g. ``"admission_extraction"``).
        status: Stage outcome (``"succeeded"``, ``"failed"``,
            ``"skipped"``).
        started_at: When the stage started.
        finished_at: When the stage finished. Defaults to ``timezone.now()``.
        details_json: Optional stage-level context dict.

    Returns:
        The created ``IngestionRunStageMetric`` instance.
    """
    if finished_at is None:
        finished_at = timezone.now()

    return IngestionRunStageMetric.objects.create(
        run=run,
        stage_name=stage_name,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        details_json=details_json or {},
    )


def mark_run_succeeded(run: IngestionRun) -> None:
    """Mark an ``IngestionRun`` as succeeded with a finished timestamp.

    Sets ``status`` to ``"succeeded"`` and ``finished_at`` to the
    current time, then persists the changes.

    Args:
        run: The ``IngestionRun`` to finalise.
    """
    run.status = "succeeded"
    run.finished_at = timezone.now()
    run.save()


def mark_run_failed(
    run: IngestionRun,
    error_message: str,
    failure_reason: str = "",
    timed_out: bool = False,
) -> None:
    """Mark an ``IngestionRun`` as failed with safe error metadata.

    Sets ``status`` to ``"failed"``, records the provided error
    details, and sets ``finished_at`` to the current time.

    The ``error_message`` should already be sanitised via
    :func:`safe_error_message` before being passed here.

    Args:
        run: The ``IngestionRun`` to finalise.
        error_message: Safe, user-readable error description. Must
            not contain credentials or sensitive context.
        failure_reason: Normalised failure category
            (e.g. ``"timeout"``, ``"source_unavailable"``).
        timed_out: Whether this run terminated due to timeout.
    """
    run.status = "failed"
    run.error_message = error_message
    run.finished_at = timezone.now()
    run.failure_reason = failure_reason
    run.timed_out = timed_out
    run.save()


# ---------------------------------------------------------------------------
# Safe error formatting
# ---------------------------------------------------------------------------


def safe_error_message(
    message: str | None,
    max_length: int = 500,
) -> str:
    """Truncate an error message to a safe length.

    Long error messages are truncated to ``max_length`` characters with
    an ellipsis suffix. ``None`` is returned as an empty string.

    This function does **not** attempt to redact credentials — the
    caller is responsible for never passing credential-bearing text.

    Args:
        message: The raw error message (may be ``None``).
        max_length: Maximum character length before truncation.

    Returns:
        A safe, truncated error string.
    """
    if not message:
        return ""
    if len(message) <= max_length:
        return message
    # When max_length is too small for "..." suffix, truncate without ellipsis.
    if max_length < 3:
        return message[:max_length]
    # Reserve exactly 3 chars for "..." so total length <= max_length.
    keep = max_length - 3
    return message[:keep] + "..."


# ---------------------------------------------------------------------------
# Legacy: shared result contract (Slice S1)
# ---------------------------------------------------------------------------


@dataclass
class ExtractionResult:
    """Structured result for a single historical extraction execution.

    Attributes:
        extraction_type: Machine-readable extraction identifier
            (e.g. ``"admission_extraction"``, ``"death_extraction"``).
        target_start: Inclusive start date of the extraction period.
        target_end: Inclusive end date of the extraction period.
        success: Whether the extraction completed without unrecoverable
            errors.
        metrics: Arbitrary key-value counters from the extraction and
            persistence stages (e.g. ``{"total_records": 42}``).
        failure_reason: Normalized failure category when ``success`` is
            ``False`` (e.g. ``"timeout"``, ``"source_unavailable"``).
            Empty string when ``success`` is ``True``.
        error_message: Safe, user-readable error description. Must not
            contain credentials or sensitive context.
        ingestion_run_id: Optional primary key of the associated
            ``IngestionRun``, if one was created.
    """

    extraction_type: str
    target_start: date
    target_end: date
    success: bool

    metrics: dict[str, Any] = field(default_factory=dict)
    failure_reason: str = ""
    error_message: str = ""
    ingestion_run_id: Optional[int] = None
