"""Shared helpers for closing drained ingestion batches."""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from apps.ingestion.models import CensusExecutionBatch, IngestionRun


def try_close_batch(
    batch: CensusExecutionBatch | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Close ``batch`` when it has no queued/running runs left.

    Returns ``True`` when this call closed the batch, otherwise ``False``.
    The batch is marked ``failed`` if any run in the batch is terminally failed;
    otherwise it is marked ``succeeded``.
    """
    if batch is None:
        return False
    if batch.finished_at is not None:
        return False

    active_runs = IngestionRun.objects.filter(
        batch=batch,
        status__in=["queued", "running"],
    ).exists()
    if active_runs:
        return False

    has_failures = IngestionRun.objects.filter(
        batch=batch,
        status="failed",
    ).exists()
    batch.finished_at = now or timezone.now()
    batch.status = "failed" if has_failures else "succeeded"
    batch.save(update_fields=["finished_at", "status"])
    return True
