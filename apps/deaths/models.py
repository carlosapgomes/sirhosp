"""Death report tracking model."""

from django.db import models


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
        on_delete=models.CASCADE,
        related_name="records",
    )
    date = models.DateField()
    prontuario = models.CharField(max_length=50, blank=True, default="")
    nome = models.CharField(max_length=255, blank=True, default="")
    data_obito = models.CharField(max_length=20, blank=True, default="")
    raw_extra = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional fields from the source CSV.",
    )

    class Meta:
        ordering = ["prontuario"]
        verbose_name = "Death Record"
        verbose_name_plural = "Death Records"

    def __str__(self) -> str:
        return f"{self.date} {self.prontuario} — {self.nome}"
