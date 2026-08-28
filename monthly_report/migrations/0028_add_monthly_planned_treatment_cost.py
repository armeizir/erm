from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monthly_report", "0027_add_monthly_actual_timeline"),
    ]

    operations = [
        migrations.AddField(
            model_name="monthlyriskreportitem",
            name="rencana_biaya_perlakuan",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=18,
                null=True,
                verbose_name="Rencana Biaya Perlakuan Risiko",
            ),
        ),
    ]
