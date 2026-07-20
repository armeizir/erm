from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("monthly_report", "0012_recalculate_risk_matrix_summaries"),
    ]

    operations = [
        migrations.AlterField(
            model_name="monthlyriskreportitem",
            name="persentase_serapan_biaya",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=18,
                null=True,
                verbose_name="Persentase Serapan Biaya",
            ),
        ),
    ]
