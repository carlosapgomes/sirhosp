"""Materialized daily statistics projection (DSRS-S2, DSRS-S3, DSRS-S4).

The projection is owned by the reporting module: source facts stay in the
census, ingestion and clinical apps, while this app persists only the
reproducible daily revision. One revision pins the accepted anchor, opening and
closing census runs, the exact closing occupancy measurement, the historical
catalog context, a deterministic source fingerprint and the quality metadata of
the selected window. Sectors copy the metrics already persisted by that exact
measurement and patients are the nominal rows of the closing census
photograph; nothing here recalculates official capacity, occupancy, balance or
excess. Detected entries, internal transfers and classified exits are one
durable event row per logical fact, with the event's own origin classification,
clinical instant or date when a source provides one, detection interval,
attributed sector quality and deterministic fingerprint.
"""

from __future__ import annotations

from django.db import models

from apps.census.models import (
    CapacityCatalogVersion,
    CensusSnapshot,
    OccupancyCalculationStatus,
    OccupancyMeasurement,
)
from apps.statistics_reports.origin_policy import OriginNature


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
        permissions = [
            (
                "view_daily_statistics",
                "Can view the daily statistics report",
            ),
            (
                "export_daily_statistics",
                "Can export the daily statistics report",
            ),
        ]

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


class DailyStatisticsEventKind(models.TextChoices):
    """Stable normalized kind of one detected report event.

    A confirmed internal transfer is one single kind: both legs live in the
    same event row instead of being duplicated as independent facts. Exits keep
    the deterministic precedence death, effective hospital discharge, internal
    transfer, unclassified departure, so one episode is counted once.
    """

    HOSPITAL_ADMISSION = "hospital_admission", "Internação hospitalar"
    INTERNAL_TRANSFER = "internal_transfer", "Transferência interna"
    DEATH = "death", "Óbito"
    HOSPITAL_DISCHARGE = "hospital_discharge", "Alta hospitalar"
    UNCLASSIFIED_ENTRY = (
        "unclassified_entry",
        "Entrada no setor — origem não identificada",
    )
    UNCLASSIFIED_DEPARTURE = (
        "unclassified_departure",
        "Saída do setor — destino não identificado",
    )


EXIT_EVENT_KINDS: tuple[str, ...] = (
    DailyStatisticsEventKind.DEATH,
    DailyStatisticsEventKind.HOSPITAL_DISCHARGE,
    DailyStatisticsEventKind.UNCLASSIFIED_DEPARTURE,
)
"""Event kinds that report a patient leaving, without a destination sector.

They may stay without any endpoint when no unambiguous earlier census position
existed; every other kind still requires one endpoint.
"""


class DailyStatisticsSectorAttribution(models.TextChoices):
    """How the sector one detected event stores was determined.

    ``observed`` means the stored sector comes from the detecting census
    photograph. ``inferred_last_census`` means the event itself carries no
    sector (a clinical exit evidence or a disappearance) and the sector comes
    only from the last unambiguous census position. ``unknown`` keeps an exit
    without any trustworthy prior position explicit instead of inventing it.
    """

    OBSERVED = "observed", "Observado na fotografia de detecção"
    INFERRED_LAST_CENSUS = (
        "inferred_last_census",
        "Inferido da última posição censitária",
    )
    UNKNOWN = "unknown", "Não determinado"


