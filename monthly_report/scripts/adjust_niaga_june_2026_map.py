"""Align the June 2026 NIAGA risk map with the approved reference image.

Run an audit first, then apply:
    python monthly_report/scripts/adjust_niaga_june_2026_map.py
    python monthly_report/scripts/adjust_niaga_june_2026_map.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.dev")

import django

django.setup()

from django.db import transaction

from monthly_report.models import MonthlyRiskReport
from monthly_report.services import refresh_monthly_report_summary
from risk.models import MasterSkalaDampak, MasterSkalaProbabilitas, ReAssessmentSummary


YEAR = 2026
MONTH = 6
PROFILE = "Profil Risiko NIAGA"
UNIT = "BID AGA"

# risk number: (impact, likelihood). Blue markers in the reference image.
INHERENT_Q2 = {
    1: (5, 4), 2: (2, 4), 3: (1, 3), 4: (3, 2),
    5: (1, 1), 6: (3, 1), 7: (1, 1), 8: (1, 1),
    9: (5, 4), 10: (1, 1), 11: (3, 5), 12: (3, 2),
    13: (1, 1), 14: (1, 1),
}

# White markers in the reference image. Risk 14 has no residual marker.
RESIDUAL_JUNE = {
    1: (5, 5), 2: (2, 3), 3: (1, 3), 4: (1, 2),
    5: (1, 2), 6: (3, 1), 7: (1, 1), 8: (1, 1),
    9: (5, 5), 10: (1, 5), 11: (1, 1), 12: (1, 1),
    13: (1, 1), 14: (None, None),
}


def main(apply: bool) -> None:
    profile = ReAssessmentSummary.objects.get(
        judul=PROFILE, tahun=YEAR, unit_bisnis__name=UNIT
    )
    report = MonthlyRiskReport.objects.get(
        reassessment=profile,
        periode__tanggal_mulai__year=YEAR,
        periode__tanggal_mulai__month=MONTH,
    )
    events = {item.no_item: item for item in profile.item.all()}
    report_items = {item.risk_event.no_item: item for item in report.items.select_related("risk_event")}

    expected = set(range(1, 15))
    if set(events) != expected or set(report_items) != expected:
        raise RuntimeError(
            f"Nomor risiko harus 1..14; profil={sorted(events)}, laporan={sorted(report_items)}"
        )

    impacts = {s.urutan: s for s in MasterSkalaDampak.objects.filter(aktif=True)}
    likelihoods = {s.urutan: s for s in MasterSkalaProbabilitas.objects.filter(aktif=True)}
    if set(impacts) != set(range(1, 6)) or set(likelihoods) != set(range(1, 6)):
        raise RuntimeError("Master skala aktif harus lengkap dari urutan 1 sampai 5.")

    print(f"Laporan: {report} (id={report.pk})")
    print("Mode:", "APPLY" if apply else "AUDIT SAJA")
    for number in sorted(expected):
        print(number, "inheren Q2", INHERENT_Q2[number], "residual", RESIDUAL_JUNE[number])

    if not apply:
        print("Tidak ada data diubah. Jalankan kembali dengan --apply.")
        return

    with transaction.atomic():
        for number, (impact, likelihood) in INHERENT_Q2.items():
            event = events[number]
            event.skala_dampak_q2 = impacts[impact]
            event.skala_probabilitas_q2 = likelihoods[likelihood]
            event.save()

        for number, (impact, likelihood) in RESIDUAL_JUNE.items():
            item = report_items[number]
            item.realisasi_skala_dampak = impacts.get(impact)
            item.realisasi_skala_probabilitas = likelihoods.get(likelihood)
            item.save()

        refresh_monthly_report_summary(report)

    report.refresh_from_db()
    print(
        "SELESAI:",
        f"total_risiko={report.total_risiko}",
        f"total_high={report.total_high}",
        f"total_mitigasi_terlambat={report.total_mitigasi_terlambat}",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    main(args.apply)
