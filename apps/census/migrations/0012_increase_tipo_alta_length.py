# Generated manually - increase tipo_alta max_length to 50

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("census", "0011_censussnapshot_new_columns"),
    ]

    operations = [
        migrations.AlterField(
            model_name="censussnapshot",
            name="tipo_alta",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Discharge type code: A=alta médica, "
                    "G=alta administrativa, I=desistiu tratamento"
                ),
                max_length=50,
            ),
        ),
    ]
