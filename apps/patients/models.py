"""Patient and Admission domain models (Slice S1)."""

import uuid

from django.db import models
from django.db.models import Q

# ---------------------------------------------------------------------------
# Canonical exit reconciliation taxonomy (RPSA-S2).
# Single source of truth for reconciliation statuses and exit types; the
# database check constraints below enforce exactly these values.
# ---------------------------------------------------------------------------

RECONCILIATION_STATUS_PENDING = "pending"
"""Evidence has not produced a reconciliation outcome yet."""
RECONCILIATION_STATUS_RECONCILED = "reconciled"
"""Evidence closed (or corrected) one uniquely matched admission."""
RECONCILIATION_STATUS_ALREADY_RECONCILED = "already_reconciled"
"""Evidence repeated against an admission already closed at the same time."""
RECONCILIATION_STATUS_PATIENT_NOT_FOUND = "patient_not_found"
"""No mirrored patient resolves for the evidence."""
RECONCILIATION_STATUS_ADMISSION_NOT_FOUND = "admission_not_found"
"""Patient resolves but no compatible admission does."""
RECONCILIATION_STATUS_AMBIGUOUS = "ambiguous"
"""Multiple candidates remain without contradictory strong identifiers."""
RECONCILIATION_STATUS_CONFLICT = "conflict"
"""Contradictory strong identifiers or a temporally unvalidatable match."""
RECONCILIATION_STATUS_INVALID_EXIT_DATETIME = "invalid_exit_datetime"
"""Exit is earlier than the matched admission start."""

RECONCILIATION_STATUSES = (
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUS_RECONCILED,
    RECONCILIATION_STATUS_ALREADY_RECONCILED,
    RECONCILIATION_STATUS_PATIENT_NOT_FOUND,
    RECONCILIATION_STATUS_ADMISSION_NOT_FOUND,
    RECONCILIATION_STATUS_AMBIGUOUS,
    RECONCILIATION_STATUS_CONFLICT,
    RECONCILIATION_STATUS_INVALID_EXIT_DATETIME,
)

RECONCILIATION_STATUS_CHOICES = [
    (RECONCILIATION_STATUS_PENDING, "Pending"),
    (RECONCILIATION_STATUS_RECONCILED, "Reconciled"),
    (RECONCILIATION_STATUS_ALREADY_RECONCILED, "Already reconciled"),
    (RECONCILIATION_STATUS_PATIENT_NOT_FOUND, "Patient not found"),
    (RECONCILIATION_STATUS_ADMISSION_NOT_FOUND, "Admission not found"),
    (RECONCILIATION_STATUS_AMBIGUOUS, "Ambiguous"),
    (RECONCILIATION_STATUS_CONFLICT, "Conflict"),
    (RECONCILIATION_STATUS_INVALID_EXIT_DATETIME, "Invalid exit datetime"),
]

EXIT_HOSPITAL_DISCHARGE = "hospital_discharge"
EXIT_DEATH = "death"
EXIT_UNKNOWN = "unknown"

EXIT_TYPES = (EXIT_HOSPITAL_DISCHARGE, EXIT_DEATH, EXIT_UNKNOWN)

EXIT_TYPE_CHOICES = [
    (EXIT_HOSPITAL_DISCHARGE, "Hospital discharge"),
    (EXIT_DEATH, "Death"),
    (EXIT_UNKNOWN, "Unknown"),
]


class Patient(models.Model):
    """Read-only mirror of patient demographic data from external source.

    Fields:
        patient_source_key: External patient identifier from source system.
        source_system: Origin system identifier (default: "tasy").
        social_name: Nome social do paciente.
        gender_identity: Gênero (identidade de gênero) do paciente.
        race_color: Raça/Cor declarada do paciente.
        cns: Cartão Nacional de Saúde.
        cpf: CPF number (fiscal identifier).
    """

    patient_source_key = models.CharField(max_length=255)
    source_system = models.CharField(max_length=100, default="tasy")

    name = models.CharField(max_length=512)
    social_name = models.CharField(max_length=512, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True, default="")
    gender_identity = models.CharField(max_length=50, blank=True, default="")
    mother_name = models.CharField(max_length=512, blank=True, default="")
    father_name = models.CharField(max_length=512, blank=True, default="")
    race_color = models.CharField(max_length=50, blank=True, default="")
    birthplace = models.CharField(max_length=200, blank=True, default="")
    nationality = models.CharField(max_length=100, blank=True, default="")
    marital_status = models.CharField(max_length=50, blank=True, default="")
    education_level = models.CharField(max_length=100, blank=True, default="")
    profession = models.CharField(max_length=200, blank=True, default="")

    cns = models.CharField(max_length=50, blank=True, default="")
    cpf = models.CharField(max_length=20, blank=True, default="")

    phone_home = models.CharField(max_length=30, blank=True, default="")
    phone_cellular = models.CharField(max_length=30, blank=True, default="")
    phone_contact = models.CharField(max_length=30, blank=True, default="")

    street = models.CharField(max_length=300, blank=True, default="")
    address_number = models.CharField(max_length=20, blank=True, default="")
    address_complement = models.CharField(max_length=200, blank=True, default="")
    neighborhood = models.CharField(max_length=200, blank=True, default="")
    city = models.CharField(max_length=200, blank=True, default="")
    state = models.CharField(max_length=5, blank=True, default="")
    postal_code = models.CharField(max_length=15, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_system", "patient_source_key"],
                name="uq_patient_src",
            ),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class AdmissionQuerySet(models.QuerySet):
    """Queryset helpers for admission identity semantics."""

    def canonical(self) -> "AdmissionQuerySet":
        """Exclude admissions merged into another canonical row."""
        return self.filter(merged_into__isnull=True)


