"""STRUCT-PEND-S2: typed complementary details and their local constraints.

Additive only: every new column is nullable and both tables keep their
identities, states and existing revisions. Nullable columns express the
historical absence of information; no text parsing or fictitious revision
is performed, so records written before this migration keep every value
unknown (PI-10).
"""

from __future__ import annotations

from django.db import migrations, models

DETAIL_FIELDS: tuple[tuple[str, models.Field], ...] = (
    ("contrast", models.BooleanField(blank=True, null=True)),
    ("is_scheduled", models.BooleanField(blank=True, null=True)),
    ("scheduled_date", models.DateField(blank=True, null=True)),
    ("sedation", models.BooleanField(blank=True, null=True)),
    ("signature_at", models.DateTimeField(blank=True, null=True)),
    ("treatment_end_date", models.DateField(blank=True, null=True)),
    ("treatment_start_date", models.DateField(blank=True, null=True)),
)

SCHEDULED_DATE_REQUIRES_YES = models.Q(scheduled_date__isnull=True) | models.Q(
    is_scheduled__isnull=False, is_scheduled=True
)
"""A stored date requires Sim; unknown or Não may not carry a date."""

TREATMENT_PERIOD_ORDER = (
    models.Q(treatment_start_date__isnull=True)
    | models.Q(treatment_end_date__isnull=True)
    | models.Q(treatment_end_date__gte=models.F("treatment_start_date"))
)


def _add_fields(model_name: str) -> list[migrations.AddField]:
    return [
        migrations.AddField(
            model_name=model_name,
            name=name,
            field=field,
        )
        for name, field in DETAIL_FIELDS
    ]


class Migration(migrations.Migration):
    dependencies = [
        ("pending_items", "0005_catalog_contract_constraints"),
    ]

    operations = [
        *_add_fields("pendingitem"),
        *_add_fields("pendingitemrevision"),
        migrations.AddConstraint(
            model_name="pendingitem",
            constraint=models.CheckConstraint(
                condition=SCHEDULED_DATE_REQUIRES_YES,
                name="ck_pending_item_scheduled_date_requires_yes",
            ),
        ),
        migrations.AddConstraint(
            model_name="pendingitem",
            constraint=models.CheckConstraint(
                condition=TREATMENT_PERIOD_ORDER,
                name="ck_pending_item_treatment_period_order",
            ),
        ),
        migrations.AddConstraint(
            model_name="pendingitemrevision",
            constraint=models.CheckConstraint(
                condition=SCHEDULED_DATE_REQUIRES_YES,
                name="ck_pending_item_revision_scheduled_date_requires_yes",
            ),
        ),
        migrations.AddConstraint(
            model_name="pendingitemrevision",
            constraint=models.CheckConstraint(
                condition=TREATMENT_PERIOD_ORDER,
                name="ck_pending_item_revision_treatment_period_order",
            ),
        ),
    ]
