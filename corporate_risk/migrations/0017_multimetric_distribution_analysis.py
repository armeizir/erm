from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("corporate_risk", "0016_multimetricmontecarloresult_dampak_base_case_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="multimetricmontecarloresult",
            name="recommended_distribution",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="multimetricmontecarloresult",
            name="distribution_reason_summary",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="multimetricmontecarloresult",
            name="distribution_reason_detail",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="multimetricmontecarloresult",
            name="distribution_limitations",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="multimetricmontecarloresult",
            name="distribution_confidence",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="multimetricmontecarloresult",
            name="distribution_data_quality_warnings",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="multimetricmontecarloresult",
            name="selected_distribution",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="multimetricmontecarloresult",
            name="selected_distribution_justification",
            field=models.TextField(blank=True),
        ),
    ]
