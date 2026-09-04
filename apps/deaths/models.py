"""Death report tracking model."""

from django.db import models
from django.db.models import Q

from apps.patients.models import (
    RECONCILIATION_STATUS_CHOICES,
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUSES,
)


class DailyDeathCount(models.Model):
    """Tracks the number of deaths per calendar day from the source system.

    Populated by the extract_deaths management command.
    """

    date = models.DateField(unique=True)
    count = models.IntegerField(default=0)
    raw_data = models.JSONField(
        default=list,
        blank=True,
        help_text="Raw records extracted from the CSV for this date.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "Daily Death Count"
        verbose_name_plural = "Daily Death Counts"

    def __str__(self) -> str:
        return f"{self.date}: {self.count} óbitos"


class DeathRecord(models.Model):
    """Individual death record extracted from the source system."""

    daily_count = models.ForeignKey(
        DailyDeathCount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="records",
        help_text=(
            "Report-batch link (nullable since RPSA-S3: evidence survives "
            "aggregate-row deletion; snapshot rows absent from a repeated "
            "extraction are detached, never deleted)."
        ),
    )
    date = models.DateField()
    prontuario = models.CharField(max_length=50, blank=True, default="")
    nome = models.CharField(max_length=255, blank=True, default="")
    data_obito = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Raw death date/time string exactly as extracted from the CSV.",
    )
    obito_em = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Death datetime parsed from data_obito when the source carries a "
            "complete date and time (America/Bahia); null for date-only "
            "evidence — no hour is ever synthesized."
        ),
    )
    raw_extra = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional fields from the source CSV.",
    )
    admission = models.ForeignKey(
        "patients.Admission",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="death_evidence",
        help_text="Canonical admission linked by reconciliation (null while unresolved).",
    )
    reconciliation_status = models.CharField(
        max_length=32,
        choices=RECONCILIATION_STATUS_CHOICES,
        default=RECONCILIATION_STATUS_PENDING,
        help_text="Outcome of the latest canonical exit-reconciliation attempt.",
    )
    reconciled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the latest reconciliation attempt was applied.",
    )

    class Meta:
        ordering = ["prontuario"]
        verbose_name = "Death Record"
        verbose_name_plural = "Death Records"
        constraints = [
            models.CheckConstraint(
                condition=Q(reconciliation_status__in=RECONCILIATION_STATUSES),
                name="ck_deathrecord_recon_status",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.date} {self.prontuario} — {self.nome}"
