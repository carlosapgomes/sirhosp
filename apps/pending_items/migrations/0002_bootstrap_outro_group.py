"""Bootstrap the Outro catalog entry and the Desospitalização group.

Idempotent: safe to reapply. Creates no users and no patient content.
"""

from django.db import migrations


def bootstrap_outro_and_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    PendingItemType = apps.get_model("pending_items", "PendingItemType")
    Group.objects.get_or_create(name="Desospitalização")
    outro, created = PendingItemType.objects.get_or_create(
        slug="outro", defaults={"name": "Outro"}
    )
    if not created and outro.name != "Outro":
        PendingItemType.objects.filter(pk=outro.pk).update(name="Outro")


class Migration(migrations.Migration):
    dependencies = [
        ("pending_items", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            bootstrap_outro_and_group,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
