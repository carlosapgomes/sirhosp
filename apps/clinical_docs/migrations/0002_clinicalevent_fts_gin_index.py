"""Add GIN index for FTS on content_text (Slice S3).

PostgreSQL-only migration: creates a functional GIN index on
to_tsvector('portuguese', content_text) for efficient full-text search.

On SQLite or other backends, this migration is a no-op.
"""

from django.db import migrations


def _create_gin_index(apps, schema_editor):
    """Create GIN index only on PostgreSQL."""
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_clinical_event_fts
            ON clinical_docs_clinicalevent
            USING GIN (to_tsvector('portuguese', content_text));
            """
        )


def _drop_gin_index(apps, schema_editor):
    """Drop GIN index only on PostgreSQL."""
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            "DROP INDEX IF EXISTS idx_clinical_event_fts;"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("clinical_docs", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            code=_create_gin_index,
            reverse_code=_drop_gin_index,
        ),
    ]
