import django.db.models.deletion
from django.db import migrations, models


def seed_risk_matrix(apps, schema_editor):
    MasterLevelRisiko = apps.get_model("risk", "MasterLevelRisiko")
    RiskMatrix = apps.get_model("risk", "RiskMatrix")
    RiskMatrixCell = apps.get_model("risk", "RiskMatrixCell")
    MasterSkalaDampak = apps.get_model("risk", "MasterSkalaDampak")
    MasterSkalaProbabilitas = apps.get_model("risk", "MasterSkalaProbabilitas")

    level_definitions = [
        ("LOW", "Rendah", "#22c55e", 1),
        ("MEDIUM", "Sedang", "#eab308", 2),
        ("HIGH", "Tinggi", "#f97316", 3),
        ("EXTREME", "Ekstrem", "#ef4444", 4),
    ]

    level_map = {}
    for kode, nama, warna, urutan in level_definitions:
        obj, _ = MasterLevelRisiko.objects.get_or_create(
            kode=kode,
            defaults={
                "nama": nama,
                "warna_hex": warna,
                "aktif": True,
                "urutan": urutan,
            },
        )
        level_map[kode] = obj

    matrix, _ = RiskMatrix.objects.get_or_create(
        kode="RM5X5",
        defaults={
            "nama": "Risk Matrix 5x5 Default",
            "ukuran": 5,
            "aktif": True,
            "is_default": True,
        },
    )

    dampak_list = list(MasterSkalaDampak.objects.order_by("urutan", "id")[:5])
    probabilitas_list = list(MasterSkalaProbabilitas.objects.order_by("urutan", "id")[:5])

    if len(dampak_list) < 5 or len(probabilitas_list) < 5:
        return

    def get_level_by_score(score):
        if score <= 5:
            return level_map["LOW"]
        elif score <= 10:
            return level_map["MEDIUM"]
        elif score <= 15:
            return level_map["HIGH"]
        return level_map["EXTREME"]

    for p_idx, probabilitas in enumerate(probabilitas_list, start=1):
        for d_idx, dampak in enumerate(dampak_list, start=1):
            skor = d_idx * p_idx
            level = get_level_by_score(skor)
            RiskMatrixCell.objects.get_or_create(
                matrix=matrix,
                skala_dampak=dampak,
                skala_probabilitas=probabilitas,
                defaults={
                    "skor": skor,
                    "level_risiko": level,
                    "warna_hex": level.warna_hex,
                    "aktif": True,
                },
            )


def unseed_risk_matrix(apps, schema_editor):
    RiskMatrixCell = apps.get_model("risk", "RiskMatrixCell")
    RiskMatrix = apps.get_model("risk", "RiskMatrix")
    MasterLevelRisiko = apps.get_model("risk", "MasterLevelRisiko")

    RiskMatrixCell.objects.filter(matrix__kode="RM5X5").delete()
    RiskMatrix.objects.filter(kode="RM5X5").delete()
    MasterLevelRisiko.objects.filter(kode__in=["LOW", "MEDIUM", "HIGH", "EXTREME"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("risk", "0021_remove_reassessmentitem_level_nilai_risiko_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="MasterLevelRisiko",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kode", models.CharField(max_length=50, unique=True, verbose_name="Kode")),
                ("nama", models.CharField(max_length=100, verbose_name="Nama Level Risiko")),
                ("warna_hex", models.CharField(blank=True, max_length=7, null=True, verbose_name="Warna")),
                ("aktif", models.BooleanField(default=True, verbose_name="Aktif")),
                ("urutan", models.PositiveIntegerField(default=1, verbose_name="Urutan")),
            ],
            options={
                "verbose_name": "MASTER — Level Risiko",
                "verbose_name_plural": "MASTER — Level Risiko",
                "ordering": ["urutan", "nama"],
            },
        ),
        migrations.CreateModel(
            name="RiskMatrix",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kode", models.CharField(max_length=50, unique=True, verbose_name="Kode")),
                ("nama", models.CharField(max_length=100, verbose_name="Nama Matriks Risiko")),
                ("ukuran", models.PositiveSmallIntegerField(default=5, verbose_name="Ukuran")),
                ("aktif", models.BooleanField(default=True, verbose_name="Aktif")),
                ("is_default", models.BooleanField(default=False, verbose_name="Default")),
            ],
            options={
                "verbose_name": "MASTER — Matriks Risiko",
                "verbose_name_plural": "MASTER — Matriks Risiko",
                "ordering": ["kode", "nama"],
            },
        ),
        migrations.AddField(
            model_name="reassessmentsummary",
            name="risk_matrix",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reassessment_summary",
                to="risk.riskmatrix",
                verbose_name="Matriks Risiko",
            ),
        ),
        migrations.CreateModel(
            name="RiskMatrixCell",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("skor", models.PositiveSmallIntegerField(verbose_name="Skor")),
                ("warna_hex", models.CharField(blank=True, max_length=7, null=True, verbose_name="Warna")),
                ("aktif", models.BooleanField(default=True, verbose_name="Aktif")),
                (
                    "level_risiko",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="risk_matrix_cells",
                        to="risk.masterlevelrisiko",
                        verbose_name="Level Risiko",
                    ),
                ),
                (
                    "matrix",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cells",
                        to="risk.riskmatrix",
                        verbose_name="Matriks Risiko",
                    ),
                ),
                (
                    "skala_dampak",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="risk_matrix_cells_dampak",
                        to="risk.masterskaladampak",
                        verbose_name="Skala Dampak",
                    ),
                ),
                (
                    "skala_probabilitas",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="risk_matrix_cells_probabilitas",
                        to="risk.masterskalaprobabilitas",
                        verbose_name="Skala Probabilitas",
                    ),
                ),
            ],
            options={
                "verbose_name": "MASTER — Sel Matriks Risiko",
                "verbose_name_plural": "MASTER — Sel Matriks Risiko",
                "ordering": ["matrix", "skala_probabilitas__urutan", "skala_dampak__urutan"],
            },
        ),
        migrations.AddConstraint(
            model_name="riskmatrixcell",
            constraint=models.UniqueConstraint(
                fields=("matrix", "skala_dampak", "skala_probabilitas"),
                name="unik_sel_matrix_per_dampak_probabilitas",
            ),
        ),
        migrations.RunPython(seed_risk_matrix, unseed_risk_matrix),
    ]