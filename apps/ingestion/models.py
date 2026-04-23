"""IngestionRun - operational tracking of ingestion executions."""

from django.db import models


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

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return (
            f"IngestionRun #{self.pk} "
            f"[{self.status}] {self.started_at}"
        )
