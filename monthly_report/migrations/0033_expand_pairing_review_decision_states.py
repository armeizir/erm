# Generated for Pairing Disable V1

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "monthly_report",
            "0032_monthlyriskreportitempairingreview",
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name="monthlyriskreportitempairingreview",
            name="decision",
            field=models.CharField(
                choices=[
                    ("aktif", "Belum Direview"),
                    ("nonaktif", "Pairing Nonaktif"),
                    ("sesuai", "Sesuai"),
                    (
                        "perlu_perbaikan",
                        "Perlu Perbaikan",
                    ),
                ],
                max_length=30,
                verbose_name="Keputusan",
            ),
        ),
    ]
