from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("risk", "0089_sla_chart_reference")]

    operations = [
        migrations.CreateModel(
            name="WhatsAppMonitoringDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("delivery_key", models.CharField(max_length=180, unique=True)),
                ("recipient", models.CharField(max_length=64)),
                ("report_year", models.PositiveSmallIntegerField()),
                ("report_month", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ("-sent_at",),
                "verbose_name": "Log Pengiriman WhatsApp Monitoring",
                "verbose_name_plural": "Log Pengiriman WhatsApp Monitoring",
            },
        ),
    ]
