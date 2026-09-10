from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("corporate_risk", "0022_riskmetric_ratio_links"),
    ]

    operations = [
        migrations.AddField(
            model_name="multimetricaiinsightkorporat",
            name="user_context",
            field=models.TextField(
                blank=True,
                default="",
                help_text=(
                    "Konteks tambahan dari user saat AI Insight dibuat. "
                    "Konteks ini tidak menggantikan fakta/angka hasil Monte Carlo."
                ),
            ),
        ),
        migrations.AddField(
            model_name="multimetricaiinsightkorporat",
            name="management_decision_draft",
            field=models.TextField(
                blank=True,
                default="",
                help_text=(
                    "Draft ringkas Management Decision yang diturunkan dari AI Insight yang sama. "
                    "Draft ini belum merupakan keputusan final manajemen."
                ),
            ),
        ),
    ]
