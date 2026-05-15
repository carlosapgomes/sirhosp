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
