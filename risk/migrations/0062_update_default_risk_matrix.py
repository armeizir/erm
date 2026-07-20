from django.db import migrations


LEVELS = [
    ("LOW", "Low", "#00B050", 1),
    ("LOW_TO_MODERATE", "Low to Moderate", "#92D050", 2),
    ("MODERATE", "Moderate", "#FFFF00", 3),
    ("MODERATE_TO_HIGH", "Moderate to High", "#FFC000", 4),
    ("HIGH", "High", "#FF0000", 5),
]

SCORES = {
    1: (1, 5, 10, 15, 20),
    2: (2, 6, 11, 16, 21),
    3: (3, 8, 13, 18, 23),
    4: (4, 9, 14, 19, 24),
    5: (7, 12, 17, 22, 25),
}


def update_matrix(apps, schema_editor):
    MasterLevelRisiko = apps.get_model("risk", "MasterLevelRisiko")
    MasterSkalaDampak = apps.get_model("risk", "MasterSkalaDampak")
    MasterSkalaProbabilitas = apps.get_model("risk", "MasterSkalaProbabilitas")
    RiskMatrix = apps.get_model("risk", "RiskMatrix")

    levels = {}
    for code, name, color, order in LEVELS:
        level, _ = MasterLevelRisiko.objects.update_or_create(
            kode=code,
            defaults={
                "nama": name,
                "warna_hex": color,
                "urutan": order,
                "aktif": True,
            },
        )
        levels[code] = level

    impact_names = ("Sangat Rendah", "Rendah", "Menengah", "Tinggi", "Sangat Tinggi")
    likelihood_names = (
        "Hampir Tidak Pernah Terjadi",
        "Jarang Terjadi",
        "Mungkin Terjadi",
        "Sering Terjadi",
        "Hampir Selalu Terjadi",
    )
    impacts = list(MasterSkalaDampak.objects.order_by("urutan", "id")[:5])
    likelihoods = list(MasterSkalaProbabilitas.objects.order_by("urutan", "id")[:5])
    for order, (scale, name) in enumerate(zip(impacts, impact_names), start=1):
        scale.nama = name
        scale.urutan = order
        scale.aktif = True
        scale.save(update_fields=["nama", "urutan", "aktif"])
    for order, (scale, name) in enumerate(zip(likelihoods, likelihood_names), start=1):
        scale.nama = name
        scale.urutan = order
        scale.aktif = True
        scale.save(update_fields=["nama", "urutan", "aktif"])

    # Perbarui seluruh matriks 5x5 aktif karena laporan dapat menunjuk matriks
    # non-default yang dibuat sebelum matriks acuan ini diberlakukan.
    matrices = RiskMatrix.objects.filter(ukuran=5, aktif=True)

    for matrix in matrices:
        for cell in matrix.cells.select_related(
            "skala_dampak", "skala_probabilitas"
        ).all():
            impact = cell.skala_dampak.urutan
            likelihood = cell.skala_probabilitas.urutan
            if likelihood not in SCORES or not 1 <= impact <= 5:
                continue
            score = SCORES[likelihood][impact - 1]
            if score <= 4:
                level = levels["LOW"]
            elif score <= 11:
                level = levels["LOW_TO_MODERATE"]
            elif score <= 15:
                level = levels["MODERATE"]
            elif score <= 19:
                level = levels["MODERATE_TO_HIGH"]
            else:
                level = levels["HIGH"]
            cell.skor = score
            cell.level_risiko = level
            cell.warna_hex = level.warna_hex
            cell.aktif = True
            cell.save(update_fields=["skor", "level_risiko", "warna_hex", "aktif"])


class Migration(migrations.Migration):
    dependencies = [("risk", "0061_kpmrindikatorresmi_jawaban")]
    operations = [migrations.RunPython(update_matrix, migrations.RunPython.noop)]
