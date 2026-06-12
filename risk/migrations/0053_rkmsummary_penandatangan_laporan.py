# Generated manually on 2026-06-11

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("risk", "0052_rkmitem_anggaran_rp_ribu_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="rkmsummary",
            name="penandatangan_laporan_km",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="rkm_laporan_km_ditandatangani",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Penandatangan Laporan KM",
            ),
        ),
        migrations.AddField(
            model_name="rkmsummary",
            name="penandatangan_laporan_rkm",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="rkm_laporan_rkm_ditandatangani",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Penandatangan Laporan RKM",
            ),
        ),
    ]
