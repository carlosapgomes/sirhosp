from __future__ import annotations

from django.db import models


class CalculationPolicy(models.TextChoices):
    STANDARD = "standard", "Standard"
    LINKED_SLOTS_PENDING = "linked_slots_pending", "Linked slots pending"
    UNRATED = "unrated", "Unrated"


class CapacityCatalogVersion(models.Model):
    """Immutable complete capacity catalog snapshot for one local date.

    Published only for future local dates in ``America/Bahia`` through the
    ``activate_sector_capacity_catalog`` command. One version per effective
    date; changes require a new future version.
    """

    effective_from = models.DateField(
        unique=True,
        help_text="First local calendar date (America/Bahia) this catalog applies",
    )
    source_reference = models.CharField(
        max_length=255,
        help_text="Human-readable provenance of the published document",
    )
    source_sha256 = models.CharField(
        max_length=64,
        help_text="SHA-256 of the input JSON document",
    )
    schema_version = models.CharField(
        max_length=20,
        help_text="Version of the catalog document schema",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["effective_from"]
        verbose_name = "Capacity Catalog Version"
        verbose_name_plural = "Capacity Catalog Versions"

    def __str__(self) -> str:
        return (
            f"CapacityCatalogVersion {self.effective_from}"
            f" ({self.source_sha256[:12]})"
        )


class CapacityGroupDefinition(models.Model):
    """One official capacity group inside a catalog version."""

    catalog = models.ForeignKey(
        CapacityCatalogVersion,
        on_delete=models.PROTECT,
        related_name="groups",
    )
    stable_key = models.CharField(
        max_length=100,
        help_text="Official identity of the sector series within the version",
    )
    display_name = models.CharField(
        max_length=255,
        help_text="Official display name resolved at publication time",
    )
    official_capacity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Official capacity; null only for unrated groups",
    )
    calculation_policy = models.CharField(
        max_length=30,
        choices=CalculationPolicy.choices,
        help_text="How occupancy is calculated for this group",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["catalog", "stable_key"],
                name="uq_capacity_group_catalog_stable_key",
            ),
            models.CheckConstraint(
                condition=models.Q(official_capacity__gt=0)
                | models.Q(official_capacity__isnull=True),
                name="ck_capacity_group_capacity_positive_or_null",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        calculation_policy=CalculationPolicy.UNRATED,
                        official_capacity__isnull=True,
                    )
                    | models.Q(
                        calculation_policy__in=[
                            CalculationPolicy.STANDARD,
                            CalculationPolicy.LINKED_SLOTS_PENDING,
                        ],
                        official_capacity__isnull=False,
                        official_capacity__gt=0,
                    )
                ),
                name="ck_capacity_group_policy_capacity_v2",
            ),
        ]
        ordering = ["catalog", "stable_key"]
        verbose_name = "Capacity Group Definition"
        verbose_name_plural = "Capacity Group Definitions"

    def __str__(self) -> str:
        return f"{self.stable_key} ({self.calculation_policy}) @ {self.catalog}"


