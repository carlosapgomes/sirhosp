"""Require the loaded catalog contract and enforce the S1 invariants.

Runs after ``0004`` loaded/validated the catalog: the type category and
profile become required, the four fixed profiles and the RNM capability
relationship are enforced by the database, and the revision snapshots
accept only known profiles while allowing unknown historical metadata.
"""

from django.db import migrations, models

PROFILE_CHOICES = [
    ("agendamento", "Agendamento"),
    ("tratamento-periodo", "Tratamento com período"),
    ("registro-simples", "Registro simples"),
    ("assinatura-documento", "Assinatura de documento"),
]

PROFILE_VALUES = tuple(value for value, _label in PROFILE_CHOICES)


class Migration(migrations.Migration):

    dependencies = [
        ("pending_items", "0004_load_pending_item_catalog"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pendingitemtype",
            name="category",
            field=models.ForeignKey(
                on_delete=models.deletion.PROTECT,
                related_name="types",
                to="pending_items.pendingitemcategory",
            ),
        ),
        migrations.AlterField(
            model_name="pendingitemtype",
            name="profile",
            field=models.CharField(choices=PROFILE_CHOICES, max_length=32),
        ),
        migrations.AddConstraint(
            model_name="pendingitemtype",
            constraint=models.CheckConstraint(
                condition=models.Q(profile__in=PROFILE_VALUES),
                name="ck_pending_item_type_profile",
            ),
        ),
        migrations.AddConstraint(
            model_name="pendingitemtype",
            constraint=models.CheckConstraint(
                condition=models.Q(has_rnm_complements=False)
                | models.Q(profile="agendamento"),
                name="ck_pending_item_type_rnm_requires_scheduling",
            ),
        ),
        migrations.AddConstraint(
            model_name="pendingitemrevision",
            constraint=models.CheckConstraint(
                condition=models.Q(profile__isnull=True)
                | models.Q(profile__in=PROFILE_VALUES),
                name="ck_pending_item_revision_profile",
            ),
        ),
        migrations.AddConstraint(
            model_name="pendingitemrevision",
            constraint=models.CheckConstraint(
                condition=models.Q(profile__isnull=True)
                | models.Q(has_rnm_complements__isnull=True)
                | models.Q(has_rnm_complements=False)
                | models.Q(profile="agendamento"),
                name="ck_pending_item_revision_rnm_requires_scheduling",
            ),
        ),
        migrations.AlterModelOptions(
            name="pendingitemtype",
            options={"ordering": ["category__name", "name"]},
        ),
    ]
