# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("census", "0010_add_missing_specialties"),
    ]

    operations = [
        migrations.AddField(
            model_name="censussnapshot",
            name="data_movimentacao",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Date of last movement (DD/MM or DD/MM/AAAA)",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="censussnapshot",
            name="origem",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Origin sector/bed code from the last movement",
                max_length=100,
            ),
        ),
        migrations.AddField(
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