class CapacitySectorMembership(models.Model):
    """Associates one source code with a capacity group within one version."""

    catalog = models.ForeignKey(
        CapacityCatalogVersion,
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    group = models.ForeignKey(
        CapacityGroupDefinition,
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    source_code = models.CharField(
        max_length=50,
        help_text="Numeric source code from the legacy system census",
    )
    configured_source_name = models.CharField(
        max_length=255,
        help_text="Sector name configured for this code in this version",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["catalog", "source_code"],
                name="uq_capacity_member_catalog_source_code",
            ),
        ]
        ordering = ["catalog", "source_code"]
        verbose_name = "Capacity Sector Membership"
        verbose_name_plural = "Capacity Sector Memberships"

    def __str__(self) -> str:
        return f"{self.source_code} -> {self.group.stable_key} @ {self.catalog}"


class OccupancyCalculationStatus(models.TextChoices):
    CALCULATED = "calculated", "Calculated"
    LINKED_SLOTS_PENDING = "linked_slots_pending", "Linked slots pending"
    UNRATED = "unrated", "Unrated"
    UNMAPPED = "unmapped", "Unmapped"


class OccupancyMeasurement(models.Model):
    """Immutable aggregate occupancy evidence for one census extraction run."""

    census_run = models.OneToOneField(
        "ingestion.IngestionRun",
        on_delete=models.PROTECT,
        related_name="occupancy_measurement",
    )
    catalog = models.ForeignKey(
        CapacityCatalogVersion,
        on_delete=models.PROTECT,
        related_name="occupancy_measurements",
    )
    captured_at = models.DateTimeField()
    local_date = models.DateField()
    algorithm_version = models.CharField(max_length=30)
    observed_sector_count = models.PositiveIntegerField()
    capacity_covered_sector_count = models.PositiveIntegerField()
    calculable_sector_count = models.PositiveIntegerField()
    known_capacity = models.PositiveIntegerField()
    calculable_capacity = models.PositiveIntegerField()
    occupied_for_rate = models.PositiveIntegerField()
    occupancy_percentage = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    exceeded_by = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    capacity_covered_sector_count__lte=models.F(
                        "observed_sector_count"
                    ),
                    calculable_sector_count__lte=models.F(
                        "observed_sector_count"
                    ),
                ),
                name="ck_occupancy_coverage_within_observed",
            ),
            models.CheckConstraint(
                condition=models.Q(occupancy_percentage__gte=0)
                | models.Q(occupancy_percentage__isnull=True),
                name="ck_occupancy_percentage_nonnegative",
            ),
        ]
        indexes = [
            models.Index(
                fields=["local_date", "captured_at"],
                name="occupancy_local_capture_idx",
            ),
        ]
        ordering = ["captured_at", "pk"]
        verbose_name = "Occupancy Measurement"
        verbose_name_plural = "Occupancy Measurements"

    def __str__(self) -> str:
        return f"OccupancyMeasurement run={self.census_run_id} @ {self.captured_at}"


class OccupancyGroupMeasurement(models.Model):
    """Resolved historical group values copied from one applicable catalog."""

    measurement = models.ForeignKey(
        OccupancyMeasurement,
        on_delete=models.CASCADE,
        related_name="groups",
    )
    stable_key = models.CharField(max_length=100)
    display_name = models.CharField(max_length=255)
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
    status_counts_json = models.JSONField(default=dict)
    components_json = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["measurement", "stable_key"],
                name="uq_occupancy_group_measurement_key",
            ),
            models.CheckConstraint(
                condition=models.Q(official_capacity__gt=0)
                | models.Q(official_capacity__isnull=True),
                name="ck_occupancy_group_capacity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(occupancy_percentage__gte=0)
                | models.Q(occupancy_percentage__isnull=True),
                name="ck_occupancy_group_percentage_nonnegative",
            ),
        ]
        ordering = ["measurement", "stable_key"]
        verbose_name = "Occupancy Group Measurement"
        verbose_name_plural = "Occupancy Group Measurements"

    def __str__(self) -> str:
        return f"{self.stable_key} @ measurement {self.measurement_id}"


