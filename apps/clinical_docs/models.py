"""ClinicalEvent - canonical clinical event model (Slice S1)."""

from django.db import models


class ClinicalEvent(models.Model):
    """Canonical clinical event (evolution) with dedup and raw payload.

    Fields:
        event_identity_key: Deterministic key for event identity (dedup).
        content_hash: Hash of content_text for revision detection.
        happened_at: When the clinical event occurred.
        profession_type: Profession type (medica, enfermagem,
            fisioterapia, etc).
        content_text: Canonical text content for queries and FTS.
        raw_payload_json: Full raw payload from source for audit.
    """

    admission = models.ForeignKey(
        "patients.Admission",
        on_delete=models.CASCADE,
        related_name="events",
    )
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.CASCADE,
        related_name="events",
    )
    ingestion_run = models.ForeignKey(
        "ingestion.IngestionRun",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="events",
    )

    event_identity_key = models.CharField(max_length=512)
    content_hash = models.CharField(max_length=128)

    happened_at = models.DateTimeField()
    signed_at = models.DateTimeField(null=True, blank=True)

    author_name = models.CharField(max_length=512)
    profession_type = models.CharField(max_length=100)

    content_text = models.TextField()
    signature_line = models.CharField(
        max_length=512, blank=True, default="",
    )

    raw_payload_json = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event_identity_key", "content_hash"],
                name="uq_evt_identity",
            ),
        ]
        ordering = ["-happened_at"]

    def __str__(self) -> str:
        return (
            f"Event {self.event_identity_key} "
            f"[{self.profession_type}] {self.happened_at}"
        )
