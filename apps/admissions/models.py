"""Admission report tracking model."""

from django.db import models


class DailyAdmissionCount(models.Model):
    """Tracks the number of admissions per calendar day from the source system.

    Populated by the extract_admissions management command.
    """

    date = models.DateField(unique=True)
    count = models.IntegerField(default=0)
    raw_data = models.JSONField(
        default=list,
        blank=True,
        help_text="Raw records extracted from the XLS for this date.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "Daily Admission Count"
        verbose_name_plural = "Daily Admission Counts"

    def __str__(self) -> str:
        return f"{self.date}: {self.count} admissões"


class AdmissionRecord(models.Model):
    """Individual admission record extracted from the source system."""

    daily_count = models.ForeignKey(
        DailyAdmissionCount,
        on_delete=models.CASCADE,
        related_name="records",
    )
    date = models.DateField()
    prontuario = models.CharField(max_length=50, blank=True, default="")
    nome = models.CharField(max_length=255, blank=True, default="")
    data_internacao = models.CharField(max_length=20, blank=True, default="")
    raw_extra = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional fields from the source XLS.",
    )

    class Meta:
        ordering = ["prontuario"]
        verbose_name = "Admission Record"
        verbose_name_plural = "Admission Records"

    def __str__(self) -> str:
        return f"{self.date} {self.prontuario} — {self.nome}"
