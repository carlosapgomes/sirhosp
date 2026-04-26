"""IngestionRun - operational tracking of ingestion executions."""

from django.db import models
from django.utils import timezone


class IngestionRun(models.Model):
    """Tracks each ingestion execution for observability and audit.

    Fields:
        parameters_json: Run parameters (date range, filters, etc).
    """

    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]

    FAILURE_REASON_CHOICES = [
        ("", "None"),
        ("timeout", "Timeout"),
        ("source_unavailable", "Source Unavailable"),
        ("invalid_payload", "Invalid Payload"),
        ("unexpected_exception", "Unexpected Exception"),
        ("validation_error", "Validation Error"),
    ]

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="running",
    )

    events_processed = models.PositiveIntegerField(default=0)
    events_created = models.PositiveIntegerField(default=0)
    events_skipped = models.PositiveIntegerField(default=0)
    events_revised = models.PositiveIntegerField(default=0)

    # S3 - Admission metrics
    admissions_seen = models.PositiveIntegerField(default=0)
    admissions_created = models.PositiveIntegerField(default=0)
    admissions_updated = models.PositiveIntegerField(default=0)

    parameters_json = models.JSONField(
        default=dict, blank=True,
    )
    gaps_json = models.JSONField(
        default=list, blank=True,
        help_text="List of gap windows that were extracted in this run.",
    )
    error_message = models.TextField(blank=True, default="")

    # AFMF-S2: Run intent (e.g. 'admissions_only', 'full_sync', etc.)
    intent = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Operational intent of this run (e.g. admissions_only).",
    )

    # IRMD-S1: Lifecycle observability
    queued_at = models.DateTimeField(default=timezone.now)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(
        max_length=50,
        choices=FAILURE_REASON_CHOICES,
        blank=True,
        default="",
        help_text="Normalized failure category for operational analysis.",
    )
    timed_out = models.BooleanField(
        default=False,
        help_text="Whether this run terminated due to timeout.",
    )
    worker_label = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Optional worker identifier for diagnostics.",
    )

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return (
            f"IngestionRun #{self.pk} "
            f"[{self.status}] {self.started_at}"
        )

    # -- Duration helpers (return None when data insufficient) ----------

    def _timedelta_seconds(self, start, end):
        """Return (end - start) in seconds, or None if either is None."""
        if start is None or end is None:
            return None
        return (end - start).total_seconds()

    @property
    def queue_latency_seconds(self):
        """Seconds between enqueue (queued_at) and processing start."""
        return self._timedelta_seconds(self.queued_at, self.processing_started_at)

    @property
    def processing_duration_seconds(self):
        """Seconds between processing start and finish."""
        return self._timedelta_seconds(
            self.processing_started_at, self.finished_at
        )

    @property
    def total_duration_seconds(self):
        """Seconds between enqueue (queued_at) and finish."""
        return self._timedelta_seconds(self.queued_at, self.finished_at)
