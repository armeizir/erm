from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("risk", "0060_appsetting_monthly_report_notification_test_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="kpmrindikatorresmi",
            name="jawaban",
            field=models.CharField(
                blank=True,
                max_length=50,
                null=True,
                verbose_name="Jawaban / Opsi",
            ),
        ),
    ]
