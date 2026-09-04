"""Append-only admission merge operation audit (RPSA-S4)."""

import uuid

from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [
        ("patients", "0003_reconciliation_event"),
    ]

    operations = [
        migrations.CreateModel(
            name="AdmissionMergeOperation",
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
                    "canonical_admission_id",
                    models.BigIntegerField(
                        help_text="Oldest (winning) Admission primary key.",
                    ),
                ),
                (
                    "merged_admission_id",
                    models.BigIntegerField(
                        help_text=(
                            "Newer Admission primary key marked ``merged_into``."
                        ),
                    ),
                ),
                (
                    "patient_id",
                    models.BigIntegerField(
                        help_text=(
                            "Internal Patient primary key shared by both "
                            "admissions (structural only; never a name or "
                            "record number)."
                        ),
                    ),
                ),
                (
                    "source_fingerprint",
                    models.CharField(
                        help_text=(
                            "SHA-256 digest of the source-confirmation "
                            "snapshot that authorized the merge (structural "
                            "content only)."
                        ),
                        max_length=64,
                    ),
                ),
                (
                    "source_episode_count",
                    models.PositiveSmallIntegerField(default=1),
                ),
                (
                    "confirmed_local_date",
                    models.DateField(
                        help_text=(
                            "America/Bahia local admission date the source "
                            "confirmed."
                        ),
                    ),
                ),
                (
                    "source_confirmed_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("before_state", models.JSONField(default=dict)),
                ("relation_manifest", models.JSONField(default=dict)),
                (
                    "rolled_back_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="admissionmergeoperation",
            index=models.Index(
                fields=["canonical_admission_id"],
                name="ix_adm_merge_op_canon",
            ),
        ),
        migrations.AddIndex(
            model_name="admissionmergeoperation",
            index=models.Index(
                fields=["merged_admission_id"],
                name="ix_adm_merge_op_merged",
            ),
        ),
        migrations.AddConstraint(
            model_name="admissionmergeoperation",
            constraint=models.CheckConstraint(
                condition=Q(
                    canonical_admission_id__lt=F("merged_admission_id")
                ),
                name="ck_adm_merge_op_oldest_canonical",
            ),
        ),
    ]
