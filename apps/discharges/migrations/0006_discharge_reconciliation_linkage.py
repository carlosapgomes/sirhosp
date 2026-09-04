"""Discharge evidence reconciliation linkage and aggregate decoupling (RPSA-S2).

Additive only: nullable ``daily_count`` decouples evidence persistence
from the operational ``DailyDischargeCount`` aggregate; new nullable
linkage/status fields plus a status check constraint attach canonical
exit reconciliation to every ``DischargeRecord``.
"""

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


class Migration(migrations.Migration):
    dependencies = [
        ("discharges", "0005_v2_xls_discharge_model"),
    ]

    operations = [
        migrations.AlterField(
            model_name="dischargerecord",
            name="daily_count",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Legacy report-batch link (nullable since RPSA-S2: evidence "
                    "is decoupled from the operational daily aggregate)."
                ),
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="records",
                to="discharges.dailydischargecount",
            ),
        ),
        migrations.AddField(
            model_name="dischargerecord",
            name="admission",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Canonical admission linked by reconciliation "
                    "(null while unresolved)."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="discharge_evidence",
                to="patients.admission",
            ),
        ),
        migrations.AddField(
            model_name="dischargerecord",
            name="reconciliation_status",
            field=models.CharField(
                choices=RECONCILIATION_STATUS_CHOICES,
                default="pending",
                help_text=(
                    "Outcome of the latest canonical exit-reconciliation attempt."
                ),
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="dischargerecord",
            name="reconciled_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the latest reconciliation attempt was applied.",
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="dischargerecord",
            constraint=models.CheckConstraint(
                condition=Q(reconciliation_status__in=RECONCILIATION_STATUSES),
                name="ck_dischargerecord_recon_status",
            ),
        ),
    ]
