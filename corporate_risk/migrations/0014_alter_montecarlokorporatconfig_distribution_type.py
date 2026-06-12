# Generated manually on 2026-06-11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("corporate_risk", "0013_riskmetric_rkap_item_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="montecarlokorporatconfig",
            name="distribution_type",
            field=models.CharField(
                choices=[
                    ("normal", "Distribusi Normal (Gaussian)"),
                    ("lognormal", "Lognormal"),
                    ("triangular", "Triangular"),
                    ("uniform", "Uniform"),
                    ("beta", "Beta"),
                    ("gamma", "Gamma"),
                    ("weibull", "Weibull"),
                    ("empirical", "Empirical Distribution"),
                ],
                default="normal",
                max_length=20,
            ),
        ),
    ]
