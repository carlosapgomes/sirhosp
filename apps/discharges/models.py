"""Daily discharge tracking model (Slice S1)."""

from django.db import models
from django.db.models import Q

from apps.patients.models import (
    RECONCILIATION_STATUS_CHOICES,
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUSES,
)


class DailyDischargeCount(models.Model):
    """Tracks the number of discharges per calendar day.

    Populated by the refresh_daily_discharge_counts management command.
    """

    date = models.DateField(unique=True)
    count = models.IntegerField(default=0)
    raw_data = models.JSONField(
        default=list,
        blank=True,
        help_text="Patient records (prontuario, nome, data_internacao) for this day.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.date}: {self.count} altas"


class DischargeRecord(models.Model):
    """Individual discharge record extracted from the source system."""

    daily_count = models.ForeignKey(
        DailyDischargeCount,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="records",
        help_text=(
            "Legacy report-batch link (nullable since RPSA-S2: evidence is "
            "decoupled from the operational daily aggregate)."
        ),
    )
    alta_em = models.DateTimeField(
        null=True, blank=True,
        help_text="Datetime when the discharge was registered in the system.",
    )
    saida_em = models.DateTimeField(
        null=True, blank=True,
        help_text="Datetime when the patient left the hospital/bed.",
    )
    prontuario = models.CharField(max_length=50, blank=True, default="")
    nome = models.CharField(max_length=255, blank=True, default="")
    data_internacao = models.CharField(max_length=20, blank=True, default="")
    leito = models.CharField(
        max_length=20, blank=True, default="",
        help_text="Bed/leito at discharge (without L: prefix).",
    )
    especialidade = models.CharField(
        max_length=20, blank=True, default="",
        help_text="Medical specialty at discharge.",
    )
    raw_extra = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional fields from the source.",
    )
    admission = models.ForeignKey(
        "patients.Admission",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="discharge_evidence",
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
        verbose_name = "Discharge Record"
        verbose_name_plural = "Discharge Records"
        unique_together = [("prontuario", "data_internacao")]
        constraints = [
            models.CheckConstraint(
                condition=Q(reconciliation_status__in=RECONCILIATION_STATUSES),
                name="ck_dischargerecord_recon_status",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.prontuario} — {self.nome} ({self.alta_em or '?'})"
