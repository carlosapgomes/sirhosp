"""Daily discharge tracking model (Slice S1)."""

from django.db import models


class DailyDischargeCount(models.Model):
    """Tracks the number of discharges per calendar day.

    Populated by the refresh_daily_discharge_counts management command.
    """

    date = models.DateField(unique=True)
    count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.date}: {self.count} altas"
