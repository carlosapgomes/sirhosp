# CIPOO-S1: additive migration allowing quality_warning on occupancy-v4 or
# occupancy-v5. No RunPython, no destructive default and no backfill.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('census', '0023_capacitysectormembership_source_display_name'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='occupancymeasurement',
            name='ck_occupancy_quality_warning_only_v4',
        ),
        migrations.AddConstraint(
            model_name='occupancymeasurement',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ('quality_warning__isnull', True),
                    (
                        'algorithm_version__in',
                        ['occupancy-v4', 'occupancy-v5'],
                    ),
                    _connector='OR',
                ),
                name='ck_occupancy_quality_warning_only_v4_v5',
            ),
        ),
        migrations.AlterField(
            model_name='occupancymeasurement',
            name='quality_warning',
            field=models.BooleanField(
                blank=True,
                default=None,
                help_text='True when this occupancy-v4 or occupancy-v5 measurement carries actionable quality warnings (conflicts or rows without position for v4; incomplete identity, cross-group records, name variants, age fallback or occupied unmapped patients for v5); such measurements stay daily-eligible with a separate warning counter. Null keeps v1-v3 uninterpreted.',
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='occupancymeasurement',
            name='physical_reconciliation_json',
            field=models.JSONField(
                blank=True,
                default=None,
                help_text='Closed aggregate reconciliation of raw rows, physical positions, duplicates, conflicts and unidentified rows (occupancy-v3 uses schema 1, occupancy-v4 uses schema 2, occupancy-v5 uses schema 3 with identified-patient and fallback counts); contains only allowlisted nonnegative integers, never row-level identity',
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='dailyoccupancysummary',
            name='quality_warning_measurement_count',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Day measurements materialized under occupancy-v4 or occupancy-v5 that carry quality warnings; such measurements stay eligible and warnings never increment the historical exclusion counters',
            ),
        ),
    ]
