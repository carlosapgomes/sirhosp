"""Layered admission identity: source aliases and merge marker (RPSA-S1)."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("patients", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="admission",
            name="merged_into",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="merged_from",
                to="patients.admission",
            ),
        ),
        migrations.CreateModel(
            name="AdmissionSourceAlias",
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
                    "source_system",
                    models.CharField(default="tasy", max_length=100),
                ),
                ("alias_key", models.CharField(max_length=255)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                (
                    "admission",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="source_aliases",
                        to="patients.admission",
                    ),
                ),
            ],
            options={
                "ordering": ["-first_seen_at"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_system", "alias_key"),
                        name="uq_admission_source_alias_key",
                    ),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="admission",
            constraint=models.CheckConstraint(
                condition=~models.Q(pk=models.F("merged_into")),
                name="ck_admission_no_self_merge",
            ),
        ),
    ]
