"""Patient and Admission domain models (Slice S1)."""

from django.db import models


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
