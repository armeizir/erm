from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("corporate_risk", "0021_crystal_ball_imported_assumptions"),
    ]

    operations = [
        migrations.AddField(
            model_name="riskmetric",
            name="ratio_numerator_metric",
            field=models.ForeignKey(
                blank=True,
                help_text="Wajib untuk aggregation RATIO. Dapat menunjuk metric pada risiko korporat lain.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="ratio_numerator_for",
                to="corporate_risk.riskmetric",
                verbose_name="Metric Pembilang Ratio",
            ),
        ),
        migrations.AddField(
            model_name="riskmetric",
            name="ratio_denominator_metric",
            field=models.ForeignKey(
                blank=True,
                help_text="Wajib untuk aggregation RATIO. Nilai ratio = pembilang / penyebut.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="ratio_denominator_for",
                to="corporate_risk.riskmetric",
                verbose_name="Metric Penyebut Ratio",
            ),
        ),
    ]
