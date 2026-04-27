"""Summary domain models — progressive admission summary (APS-S1).

Models:
    AdmissionSummaryState: canonical memory per admission (1:1).
    AdmissionSummaryVersion: immutable snapshot per chunk/round.
    SummaryRun: async queue entry for on-demand summarisation.
    SummaryRunChunk: fine-grained tracking per window.
"""

from django.conf import settings
from django.db import models


class AdmissionSummaryState(models.Model):
    """Canonical memory for a single admission (1:1).

    Persists both structured clinical state and the derived Markdown
    narrative.  Updated transactionally with each successful chunk.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        COMPLETE = "complete", "Complete"
        INCOMPLETE = "incomplete", "Incomplete"

    admission = models.OneToOneField(
        "patients.Admission",
        on_delete=models.CASCADE,
        related_name="summary_state",
    )

    coverage_start = models.DateField()
    coverage_end = models.DateField()

    structured_state_json = models.JSONField(default=dict)
    narrative_markdown = models.TextField(default="")

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    last_source_event_happened_at = models.DateTimeField(
        null=True, blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return (
            f"SummaryState(adm={self.admission_id}, "
            f"status={self.status}, "
            f"coverage={self.coverage_start}..{self.coverage_end})"
        )


class AdmissionSummaryVersion(models.Model):
    """Immutable snapshot saved after each successful chunk.

    Stores the full structured state, narrative, and evidence links for
    auditability.
    """

    admission = models.ForeignKey(
        "patients.Admission",
        on_delete=models.CASCADE,
        related_name="summary_versions",
    )
    summary_state = models.ForeignKey(
        AdmissionSummaryState,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    run = models.ForeignKey(
        "SummaryRun",
        on_delete=models.CASCADE,
        related_name="versions",
    )

    chunk_index = models.IntegerField()

    coverage_start = models.DateField()
    coverage_end = models.DateField()

    structured_state_json = models.JSONField(default=dict)
    narrative_markdown = models.TextField(default="")

    changes_json = models.JSONField(default=dict)
    uncertainties_json = models.JSONField(default=dict)
    evidences_json = models.JSONField(default=list)

    llm_provider = models.CharField(max_length=50, default="")
    llm_model = models.CharField(max_length=100, default="")
    prompt_version = models.CharField(max_length=50, default="")

    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["admission", "-created_at"],
                name="idx_sv_admission_created",
            ),
            models.Index(
                fields=["run", "chunk_index"],
                name="idx_sv_run_chunk",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"SummaryVersion(run={self.run_id}, "
            f"chunk={self.chunk_index}, "
            f"coverage={self.coverage_start}..{self.coverage_end})"
        )


class SummaryRun(models.Model):
    """Asynchronous on-demand summary run.

    Created by user action on the admission page.  Processed by the
    summary worker.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"

    class Mode(models.TextChoices):
        GENERATE = "generate", "Generate"
        UPDATE = "update", "Update"
        REGENERATE = "regenerate", "Regenerate"

    admission = models.ForeignKey(
        "patients.Admission",
        on_delete=models.CASCADE,
        related_name="summary_runs",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="summary_runs",
    )

    mode = models.CharField(
        max_length=20,
        choices=Mode.choices,
    )
    target_end_date = models.DateField()

    pinned_cutoff_happened_at = models.DateTimeField(
        null=True, blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )

    current_chunk_index = models.IntegerField(default=0)
    total_chunks = models.IntegerField(default=0)

    error_message = models.TextField(default="")

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "created_at"],
                name="idx_sr_status_created",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"SummaryRun(adm={self.admission_id}, "
            f"mode={self.mode}, status={self.status})"
        )


class SummaryRunChunk(models.Model):
    """Fine-grained tracking for a single window within a SummaryRun."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    run = models.ForeignKey(
        SummaryRun,
        on_delete=models.CASCADE,
        related_name="chunks",
    )

    chunk_index = models.IntegerField()

    window_start = models.DateField()
    window_end = models.DateField()

    attempt_count = models.IntegerField(default=0)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )

    error_message = models.TextField(default="")

    input_event_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["chunk_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "chunk_index"],
                name="uq_src_run_chunk",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"SummaryRunChunk(run={self.run_id}, "
            f"chunk={self.chunk_index}, "
            f"status={self.status})"
        )
