# DSRS-S7: the served-export audit log of the daily statistics report. One
# additive row per workbook generated and ready to be served, carrying only the
# actor, the exact revision, the served instant and aggregate sheet/row counts
# -- no patient name, record or row content and no persisted workbook. Write
# only by the export endpoint, after the workbook exists in memory.
#
# Additive migration only: no RunPython, no data migration and no historical
# backfill.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("statistics_reports", "0004_statistics_permissions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StatisticsExportLog",
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
                (
                    "served_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text=(
                            "Instant the workbook was generated and ready to "
                            "be served"
                        ),
                    ),
                ),
                (
                    "sheet_count",
                    models.PositiveIntegerField(
                        help_text="Aggregate number of worksheets served"
                    ),
                ),
                (
                    "row_count",
                    models.PositiveIntegerField(
                        help_text=(
                            "Aggregate number of data rows served, section "
                            "titles excluded"
                        )
                    ),
                ),
                (
                    "report",
                    models.ForeignKey(
                        help_text=(
                            "Exact revision the served workbook reproduced"
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="export_logs",
                        to="statistics_reports.dailystatisticsreport",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        help_text=(
                            "Authenticated user the workbook was served to"
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="daily_statistics_exports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Statistics Export Log",
                "verbose_name_plural": "Statistics Export Logs",
                "ordering": ["-served_at", "-pk"],
            },
        ),
        migrations.AddIndex(
            model_name="statisticsexportlog",
            index=models.Index(
                fields=["report", "served_at"],
                name="dsr_export_report_idx",
            ),
        ),
    ]
