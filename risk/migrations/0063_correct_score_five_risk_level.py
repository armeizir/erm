from django.db import migrations


def correct_score_five_level(apps, schema_editor):
    MasterLevelRisiko = apps.get_model("risk", "MasterLevelRisiko")
    RiskMatrix = apps.get_model("risk", "RiskMatrix")

    levels = {
        level.kode: level
        for level in MasterLevelRisiko.objects.filter(
            kode__in=["LOW", "LOW_TO_MODERATE", "MODERATE", "MODERATE_TO_HIGH", "HIGH"]
        )
    }
    for matrix in RiskMatrix.objects.filter(ukuran=5, aktif=True):
        for cell in matrix.cells.all():
            if cell.skor <= 5:
                level = levels["LOW"]
            elif cell.skor <= 11:
                level = levels["LOW_TO_MODERATE"]
            elif cell.skor <= 15:
                level = levels["MODERATE"]
            elif cell.skor <= 19:
                level = levels["MODERATE_TO_HIGH"]
            else:
                level = levels["HIGH"]
            cell.level_risiko = level
            cell.warna_hex = level.warna_hex
            cell.save(update_fields=["level_risiko", "warna_hex"])


class Migration(migrations.Migration):
    dependencies = [("risk", "0062_update_default_risk_matrix")]
    operations = [migrations.RunPython(correct_score_five_level, migrations.RunPython.noop)]
