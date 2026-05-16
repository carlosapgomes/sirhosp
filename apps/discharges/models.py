"""Daily discharge tracking model (Slice S1)."""

from django.db import models


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
        related_name="records",
    )
    date = models.DateField()
    prontuario = models.CharField(max_length=50, blank=True, default="")
    nome = models.CharField(max_length=255, blank=True, default="")
    data_internacao = models.CharField(max_length=20, blank=True, default="")
    leito = models.CharField(
        max_length=20, blank=True, default="",
        help_text="Bed/leito at discharge.",
    )
    especialidade = models.CharField(
        max_length=20, blank=True, default="",
        help_text="Medical specialty at discharge.",
    )
    raw_extra = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional fields from the source PDF.",
    )

    class Meta:
        ordering = ["prontuario"]
        verbose_name = "Discharge Record"
        verbose_name_plural = "Discharge Records"

    def __str__(self) -> str:
        return f"{self.date} {self.prontuario} — {self.nome}"
