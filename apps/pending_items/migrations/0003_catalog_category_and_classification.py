"""Add the catalog category and the classification metadata columns.

Schema only (design D8): the category stays nullable and the type profile
stays nullable until ``0004`` finishes loading/validating the catalog and
``0005`` makes them required. The global unique name is replaced by a
per-category unique name so the same visible name can exist in two
categories (for example the two ``RNM`` entries).
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pending_items", "0002_bootstrap_outro_group"),
    ]

    operations = [
        migrations.CreateModel(
            name="PendingItemCategory",
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
                ("name", models.CharField(max_length=100, unique=True)),
                ("slug", models.SlugField(max_length=100, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="pendingitemrevision",
            name="category_name",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="pendingitemrevision",
            name="category_slug",
            field=models.SlugField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="pendingitemrevision",
            name="has_rnm_complements",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="pendingitemrevision",
            name="profile",
            field=models.CharField(
                blank=True,
                choices=[
                    ("agendamento", "Agendamento"),
                    ("tratamento-periodo", "Tratamento com período"),
                    ("registro-simples", "Registro simples"),
                    ("assinatura-documento", "Assinatura de documento"),
                ],
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="pendingitemrevision",
            name="requires_description",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="pendingitemrevision",
            name="type_slug",
            field=models.SlugField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="pendingitemtype",
            name="has_rnm_complements",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="pendingitemtype",
            name="profile",
            field=models.CharField(
                choices=[
                    ("agendamento", "Agendamento"),
                    ("tratamento-periodo", "Tratamento com período"),
                    ("registro-simples", "Registro simples"),
                    ("assinatura-documento", "Assinatura de documento"),
                ],
                max_length=32,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="pendingitemtype",
            name="requires_description",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="pendingitemtype",
            name="name",
            field=models.CharField(max_length=100),
        ),
        migrations.AddField(
            model_name="pendingitemtype",
            name="category",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="types",
                to="pending_items.pendingitemcategory",
            ),
        ),
        migrations.AddConstraint(
            model_name="pendingitemtype",
            constraint=models.UniqueConstraint(
                fields=("category", "name"),
                name="uq_pending_item_type_category_name",
            ),
        ),
    ]
