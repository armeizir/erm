from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("risk", "0077_add_profile_completeness_tutorial_placement"),
    ]

    operations = [
        migrations.AddField(
            model_name="rkapitem",
            name="jenis_rkap",
            field=models.CharField(
                choices=[
                    ("TARGET", "Target / Parameter RKAP"),
                    ("LABA_RUGI", "Laba Rugi RKAP"),
                    ("NERACA", "Neraca RKAP"),
                    ("LAINNYA", "Lainnya"),
                ],
                default="LAINNYA",
                help_text="Kelompok sumber/struktur RKAP: Target, Laba Rugi, Neraca, atau lainnya.",
                max_length=20,
                verbose_name="Jenis RKAP",
            ),
        ),
        migrations.AddField(
            model_name="rkapitem",
            name="tipe_baris",
            field=models.CharField(
                choices=[
                    ("GROUP", "Kelompok / Header"),
                    ("SUBTOTAL", "Subtotal / Total"),
                    ("DATA", "Data / Parameter"),
                    ("FORMULA", "Formula / Derived"),
                ],
                default="DATA",
                help_text="Menandai apakah item merupakan header, subtotal/total, data, atau formula.",
                max_length=20,
                verbose_name="Tipe Baris",
            ),
        ),
        migrations.AddField(
            model_name="rkapitem",
            name="polaritas",
            field=models.CharField(
                choices=[
                    ("POSITIF", "Positif"),
                    ("NEGATIF", "Negatif"),
                    ("NETRAL", "Netral"),
                ],
                default="NETRAL",
                help_text="Arah kinerja parameter untuk evaluasi RKAP vs realisasi.",
                max_length=10,
                verbose_name="Polaritas",
            ),
        ),
    ]
