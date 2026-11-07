"""Load and validate the canonical pending-item catalog.

Design D8: the load runs after the schema migration that made the
category nullable and before the migration that makes it required. The
load is atomic: a catalog collision aborts the whole operation with a
diagnostic that contains only catalog identifiers, never patient data.
"""

from django.db import migrations

from apps.pending_items.catalog import load_pending_item_catalog


def load_catalog(apps, schema_editor):
    load_pending_item_catalog(apps, initial=True)


class Migration(migrations.Migration):

    dependencies = [
        ("pending_items", "0003_catalog_category_and_classification"),
    ]

    operations = [
        migrations.RunPython(load_catalog, reverse_code=migrations.RunPython.noop),
    ]
