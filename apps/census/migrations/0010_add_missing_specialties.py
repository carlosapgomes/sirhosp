# Generated manually: add missing specialties from AGHU census data
# These codes appear in the daily census but were absent from earlier seeds.

from django.db import migrations


MISSING_SPECIALTIES = [
    ("NCI", "NEUROCIRURGIA"),
    ("NEF", "NEFROLOGIA"),
    ("NEO", "NEONATOLOGIA"),
    ("NEP", "NEFROLOGIA PEDIÁTRICA"),
    ("NEU", "NEUROLOGIA"),
    ("OB", "OBSTETRÍCIA"),
    ("OBS", "OBSTETRÍCIA (OBS)"),
    ("PED", "PEDIATRIA"),
    ("ROL", "REUMATOLOGIA (ROL)"),
    ("URO", "UROLOGIA"),
]


def add_missing(apps, schema_editor):
    Specialty = apps.get_model("census", "Specialty")
    for code, name in MISSING_SPECIALTIES:
        Specialty.objects.get_or_create(code=code, defaults={"name": name})


def reverse_add(apps, schema_editor):
    Specialty = apps.get_model("census", "Specialty")
    Specialty.objects.filter(code__in=[c for c, _ in MISSING_SPECIALTIES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("census", "0009_update_specialties_from_source"),
    ]

    operations = [
        migrations.RunPython(add_missing, reverse_add),
    ]
