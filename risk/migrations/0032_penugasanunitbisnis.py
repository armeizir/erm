from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("risk", "0031_profilrisikokorporatitem_rcc_modes"),
    ]

    operations = [
        migrations.CreateModel(
            name="PenugasanUnitBisnis",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("peran", models.CharField(choices=[("PAIRING_OFFICER", "Pairing Officer"), ("RISK_CHAMPION", "Risk Champion"), ("RISK_OFFICER", "Risk Officer")], max_length=30, verbose_name="Peran")),
                ("aktif", models.BooleanField(default=True, verbose_name="Aktif")),
                ("catatan", models.CharField(blank=True, max_length=255, null=True, verbose_name="Catatan")),
                ("dibuat_pada", models.DateTimeField(auto_now_add=True, verbose_name="Dibuat Pada")),
                ("unit_bisnis", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="penugasan_pengguna", to="auth.group", verbose_name="Bidang / Unit Bisnis")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="penugasan_unit_bisnis", to=settings.AUTH_USER_MODEL, verbose_name="User")),
            ],
            options={
                "verbose_name": "Penugasan User Unit Bisnis",
                "verbose_name_plural": "MASTER — Penugasan User Unit Bisnis",
                "ordering": ["unit_bisnis__name", "peran", "user__username"],
            },
        ),
        migrations.AddConstraint(
            model_name="penugasanunitbisnis",
            constraint=models.UniqueConstraint(fields=("user", "unit_bisnis", "peran"), name="unik_user_unit_bisnis_peran"),
        ),
    ]
