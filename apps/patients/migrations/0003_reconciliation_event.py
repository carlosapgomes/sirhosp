"""Append-only exit reconciliation audit (RPSA-S2)."""

import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q

RECONCILIATION_STATUSES = (
    "pending",
    "reconciled",
    "already_reconciled",
    "patient_not_found",
    "admission_not_found",
    "ambiguous",
    "conflict",
    "invalid_exit_datetime",
)

RECONCILIATION_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("reconciled", "Reconciled"),
    ("already_reconciled", "Already reconciled"),
    ("patient_not_found", "Patient not found"),
    ("admission_not_found", "Admission not found"),
    ("ambiguous", "Ambiguous"),
    ("conflict", "Conflict"),
    ("invalid_exit_datetime", "Invalid exit datetime"),
]

EXIT_TYPE_CHOICES = [
    ("hospital_discharge", "Hospital discharge"),
    ("death", "Death"),
    ("unknown", "Unknown"),
]


class Migration(migrations.Migration):
    dependencies = [
        ("patients", "0002_admission_identity"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReconciliationEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "operation_uuid",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        unique=True,
                    ),
                ),
                (
                    "source_kind",
                    models.CharField(
                        help_text="Evidence kind (e.g. discharge_record).",
                        max_length=50,
                    ),
                ),
                (
                    "source_id",
                    models.BigIntegerField(
                        help_text=(
                            "Primary key of the evidence row (no FK: audit "
                            "outlives evidence)."
                        ),
                    ),
                ),
                (
                    "admission",
                    models.ForeignKey(
                        blank=True,
                        help_text="Candidate or matched admission, when one resolved.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reconciliation_events",
                        to="patients.admission",
                    ),
                ),
                ("status", models.CharField(choices=RECONCILIATION_STATUS_CHOICES, max_length=32)),
                (
                    "exit_type",
                    models.CharField(choices=EXIT_TYPE_CHOICES, default="unknown", max_length=32),
                ),
                (
                    "reason_code",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                (
                    "prior_discharge_date",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "new_discharge_date",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "details_json",
                    models.JSONField(blank=True, default=dict),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="reconciliationevent",
            index=models.Index(
                fields=["source_kind", "source_id"],
                name="ix_recon_event_source",
            ),
        ),
        migrations.AddConstraint(
            model_name="reconciliationevent",
            constraint=models.CheckConstraint(
                condition=Q(status__in=RECONCILIATION_STATUSES),
                name="ck_reconciliation_event_status",
            ),
        ),
    ]
