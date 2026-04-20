"""Patient and Admission domain models (Slice S1)."""

from django.db import models


class Patient(models.Model):
    """Read-only mirror of patient demographic data from external source.

    Fields:
        patient_source_key: External patient identifier from source system.
        source_system: Origin system identifier (default: "tasy").
        cns: Cartão Nacional de Saúde.
        cpf: CPF number (fiscal identifier).
    """

    patient_source_key = models.CharField(max_length=255)
    source_system = models.CharField(max_length=100, default="tasy")

    name = models.CharField(max_length=512)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True, default="")
    mother_name = models.CharField(max_length=512, blank=True, default="")

    cns = models.CharField(max_length=50, blank=True, default="")
    cpf = models.CharField(max_length=20, blank=True, default="")

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


class Admission(models.Model):
    """Mirror of hospital admission linked to a Patient.

    Fields:
        source_admission_key: External admission identifier
            (e.g. admissionKey).
        source_patient_reference: Patient registration number as seen
            during this admission (for reconciliation).
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_system", "source_admission_key"],
                name="uq_adm_src",
            ),
        ]
        ordering = ["-admission_date"]

    def __str__(self) -> str:
        return (
            f"Admission {self.source_admission_key} "
            f"({self.patient.name})"
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
