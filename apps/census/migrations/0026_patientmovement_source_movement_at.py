# SMT-S1: additive optional source movement time on patient movements.
# No RunPython, no backfill, no new index and no change to existing columns.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('census', '0025_censussnapshot_source_timestamps'),
    ]

    operations = [
        migrations.AddField(
            model_name='patientmovement',
            name='source_movement_at',
            field=models.DateTimeField(
                blank=True,
                help_text='Optional real movement timestamp supplied by the source census snapshot; null when the source only carried a date or no value',
                null=True,
            ),
        ),
    ]
