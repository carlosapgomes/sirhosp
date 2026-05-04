"""Summary domain models — progressive admission summary (APS-S1, STP-S1, STP-S4, STP-S5).

Models:
    AdmissionSummaryState: canonical memory per admission (1:1).
    AdmissionSummaryVersion: immutable snapshot per chunk/round.
    SummaryRun: async queue entry for on-demand summarisation.
    SummaryRunChunk: fine-grained tracking per window.
    SummaryPipelineRun: two-phase pipeline parent run with costs in USD.
    SummaryPipelineStepRun: auditable per-phase record with prompt/payload snapshots.
    ExchangeRateSnapshot: daily USD/BRL rate from external providers.
    UserPromptTemplate: reusable prompt library with title and visibility.
"""

from decimal import Decimal

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


# ---------------------------------------------------------------------------
# Two-phase pipeline traceability (STP-S1)
# ---------------------------------------------------------------------------


class SummaryPipelineRun(models.Model):
    """Parent run for a two-phase summary pipeline execution.

    Tracks the overall request lifecycle with per-phase costs in USD.
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
        related_name="pipeline_runs",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="pipeline_runs",
    )

    mode = models.CharField(
        max_length=20,
        choices=Mode.choices,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )

    phase1_reused = models.BooleanField(default=False)

    phase1_cost_total = models.DecimalField(
        max_digits=12, decimal_places=6, default=Decimal("0.00")
    )
    phase2_cost_total = models.DecimalField(
        max_digits=12, decimal_places=6, default=Decimal("0.00")
    )
    total_cost = models.DecimalField(
        max_digits=12, decimal_places=6, default=Decimal("0.00")
    )
    currency = models.CharField(max_length=3, default="USD")

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
                name="idx_spr_status_created",
            ),
        ]

    def save(self, *args, **kwargs):
        self.total_cost = self.phase1_cost_total + self.phase2_cost_total
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            # Ensure total_cost is persisted even when caller passes a
            # custom update_fields that omits it.
            update_fields_set = set(update_fields)
            update_fields_set.add("total_cost")
            kwargs["update_fields"] = update_fields_set
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return (
            f"SummaryPipelineRun(adm={self.admission_id}, "
            f"mode={self.mode}, status={self.status})"
        )


class SummaryPipelineStepRun(models.Model):
    """Auditable record for a single phase call within a pipeline run.

    Stores full prompt/payload/response snapshots and per-call cost in USD.
    """

    class StepType(models.TextChoices):
        PHASE1_CANONICAL = "phase1_canonical", "Phase 1 — Canonical"
        PHASE2_RENDER = "phase2_render", "Phase 2 — Render"

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    pipeline_run = models.ForeignKey(
        SummaryPipelineRun,
        on_delete=models.CASCADE,
        related_name="step_runs",
    )

    step_type = models.CharField(
        max_length=30,
        choices=StepType.choices,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
    )

    # Provider / model identity
    provider_name = models.CharField(max_length=50, default="")
    model_name = models.CharField(max_length=100, default="")
    base_url = models.CharField(max_length=500, default="")

    # Prompt traceability
    prompt_version = models.CharField(max_length=50, default="")
    prompt_text_snapshot = models.TextField(default="")

    # Full payload snapshots (immutable)
    request_payload_json = models.JSONField(default=dict)
    response_payload_json = models.JSONField(default=dict)

    # Token usage
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    cached_tokens = models.IntegerField(default=0)

    # Costs in USD
    cost_input = models.DecimalField(
        max_digits=12, decimal_places=6, default=Decimal("0.00")
    )
    cost_output = models.DecimalField(
        max_digits=12, decimal_places=6, default=Decimal("0.00")
    )
    cost_total = models.DecimalField(
        max_digits=12, decimal_places=6, default=Decimal("0.00")
    )

    # Observability
    latency_ms = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(default="")

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["started_at"]
        indexes = [
            models.Index(
                fields=["pipeline_run", "step_type"],
                name="idx_spsr_run_type",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"SummaryPipelineStepRun(run={self.pipeline_run_id}, "
            f"step={self.step_type}, status={self.status})"
        )


# ---------------------------------------------------------------------------
# Exchange rate tracking (STP-S4)
# ---------------------------------------------------------------------------


class ExchangeRateSnapshot(models.Model):
    """Daily USD/BRL exchange rate from an external provider.

    Persisted by `sync_exchange_rates` management command.  The UI uses the
    latest available rate at view time for BRL cost display.
    """

    base_currency = models.CharField(max_length=3, default="USD")
    quote_currency = models.CharField(max_length=3, default="BRL")
    rate = models.DecimalField(max_digits=12, decimal_places=6)
    reference_date = models.DateField()
    provider = models.CharField(max_length=50)
    fetched_at = models.DateTimeField()

    class Meta:
        ordering = ["-reference_date"]
        indexes = [
            models.Index(
                fields=["reference_date"],
                name="idx_ers_ref_date",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["base_currency", "quote_currency", "reference_date"],
                name="uq_ers_currency_date",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"ExchangeRateSnapshot(USD/BRL={self.rate} "
            f"on {self.reference_date} via {self.provider})"
        )


# ---------------------------------------------------------------------------
# Prompt library (STP-S5)
# ---------------------------------------------------------------------------


class UserPromptTemplate(models.Model):
    """Reusable custom prompt for phase-2 summary rendering.

    Each user can create private/public prompts with a mandatory title.
    Public prompts are visible to all authenticated users but only the
    owner can edit or delete.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="prompt_templates",
    )
    title = models.CharField(max_length=200)
    content = models.TextField()
    is_public = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        visibility = "public" if self.is_public else "private"
        return (
            f"UserPromptTemplate(owner={self.owner_id}, "
            f"title={self.title!r}, {visibility})"
        )
