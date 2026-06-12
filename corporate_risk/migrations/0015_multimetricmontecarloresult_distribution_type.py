from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("corporate_risk", "0014_alter_montecarlokorporatconfig_distribution_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="multimetricmontecarloresult",
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
                help_text="Pilih model distribusi setelah melihat rekomendasi sistem.",
                max_length=20,
                verbose_name="Model Distribusi Monte Carlo",
            ),
        ),
    ]
