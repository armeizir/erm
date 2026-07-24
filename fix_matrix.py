import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.dev")
django.setup()

from risk.models import (
    RiskMatrix,
    RiskMatrixCell,
    MasterSkalaProbabilitas,
    MasterSkalaDampak,
    MasterLevelRisiko,
)

matrix = RiskMatrix.objects.filter(is_default=True, aktif=True).first()

level_rendah = MasterLevelRisiko.objects.get(kode="LOW")
level_sedang = MasterLevelRisiko.objects.get(kode="MEDIUM")
level_tinggi = MasterLevelRisiko.objects.get(kode="HIGH")
level_ekstrem = MasterLevelRisiko.objects.get(kode="EXTREME")

# create skala
for i in range(1, 6):
    MasterSkalaProbabilitas.objects.get_or_create(
        urutan=i,
        defaults={"nama": f"Skala {i}", "aktif": True}
    )
    MasterSkalaDampak.objects.get_or_create(
        urutan=i,
        defaults={"nama": f"Skala {i}", "aktif": True}
    )

# reset matrix
RiskMatrixCell.objects.filter(matrix=matrix).delete()

# isi matrix
for prob in range(1, 6):
    for dampak in range(1, 6):

        prob_obj = MasterSkalaProbabilitas.objects.get(urutan=prob)
        dampak_obj = MasterSkalaDampak.objects.get(urutan=dampak)

        # override lampiran 2
        if (prob, dampak) in [(5,5), (4,4), (2,4)]:
            level = level_tinggi
            color = "#F4A000"

        elif (prob, dampak) in [(2,5), (1,5)]:
            level = level_ekstrem
            color = "#D00000"

        elif (prob, dampak) == (1,4):
            level = level_sedang
            color = "#FFFF00"

        else:
            score = prob * dampak

            if score <= 4:
                level = level_rendah
                color = "#548235"
            elif score <= 9:
                level = level_sedang
                color = "#FFFF00"
            elif score <= 16:
                level = level_tinggi
                color = "#F4A000"
            else:
                level = level_ekstrem
                color = "#D00000"

        RiskMatrixCell.objects.create(
            matrix=matrix,
            skala_probabilitas=prob_obj,
            skala_dampak=dampak_obj,
            skor=prob * dampak,
            level_risiko=level,
            warna_hex=color,
            aktif=True,
        )

print("DONE:", RiskMatrixCell.objects.filter(matrix=matrix).count())