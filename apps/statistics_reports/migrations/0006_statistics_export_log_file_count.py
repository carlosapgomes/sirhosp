# DSRS-S7: audit the served ZIP archive with an explicit file count.
#
# The export endpoint stopped serving a single workbook and now serves one
# archive with one XLSX per rendered group. ``file_count`` records how many
# files the archive held; legacy rows described exactly one served workbook,
# so they are backfilled with ``1``. The default exists only to backfill those
# legacy rows and is removed right after, so new rows must always carry their
# explicit count.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("statistics_reports", "0005_statistics_export_log"),
    ]

    operations = [
        migrations.AddField(
            model_name="statisticsexportlog",
            name="file_count",
            field=models.PositiveIntegerField(
                default=1,
                help_text=(
                    "Aggregate number of XLSX files served inside the archive"
                ),
            ),
        ),
        migrations.AlterField(
            model_name="statisticsexportlog",
            name="file_count",
            field=models.PositiveIntegerField(
                help_text=(
                    "Aggregate number of XLSX files served inside the archive"
                ),
            ),
        ),
    ]
