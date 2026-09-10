from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("corporate_risk", "0020_montecarlometrichistory_assigned_to_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="riskmetric",
            name="aggregation_type",
            field=models.CharField(
                choices=[
                    ("sum", "SUM - dijumlahkan antar periode"),
                    ("rate", "RATE - nilai tingkat/rate, tidak dijumlahkan"),
                    ("ratio", "RATIO - hasil pembagian numerator/denominator"),
                ],
                default="sum",
                help_text=(
                    "SUM untuk volume/nilai tahunan yang dijumlahkan per bulan. "
                    "RATE/RATIO tidak boleh dijumlahkan antar bulan."
                ),
                max_length=20,
                verbose_name="Semantik Agregasi",
            ),
        ),
        migrations.CreateModel(
            name="MonteCarloForecastAssumption",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("forecast_date", models.DateField(verbose_name="Bulan Forecast")),
                ("distribution_type", models.CharField(
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
                    default="normal", max_length=20, verbose_name="Distribusi"
                )),
                ("mean_value", models.DecimalField(decimal_places=4, max_digits=24, verbose_name="Mean / P50")),
                ("stddev_value", models.DecimalField(decimal_places=4, max_digits=24, verbose_name="Standard Deviation")),
                ("p15_value", models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True, verbose_name="P15.865254 Referensi")),
                ("source_type", models.CharField(
                    choices=[("crystal_ball", "Crystal Ball Import"), ("manual", "Manual")],
                    default="crystal_ball", max_length=20, verbose_name="Sumber"
                )),
                ("source_file", models.CharField(blank=True, default="", max_length=255, verbose_name="Nama File Sumber")),
                ("source_sha256", models.CharField(blank=True, db_index=True, default="", max_length=64, verbose_name="SHA256 Sumber")),
                ("source_sheet", models.CharField(blank=True, default="", max_length=100, verbose_name="Sheet Sumber")),
                ("source_metadata", models.JSONField(blank=True, default=dict, verbose_name="Metadata Sumber")),
                ("is_active", models.BooleanField(default=True, verbose_name="Aktif")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("metric", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="forecast_assumptions",
                    to="corporate_risk.riskmetric",
                    verbose_name="Risk Metric",
                )),
            ],
            options={
                "verbose_name": "Monte Carlo Forecast Assumption",
                "verbose_name_plural": "Monte Carlo Forecast Assumptions",
                "ordering": ("metric", "forecast_date"),
            },
        ),
        migrations.AddConstraint(
            model_name="montecarloforecastassumption",
            constraint=models.UniqueConstraint(
                fields=("metric", "forecast_date", "source_type", "source_sha256"),
                name="uniq_mc_assumption_metric_month_source",
            ),
        ),
    ]
