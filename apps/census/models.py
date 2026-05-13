from __future__ import annotations

from django.db import models


class BedStatus(models.TextChoices):
    OCCUPIED = "occupied", "Ocupado"
    EMPTY = "empty", "Vago"
    MAINTENANCE = "maintenance", "Em Manutenção"
    RESERVED = "reserved", "Reservado"
    ISOLATION = "isolation", "Isolamento"


class CensusSnapshot(models.Model):
    """Single row from a daily inpatient census extraction.

    Each row represents one bed in one sector at the moment of capture.
    Beds without a patient (empty, maintenance, reserved, isolation) have
    empty prontuario and a descriptive nome.
    """

    captured_at = models.DateTimeField(
        help_text="Timestamp when this census run was captured"
    )
    ingestion_run = models.ForeignKey(
        "ingestion.IngestionRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="census_snapshots",
        help_text="Optional link to the ingestion run that produced this snapshot",
    )

    setor = models.CharField(
        max_length=255,
        help_text="Sector/ward name as it appears in the source system",
    )
    leito = models.CharField(
        max_length=50,
        help_text="Bed identifier (e.g. I10CA, CV01A)",
    )
    prontuario = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Patient record number (empty for non-occupied beds)",
    )
    nome = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Patient name or bed status label (e.g. DESOCUPADO, RESERVA INTERNA)",
    )
    especialidade = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Medical specialty abbreviation (e.g. NEF, CIV, PED)",
    )
    bed_status = models.CharField(
        max_length=20,
        choices=BedStatus.choices,
        help_text="Classified bed status",
    )

    class Meta:
        ordering = ["-captured_at", "setor", "leito"]
        indexes = [
            models.Index(fields=["captured_at"], name="census_captured_idx"),
            models.Index(fields=["setor"], name="census_setor_idx"),
            models.Index(fields=["prontuario"], name="census_pront_idx"),
            models.Index(
                fields=["captured_at", "bed_status"],
                name="census_capt_bstat_idx",
            ),
        ]
        verbose_name = "Census Snapshot"
        verbose_name_plural = "Census Snapshots"

    def __str__(self) -> str:
        return (
            f"{self.setor} / {self.leito} "
            f"[{self.bed_status}] "
            f"{self.prontuario or '-'} "
            f"@ {self.captured_at:%Y-%m-%d %H:%M}"
        )


class Ward(models.Model):
    """Hospital unit/ward registry from the official bed catalog.

    Extracted from the 'Cadastro de leitos por Clínica / Unidade' PDF.
    The source_code matches the numeric codes used in the official census.
    """

    source_code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Numeric unit code from source system (e.g. '640').",
    )
    name = models.CharField(
        max_length=255,
        help_text="Unit display name (e.g. '01 6 - 1A - CIRURGIA GERAL - HGRS').",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["source_code"]
        verbose_name = "Ward"
        verbose_name_plural = "Wards"

    def __str__(self) -> str:
        return f"[{self.source_code}] {self.name}"


class Bed(models.Model):
    """Hospital bed registry from the official bed catalog.

    Each bed belongs to a Ward. Beds can be activated/deactivated
    across catalog updates.
    """

    ward = models.ForeignKey(
        Ward,
        on_delete=models.CASCADE,
        related_name="beds",
    )
    code = models.CharField(
        max_length=50,
        help_text="Bed identifier (e.g. '101AA', 'UC01A').",
    )
    status = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Status code from source system (meaning TBD).",
    )
    accommodation = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Accommodation type (e.g. 'ENFERMARIA', 'UTI').",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="True if Ativo='A', False if Ativo='I'.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ward", "code"],
                name="uq_bed_ward_code",
            ),
        ]
        ordering = ["ward", "code"]
        verbose_name = "Bed"
        verbose_name_plural = "Beds"

    def __str__(self) -> str:
        active = "A" if self.is_active else "I"
        return f"{self.code} [{active}] @ {self.ward.name}"
