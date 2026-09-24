"""Materialized daily statistics projection (DSRS-S2).

The projection is owned by the reporting module: source facts stay in the
census, ingestion and clinical apps, while this app persists only the
reproducible daily revision. One revision pins the accepted anchor, opening and
closing census runs, the exact closing occupancy measurement, the historical
catalog context, a deterministic source fingerprint and the quality metadata of
the selected window. Sectors copy the metrics already persisted by that exact
measurement and patients are the nominal rows of the closing census
photograph; nothing here recalculates official capacity, occupancy, balance or
excess.
"""

from __future__ import annotations

from django.db import models

from apps.census.models import (
    CapacityCatalogVersion,
    CensusSnapshot,
    OccupancyCalculationStatus,
    OccupancyMeasurement,
)


class DailyStatisticsReportStatus(models.TextChoices):
    """Publication state of one daily statistics revision."""

    READY = "ready", "Ready"
    SUPERSEDED = "superseded", "Superseded"


class DailyStatisticsReport(models.Model):
    """One reproducible revision of the daily statistics report.

    At most one revision per local date is ``ready``: a newer revision
    supersedes the previous one without mutating its content. Dates before the
    declared activation boundary are never materialized.
    """

    local_date = models.DateField(
        help_text="Local calendar date (America/Bahia) this revision reports",
    )
    revision = models.PositiveIntegerField(
        default=1,
        help_text="1-based revision of this local date, increasing over time",
    )
    status = models.CharField(
        max_length=20,
        choices=DailyStatisticsReportStatus.choices,
        default=DailyStatisticsReportStatus.READY,
        help_text="Publication state of this revision",
    )
    activation_date = models.DateField(
        help_text=(
            "First eligible local date declared for the feature when this "
            "revision was materialized"
        ),
    )
    anchor_run = models.ForeignKey(
        "ingestion.IngestionRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="anchored_statistics_reports",
        help_text=(
            "Last accepted census before the opening photograph; null when no "
            "accepted anchor existed"
        ),
    )
    opening_run = models.ForeignKey(
        "ingestion.IngestionRun",
        on_delete=models.PROTECT,
        related_name="opened_statistics_reports",
        help_text="Accepted opening census extraction run of the day",
    )
    closing_run = models.ForeignKey(
        "ingestion.IngestionRun",
        on_delete=models.PROTECT,
        related_name="closed_statistics_reports",
        help_text="Accepted closing census extraction run of the day",
    )
    measurement = models.ForeignKey(
        OccupancyMeasurement,
        on_delete=models.PROTECT,
        related_name="daily_statistics_reports",
        help_text="Exact immutable closing measurement this revision copies",
    )
    catalog = models.ForeignKey(
        CapacityCatalogVersion,
        on_delete=models.PROTECT,
        related_name="daily_statistics_reports",
        help_text="Historical catalog of the closing measurement",
    )
    algorithm_version = models.CharField(
        max_length=30,
        help_text="Occupancy algorithm of the exact closing measurement",
    )
    source_fingerprint = models.CharField(
        max_length=64,
        help_text=(
            "SHA-256 of the normalized sources used by this revision; an "
            "unchanged fingerprint makes a rebuild a no-op"
        ),
    )
    quality_warnings_json = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Structured quality warnings of the selected window, such as a "
            "missing accepted anchor census; aggregate codes only"
        ),
    )
    generated_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Instant this revision was materialized",
    )

    class Meta:
        ordering = ["local_date", "revision"]
        constraints = [
            models.UniqueConstraint(
                fields=["local_date", "revision"],
                name="uq_daily_statistics_report_date_revision",
            ),
            models.UniqueConstraint(
                fields=["local_date"],
                condition=models.Q(
                    status=DailyStatisticsReportStatus.READY
                ),
                name="uq_daily_statistics_report_current_ready",
            ),
            models.CheckConstraint(
                condition=models.Q(revision__gte=1),
                name="ck_daily_statistics_report_revision_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(local_date__gte=models.F("activation_date")),
                name="ck_daily_statistics_report_after_activation",
            ),
        ]
        indexes = [
            models.Index(
                fields=["local_date", "status"],
                name="dsr_date_status_idx",
            ),
        ]
        verbose_name = "Daily Statistics Report"
        verbose_name_plural = "Daily Statistics Reports"

    def __str__(self) -> str:
        return (
            f"DailyStatisticsReport {self.local_date} "
            f"rev {self.revision} [{self.status}]"
        )


class DailyStatisticsSector(models.Model):
    """One official grouping of the closing measurement inside one revision.

    Every value is copied from the exact immutable group measurement of the
    closing census run; no capacity, occupancy, balance or excess is
    recalculated for the report.
    """

    report = models.ForeignKey(
        DailyStatisticsReport,
        on_delete=models.CASCADE,
        related_name="sectors",
    )
    stable_key = models.CharField(
        max_length=100,
        help_text="Historical stable official key of the group",
    )
    display_name = models.CharField(
        max_length=255,
        help_text="Historical display name of the group",
    )
    calculation_policy = models.CharField(max_length=30, blank=True, default="")
    calculation_status = models.CharField(
        max_length=30,
        choices=OccupancyCalculationStatus.choices,
    )
    official_capacity = models.PositiveIntegerField(null=True, blank=True)
    occupied_count = models.PositiveIntegerField(null=True, blank=True)
    occupancy_percentage = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    exceeded_by = models.PositiveIntegerField(null=True, blank=True)
    official_availability = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["report", "stable_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["report", "stable_key"],
                name="uq_daily_statistics_sector_report_key",
            ),
        ]
        verbose_name = "Daily Statistics Sector"
        verbose_name_plural = "Daily Statistics Sectors"

    def __str__(self) -> str:
        return f"{self.stable_key} @ report {self.report_id}"


class DailyStatisticsPatient(models.Model):
    """One nominal patient row of the closing census photograph.

    Only the fields the report needs are duplicated; provenance points to the
    exact census snapshot of the closing run.
    """

    report = models.ForeignKey(
        DailyStatisticsReport,
        on_delete=models.CASCADE,
        related_name="patients",
    )
    sector = models.ForeignKey(
        DailyStatisticsSector,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="patients",
        help_text=(
            "Official grouping of the closing census; null keeps a safely "
            "unidentified grouping explicit"
        ),
    )
    census_snapshot = models.ForeignKey(
        CensusSnapshot,
        on_delete=models.PROTECT,
        related_name="daily_statistics_patients",
        help_text="Exact closing census row this patient was copied from",
    )
    bed = models.CharField(max_length=50)
    name = models.CharField(max_length=512)
    record = models.CharField(max_length=255)
    specialty = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["report", "sector", "census_snapshot"]
        constraints = [
            models.UniqueConstraint(
                fields=["report", "census_snapshot"],
                name="uq_daily_statistics_patient_report_snapshot",
            ),
        ]
        verbose_name = "Daily Statistics Patient"
        verbose_name_plural = "Daily Statistics Patients"

    def __str__(self) -> str:
        return f"{self.record} @ {self.bed} report {self.report_id}"