class DailyStatisticsEvent(models.Model):
    """One detected logical event of a revision.

    A sector change is stored once, carrying origin and destination, and is
    read as the origin's exit and as the destination's entry. The origin
    classification records the policy version and the normalized source value
    that produced it, so an entry never becomes an admission silently. An exit
    is classified once, by the global precedence of its episode, and carries
    the clinical instant or date of the evidence that explained it. Clinical
    time stays distinct from detection: a transition only observed between two
    census photographs keeps its detection interval and stores no synthesized
    instant, and the attributed sector records how it was determined. An exit
    explained by persisted clinical evidence also keeps the inspectable
    provenance of the chosen row (source kind and primary key, without a foreign
    key), while a fact the census photographs alone proved keeps both null and
    never claims evidence it did not use.
    """

    report = models.ForeignKey(
        DailyStatisticsReport,
        on_delete=models.CASCADE,
        related_name="events",
    )
    kind = models.CharField(
        max_length=30,
        choices=DailyStatisticsEventKind.choices,
        help_text="Stable normalized kind of the detected fact",
    )
    origin_nature = models.CharField(
        max_length=30,
        choices=OriginNature.choices,
        default=OriginNature.UNKNOWN,
        help_text="Institutional nature attributed to the event origin",
    )
    origin_value = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=(
            "Normalized source origin value the classification used; empty "
            "when the origin came from a census position instead"
        ),
    )
    origin_policy_version = models.CharField(
        max_length=30,
        help_text=(
            "Version of the origin policy in force when this event was "
            "derived; stored for audit even when the origin came from a "
            "resolved census position"
        ),
    )
    origin_sector = models.ForeignKey(
        DailyStatisticsSector,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="origin_events",
        help_text=(
            "Official grouping the patient left; null keeps an unidentified "
            "origin explicit instead of inventing it"
        ),
    )
    destination_sector = models.ForeignKey(
        DailyStatisticsSector,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="destination_events",
        help_text=(
            "Official grouping the patient reached; null keeps an "
            "unidentified destination explicit instead of inventing it"
        ),
    )
    census_snapshot = models.ForeignKey(
        CensusSnapshot,
        on_delete=models.PROTECT,
        related_name="daily_statistics_events",
        help_text="Detecting census row this event was observed on",
    )
    record = models.CharField(
        max_length=255,
        help_text="Normalized patient record of the detecting row",
    )
    name = models.CharField(
        max_length=512,
        help_text="Nominal patient name at detection time",
    )
    bed = models.CharField(
        max_length=50,
        help_text="Bed of the detecting row",
    )
    occurred_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Exact aware clinical instant when the source provides one; null "
            "never synthesizes an hour"
        ),
    )
    occurred_on = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Clinical date when only a date exists, without an hour; null "
            "never synthesizes a clinical date"
        ),
    )
    source_kind = models.CharField(
        max_length=30,
        null=True,
        blank=True,
        help_text=(
            "Stable source kind of the clinical exit evidence that explained "
            "this event (e.g. death_record); null when only the census "
            "photographs proved it, so no evidence is ever claimed"
        ),
    )
    source_pk = models.BigIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Primary key of that clinical evidence row, kept as an "
            "inspectable provenance reference without a foreign key; null "
            "when no clinical evidence explained this event"
        ),
    )
    detected_not_before = models.DateTimeField(
        help_text="Instant of the accepted census photograph before the change",
    )
    detected_at = models.DateTimeField(
        help_text="Instant of the accepted census photograph detecting the change",
    )
    sector_attribution = models.CharField(
        max_length=30,
        choices=DailyStatisticsSectorAttribution.choices,
        default=DailyStatisticsSectorAttribution.OBSERVED,
        help_text=(
            "How the sector this event stores was determined: observed in the "
            "detecting photograph, inferred from the last unambiguous census "
            "position when the event itself carries no sector, or not "
            "determined"
        ),
    )
    fingerprint = models.CharField(
        max_length=64,
        help_text=(
            "Deterministic SHA-256 identity of this detected fact inside its "
            "revision"
        ),
    )

    class Meta:
        ordering = ["report", "detected_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["report", "fingerprint"],
                name="uq_daily_statistics_event_report_fingerprint",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=EXIT_EVENT_KINDS)
                | models.Q(origin_sector__isnull=False)
                | models.Q(destination_sector__isnull=False),
                name="ck_daily_statistics_event_has_endpoint",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    detected_at__gte=models.F("detected_not_before")
                ),
                name="ck_daily_statistics_event_detection_order",
            ),
        ]
        indexes = [
            models.Index(
                fields=["report", "kind"],
                name="dse_report_kind_idx",
            ),
            models.Index(
                fields=["report", "origin_sector"],
                name="dse_report_origin_idx",
            ),
            models.Index(
                fields=["report", "destination_sector"],
                name="dse_report_dest_idx",
            ),
        ]
        verbose_name = "Daily Statistics Event"
        verbose_name_plural = "Daily Statistics Events"

    def __str__(self) -> str:
        return (
            f"{self.kind} {self.record} @ {self.bed} "
            f"report {self.report_id}"
        )
