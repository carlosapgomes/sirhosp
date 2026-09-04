"""PostgreSQL-backed stale-admission reconciliation cases (RPSA-S5).

Additive model migration: one conservative case per open canonical
admission plus the dedicated reconciliation-review permission consumed
by RPSA-S6 (codename pinned to ``review_reconciliation_cases``).
"""

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [
        ("ingestion", "0006_evolutionextractioncoverage"),
        ("patients", "0004_admissionmergeoperation"),
    ]

    operations = [
        migrations.CreateModel(
            name="StaleAdmissionCase",
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
                    "first_absence_at",
                    models.DateTimeField(
                        help_text=(
                            "Capture timestamp of the first absence run; "
                            "the 30-minute eligibility window is measured "
                            "from here (inclusive)."
                        ),
                    ),
                ),
                (
                    "last_absence_at",
                    models.DateTimeField(
                        help_text=(
                            "Capture timestamp of the latest absence run."
                        ),
                    ),
                ),
                (
                    "resolved_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "resolution_reason",
                    models.CharField(
                        blank=True,
                        choices=[
                            (
                                "reappeared",
                                "Reappeared in an accepted census",
                            ),
                            (
                                "exit_confirmed",
                                "Admission exit confirmed by reconciliation",
                            ),
                        ],
                        default="",
                        help_text=(
                            "Set together with resolved_at; empty while "
                            "the case is open."
                        ),
                        max_length=32,
                    ),
                ),
                (
                    "last_enqueued_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "last_enqueue_outcome",
                    models.CharField(
                        blank=True,
                        choices=[
                            (
                                "inconclusive",
                                "Inconclusive source confirmation",
                            ),
                            (
                                "conclusive_no_exit",
                                "Source confirmed no exit",
                            ),
                        ],
                        default="",
                        help_text=(
                            "Classified at the next evaluation from the "
                            "run status plus admission state; empty while "
                            "the latest attempt is pending."
                        ),
                        max_length=32,
                    ),
                ),
                (
                    "last_outcome_at",
                    models.DateTimeField(
                        blank=True,
                        help_text=(
                            "Reference instant of the cooldown (run "
                            "completion)."
                        ),
                        null=True,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "admission",
                    models.ForeignKey(
                        help_text=(
                            "Open canonical admission under conservative "
                            "suspicion."
                        ),
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stale_cases",
                        to="patients.admission",
                    ),
                ),
                (
                    "first_absence_run",
                    models.ForeignKey(
                        help_text=(
                            "Accepted census run of the first confirmed "
                            "absence."
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="ingestion.ingestionrun",
                    ),
                ),
                (
                    "last_absence_run",
                    models.ForeignKey(
                        help_text=(
                            "Latest accepted census run that omitted the "
                            "patient."
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="ingestion.ingestionrun",
                    ),
                ),
                (
                    "last_enqueued_run",
                    models.ForeignKey(
                        blank=True,
                        help_text=(
                            "Latest admissions_only confirmation run "
                            "requested."
                        ),
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="ingestion.ingestionrun",
                    ),
                ),
            ],
            options={
                "verbose_name": "Stale Admission Case",
                "verbose_name_plural": "Stale Admission Cases",
                "ordering": ["first_absence_at", "pk"],
                "permissions": [
                    (
                        "review_reconciliation_cases",
                        "Can review reconciliation cases",
                    ),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="staleadmissioncase",
            constraint=models.UniqueConstraint(
                condition=Q(resolved_at__isnull=True),
                fields=["admission"],
                name="uq_stale_case_open_per_admission",
            ),
        ),
        migrations.AddConstraint(
            model_name="staleadmissioncase",
            constraint=models.CheckConstraint(
                condition=Q(last_absence_at__gte=F("first_absence_at")),
                name="ck_stale_case_absence_order",
            ),
        ),
        migrations.AddConstraint(
            model_name="staleadmissioncase",
            constraint=models.CheckConstraint(
                condition=Q(resolved_at__isnull=True, resolution_reason="")
                | (Q(resolved_at__isnull=False) & ~Q(resolution_reason="")),
                name="ck_stale_case_resolution_consistent",
            ),
        ),
    ]
