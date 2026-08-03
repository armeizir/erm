# Generated manually for ERM tutorial placement.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("risk", "0072_knowledgebasearticle_tutorial_video"),
    ]

    operations = [
        migrations.AlterField(
            model_name="knowledgebasearticle",
            name="tutorial_placement",
            field=models.CharField(
                blank=True,
                choices=[
                    (
                        "",
                        "Tidak digunakan sebagai video tutorial",
                    ),
                    (
                        "monthly_report_email",
                        "Email Laporan Risiko Bulanan",
                    ),
                    (
                        "metric_history_input",
                        "Halaman Input Data Histori Risiko",
                    ),
                ],
                default="",
                help_text=(
                    "Pilih lokasi aplikasi atau email tempat video "
                    "tutorial ditampilkan. Hanya satu artikel Published "
                    "yang boleh aktif pada setiap lokasi."
                ),
                max_length=50,
                verbose_name="Penempatan Tutorial",
            ),
        ),
    ]