class AdmissionManager(models.Manager["Admission"]):
    """Default manager: canonical admissions only (merged rows hidden)."""

    def get_queryset(self) -> AdmissionQuerySet:
        return AdmissionQuerySet(self.model, using=self._db).canonical()

    def canonical(self) -> AdmissionQuerySet:
        return self.get_queryset()


class Admission(models.Model):
    """Mirror of hospital admission linked to a Patient.

    Fields:
        source_admission_key: External admission identifier
            (e.g. admissionKey).
        source_patient_reference: Patient registration number as seen
            during this admission (for reconciliation).
        merged_into: Canonical admission when this row was merged as a
            duplicate; merged rows keep their identity for audit and are
            excluded from clinical listings via the default manager.

    Managers:
        objects: Canonical admissions only (``merged_into`` is null).
        all_objects: Unfiltered maintenance access, including merged rows.
    """

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE,
        related_name="admissions",
    )

    source_admission_key = models.CharField(max_length=255)
    source_system = models.CharField(max_length=100, default="tasy")

    admission_date = models.DateTimeField(null=True, blank=True)
    discharge_date = models.DateTimeField(null=True, blank=True)

    ward = models.CharField(max_length=100, blank=True, default="")
    bed = models.CharField(max_length=50, blank=True, default="")

    source_patient_reference = models.CharField(
        max_length=255, blank=True, default="",
    )

    merged_into = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="merged_from",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AdmissionManager()
    all_objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_system", "source_admission_key"],
                name="uq_adm_src",
            ),
            models.CheckConstraint(
                condition=~models.Q(pk=models.F("merged_into")),
                name="ck_admission_no_self_merge",
            ),
        ]
        ordering = ["-admission_date"]

    def __str__(self) -> str:
        return (
            f"Admission {self.source_admission_key} "
            f"({self.patient.name})"
        )


class AdmissionSourceAlias(models.Model):
    """External admission key observed for one canonical Admission.

    The source system can change the admission key inside a single episode;
    every observed key is preserved here so layered identity resolution can
    reuse the canonical admission instead of creating a duplicate. The
    ``(source_system, alias_key)`` uniqueness guarantees one alias resolves
    to exactly one canonical admission.
    """

    admission = models.ForeignKey(
        Admission,
        on_delete=models.CASCADE,
        related_name="source_aliases",
    )
    source_system = models.CharField(max_length=100, default="tasy")
    alias_key = models.CharField(max_length=255)
    first_seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_system", "alias_key"],
                name="uq_admission_source_alias_key",
            ),
        ]
        ordering = ["-first_seen_at"]

    def __str__(self) -> str:
        return f"{self.source_system}:{self.alias_key} -> #{self.admission_id}"


class ReconciliationEvent(models.Model):
    """Append-only audit of one canonical exit-reconciliation attempt.

    One row is created per attempted reconciliation (RPSA-S2). Payloads
    carry structural state required for traceability and reversibility —
    source evidence kind/primary key, status, exit type, reason code and
    prior/new ``discharge_date`` values — and never duplicate patient
    identity (name, record number) or clinical text. Application code only
    creates rows: audit is retained indefinitely and must never be updated
    or deleted through services.
    """

    operation_uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
    )
    source_kind = models.CharField(
        max_length=50,
        help_text="Evidence kind (e.g. discharge_record).",
    )
    source_id = models.BigIntegerField(
        help_text="Primary key of the evidence row (no FK: audit outlives evidence).",
    )
    admission = models.ForeignKey(
        Admission,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconciliation_events",
        help_text="Candidate or matched admission, when one resolved.",
    )
    status = models.CharField(
        max_length=32,
        choices=RECONCILIATION_STATUS_CHOICES,
    )
    exit_type = models.CharField(
        max_length=32,
        choices=EXIT_TYPE_CHOICES,
        default=EXIT_UNKNOWN,
    )
    reason_code = models.CharField(max_length=64, blank=True, default="")
    prior_discharge_date = models.DateTimeField(null=True, blank=True)
    new_discharge_date = models.DateTimeField(null=True, blank=True)
    details_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["source_kind", "source_id"],
                name="ix_recon_event_source",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=RECONCILIATION_STATUSES),
                name="ck_reconciliation_event_status",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"ReconciliationEvent {self.operation_uuid} "
            f"[{self.status}] {self.source_kind}#{self.source_id}"
        )


class PatientIdentifierHistory(models.Model):
    """Audit trail for patient identifier changes.

    Fields:
        identifier_type: Type of identifier changed
            (e.g. patient_source_key, cns, cpf).
    """

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE,
        related_name="id_history",
    )
    identifier_type = models.CharField(max_length=100)
    old_value = models.CharField(max_length=255, blank=True, default="")
    new_value = models.CharField(max_length=255, blank=True, default="")
    changed_at = models.DateTimeField(auto_now_add=True)
    ingestion_run = models.ForeignKey(
        "ingestion.IngestionRun",
        on_delete=models.SET_NULL, null=True, blank=True,
    )

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self) -> str:
        return (
            f"{self.identifier_type}: "
            f"{self.old_value} -> {self.new_value}"
        )
