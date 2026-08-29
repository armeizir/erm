from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("monthly_report", "0026_add_realisasi_pic_organization_unit"),
    ]

    operations = [
        migrations.AddField(
            model_name="monthlyriskreportitem",
            name="realisasi_timeline_1",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Realisasi Timeline Januari"),
        ),
        migrations.AddField(
            model_name="monthlyriskreportitem",
            name="realisasi_timeline_2",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Realisasi Timeline Februari"),
        ),
        migrations.AddField(
            model_name="monthlyriskreportitem",
            name="realisasi_timeline_3",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Realisasi Timeline Maret"),
        ),
        migrations.AddField(
            model_name="monthlyriskreportitem",
            name="realisasi_timeline_4",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Realisasi Timeline April"),
        ),
        migrations.AddField(
            model_name="monthlyriskreportitem",
            name="realisasi_timeline_5",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Realisasi Timeline Mei"),
        ),
        migrations.AddField(
            model_name="monthlyriskreportitem",
            name="realisasi_timeline_6",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Realisasi Timeline Juni"),
        ),
        migrations.AddField(
            model_name="monthlyriskreportitem",
            name="realisasi_timeline_7",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Realisasi Timeline Juli"),
        ),
        migrations.AddField(
            model_name="monthlyriskreportitem",
            name="realisasi_timeline_8",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Realisasi Timeline Agustus"),
        ),
        migrations.AddField(
            model_name="monthlyriskreportitem",
            name="realisasi_timeline_9",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Realisasi Timeline September"),
        ),
        migrations.AddField(
            model_name="monthlyriskreportitem",
            name="realisasi_timeline_10",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Realisasi Timeline Oktober"),
        ),
        migrations.AddField(
            model_name="monthlyriskreportitem",
            name="realisasi_timeline_11",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Realisasi Timeline November"),
        ),
        migrations.AddField(
            model_name="monthlyriskreportitem",
            name="realisasi_timeline_12",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Realisasi Timeline Desember"),
        ),
    ]