class PatientMovement(models.Model):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE,
        related_name="movements",
    )
    admission = models.ForeignKey(
        "patients.Admission", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="movements",
    )
    movement_date = models.DateField(
        help_text="Data da movimentação (do censo)",
    )
    sector = models.CharField(
        max_length=255, help_text="Setor atual",
    )
    bed = models.CharField(max_length=50, blank=True, default="")
    origin = models.CharField(
        max_length=100, blank=True, default="",
        help_text="Setor de origem (campo Origem do censo)",
    )
    discharge_type = models.CharField(
        max_length=50, blank=True, default="",
        help_text="Tipo de alta (vazio = ativo)",
    )
    sequence = models.IntegerField(
        default=0,
        help_text="Ordem cronológica dentro da admissão",
    )
    first_seen_at = models.DateTimeField(
        help_text="Primeiro snapshot que capturou este estado",
    )
    last_seen_at = models.DateTimeField(
        help_text="Último snapshot (atualizado a cada repetição)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["patient", "movement_date", "sector"],
                name="uq_patient_movement_date_sector",
            ),
        ]
        ordering = ["patient", "sequence"]
        indexes = [
            models.Index(fields=["sector", "last_seen_at"]),
            models.Index(fields=["patient", "sequence"]),
            models.Index(fields=["discharge_type"]),
        ]
        verbose_name = "Patient Movement"
        verbose_name_plural = "Patient Movements"

    def __str__(self) -> str:
        discharge = f" → {self.discharge_type}" if self.discharge_type else ""
        return (
            f"[{self.movement_date}] {self.patient} @ {self.sector}"
            f"{discharge}"
        )


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
    setor_codigo = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Numeric ward code from the source system (e.g. '640').",
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
    data_internacao = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Admission date from the census table (DD/MM or DD/MM/AAAA)",
    )
    tempo_internacao = models.IntegerField(
        blank=True,
        null=True,
        help_text="Length of stay in days from the census table (numeric)",
    )
    data_movimentacao = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Date of last movement (DD/MM or DD/MM/AAAA)",
    )
    tipo_alta = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text=(
            "Discharge type code: A=alta médica, "
            "G=alta administrativa, I=desistiu tratamento"
        ),
    )
    origem = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Origin sector/bed code from the last movement",
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


class Specialty(models.Model):
    """Medical specialty reference table.

    Populated from the AGHU source system specialty catalog.
    Admin-managed via Django admin.
    """

    code = models.CharField(
        max_length=20,
        unique=True,
        help_text="Specialty abbreviation (e.g. CIV, NEF, CAR)",
    )
    name = models.CharField(
        max_length=255,
        help_text="Full specialty name (e.g. CIRURGIA VASCULAR)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Specialty"
        verbose_name_plural = "Specialties"

    def __str__(self) -> str:
        return f"[{self.code}] {self.name}"


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


class OfficialCensusRecord(models.Model):
    """Single row from the official daily census file.

    Generated by the 'Gerar Arquivos' report in the source system.
    The data comes from a semicolon-delimited TXT inside a ZIP file.

    Columns: PRONTUARIO;NOME;DATA INTERNACAO;TEMPO INT;QUARTO/LEITO;
             CID INT;DESCRICAO;UNIDADE;AREA FUNCIONAL;SIGLA;ESPECIALIDADE
    """

    date = models.DateField(
        help_text="Census date this record refers to",
    )
    ingestion_run = models.ForeignKey(
        "ingestion.IngestionRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="official_census_records",
        help_text="Ingestion run that produced this record",
    )
    prontuario = models.CharField(max_length=50, blank=True, default="")
    nome = models.CharField(max_length=255, blank=True, default="")
    data_internacao = models.CharField(max_length=20, blank=True, default="")
    tempo_internacao = models.CharField(max_length=20, blank=True, default="")
    quarto_leito = models.CharField(max_length=50, blank=True, default="")
    cid = models.CharField(max_length=20, blank=True, default="")
    descricao = models.CharField(max_length=255, blank=True, default="")
    unidade = models.CharField(max_length=50, blank=True, default="")
    area_funcional = models.CharField(max_length=255, blank=True, default="")
    sigla = models.CharField(max_length=50, blank=True, default="")
    especialidade = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "id"]
        indexes = [
            models.Index(fields=["date"], name="off_census_date_idx"),
            models.Index(fields=["prontuario"], name="off_census_pront_idx"),
        ]
        verbose_name = "Official Census Record"
        verbose_name_plural = "Official Census Records"

    def __str__(self) -> str:
        return f"OfficialCensusRecord #{self.pk} [{self.date}]"

