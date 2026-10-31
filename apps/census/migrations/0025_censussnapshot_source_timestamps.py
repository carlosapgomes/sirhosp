# ECD-S1: additive optional source timestamps on census snapshots.
# No RunPython, no backfill, no new index and no change to existing columns.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('census', '0024_occupancy_quality_warning_v4_v5'),
    ]

    operations = [
        migrations.AddField(
            model_name='censussnapshot',
            name='source_admission_at',
            field=models.DateTimeField(
                blank=True,
                help_text='Optional admission timestamp supplied by the source; null when the transport only carries a date or no value',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='censussnapshot',
            name='source_movement_at',
            field=models.DateTimeField(
                blank=True,
                help_text='Optional movement timestamp supplied by the source; null when the transport only carries a date or no value',
                null=True,
            ),
        ),
    ]
