"""IngestionRun, CensusExecutionBatch, IngestionRunAttempt,
FinalRunFailure, and IngestionRunStageMetric - operational tracking."""

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

    # CQM-S1: batch and retry fields
    batch = models.ForeignKey(
        "CensusExecutionBatch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
        help_text="Census execution batch this run belongs to.",
    )
    attempt_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of execution attempts so far (starts at 0).",
    )
    max_attempts = models.PositiveSmallIntegerField(
        default=3,
        help_text="Maximum execution attempts before final failure.",
    )
    next_retry_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Earliest datetime for the next retry attempt.",
    )

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


class CensusExecutionBatch(models.Model):
    """Tracks a complete census execution cycle from enqueue to drain.

    Created when process_census_snapshot starts enqueuing runs.
    Closed when no queued/running runs remain in the batch.
    """

    STATUS_CHOICES = [
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]

    started_at = models.DateTimeField(auto_now_add=True)
    enqueue_finished_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Moment when all initial runs were enqueued.",
    )
    finished_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Moment when the batch was fully drained.",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="running",
    )
    notes_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional batch-level context (snapshot_id, counts, etc.).",
    )

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"CensusExecutionBatch #{self.pk} [{self.status}]"

    @property
    def total_duration_seconds(self):
        """Seconds between enqueue_finished_at and finished_at."""
        if self.enqueue_finished_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.enqueue_finished_at).total_seconds()


class IngestionRunAttempt(models.Model):
    """Per-attempt execution record for a single IngestionRun.

    One row per retry attempt; the final attempt that exhausts retries
    has status='failed' and triggers a FinalRunFailure.
    """

    STATUS_CHOICES = [
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]

    FAILURE_REASON_CHOICES = IngestionRun.FAILURE_REASON_CHOICES

    run = models.ForeignKey(
        IngestionRun,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    attempt_number = models.PositiveSmallIntegerField(
        help_text="1-based attempt index (1, 2, or 3).",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="succeeded",
    )
    failure_reason = models.CharField(
        max_length=50,
        choices=FAILURE_REASON_CHOICES,
        blank=True,
        default="",
        help_text="Normalized failure category for this attempt.",
    )
    timed_out = models.BooleanField(
        default=False,
        help_text="Whether this attempt terminated due to timeout.",
    )
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="Free-text error context for this attempt.",
    )

    class Meta:
        ordering = ["started_at"]

    def __str__(self) -> str:
        return (
            f"IngestionRunAttempt #{self.pk} "
            f"run={self.run_id} "
            f"attempt={self.attempt_number} "
            f"[{self.status}]"
        )


class FinalRunFailure(models.Model):
    """Materialised record of a run that exhausted all retry attempts.

    One row per (batch, run) for operational analysis of edge cases.
    """

    batch = models.ForeignKey(
        CensusExecutionBatch,
        on_delete=models.CASCADE,
        related_name="final_failures",
    )
    run = models.OneToOneField(
        IngestionRun,
        on_delete=models.CASCADE,
        related_name="final_failure",
    )
    patient_record = models.CharField(
        max_length=100,
        help_text="Patient identifier from the source system.",
    )
    intent = models.CharField(
        max_length=50,
        help_text="Operational intent that failed (e.g. admissions_only).",
    )
    failed_at = models.DateTimeField(auto_now_add=True)
    attempts_exhausted = models.PositiveSmallIntegerField(
        help_text="Total attempts tried before this final failure.",
    )

    class Meta:
        ordering = ["-failed_at"]

    def __str__(self) -> str:
        return (
            f"FinalRunFailure #{self.pk} "
            f"patient={self.patient_record} "
            f"intent={self.intent}"
        )


class IngestionRunStageMetric(models.Model):
    """Per-stage execution metrics for an IngestionRun.

    Captures start/end timestamps and outcome for each critical
    execution stage, enabling operational diagnostics at stage level.

    Stages tracked:
        - admissions_capture
        - gap_planning
        - evolution_extraction
        - ingestion_persistence
    """

    STAGE_STATUS_CHOICES = [
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("skipped", "Skipped"),
    ]

    run = models.ForeignKey(
        IngestionRun,
        on_delete=models.CASCADE,
        related_name="stage_metrics",
    )
    stage_name = models.CharField(max_length=50)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STAGE_STATUS_CHOICES,
        default="succeeded",
    )
    details_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional stage-level context (counters, gaps count, etc.).",
    )

    class Meta:
        ordering = ["started_at"]
        indexes = [
            models.Index(fields=["run", "stage_name"]),
            models.Index(fields=["stage_name", "status"]),
        ]

    def __str__(self) -> str:
        return (
            f"StageMetric #{self.pk} "
            f"run={self.run_id} "
            f"stage={self.stage_name} "
            f"[{self.status}]"
        )
