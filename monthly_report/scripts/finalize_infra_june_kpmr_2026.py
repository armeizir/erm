"""Audit/finalisasi KPMR UB INFRA Juni 2026 (snapshot resmi TW II).

Dry run:
    python monthly_report/scripts/finalize_infra_june_kpmr_2026.py

Simpan hanya jika hasil aktual tervalidasi 81 / FAIR:
    python monthly_report/scripts/finalize_infra_june_kpmr_2026.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.dev")

import django

django.setup()

from django.db import transaction
from monthly_report.models import MonthlyRiskReport
from risk.services.kpmr_automation import calculate_kpmr_for_report, save_kpmr_calculation

EXPECTED_ITEM_COUNT = 37
EXPECTED_TOTAL = Decimal("81.00")
EXPECTED_RATING = "FAIR"
EXPECTED = {
    "I1": (Decimal("60.00"), Decimal("18.00")),
    "I2": (Decimal("100.00"), Decimal("20.00")),
    "I3": (Decimal("80.00"), Decimal("16.00")),
    "I4": (Decimal("90.00"), Decimal("27.00")),
}


def q(value):
    if value is None:
        return None
    return Decimal(value).quantize(Decimal("0.01"))


def find_report():
    qs = (
        MonthlyRiskReport.objects.select_related("reassessment", "reassessment__unit_bisnis", "periode")
        .filter(
            reassessment__tahun=2026,
            reassessment__unit_bisnis__name__icontains="INFRA",
            periode__tanggal_mulai__month=6,
        )
        .order_by("-id")
    )
    reports = list(qs)
    if not reports:
        raise SystemExit("ERROR: Laporan UB INFRA Juni 2026 tidak ditemukan.")
    # Prefer known canonical report 38 when present; otherwise newest matching report.
    return next((r for r in reports if r.id == 38), reports[0])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    report = find_report()
    calc = calculate_kpmr_for_report(report)
    by_code = {i["kode"]: i for i in calc.indicators}

    print("=" * 78)
    print("KPMR UB INFRA - JUNI 2026 / SNAPSHOT TW II")
    print("=" * 78)
    print(f"Report ID         : {report.id}")
    print(f"Report            : {report}")
    print(f"Jumlah item       : {calc.item_count}")
    print()

    errors = []
    if calc.item_count != EXPECTED_ITEM_COUNT:
        errors.append(f"Jumlah item {calc.item_count}, seharusnya {EXPECTED_ITEM_COUNT}.")

    for code in ("I1", "I2", "I3", "I4"):
        row = by_code.get(code)
        if not row:
            errors.append(f"{code} tidak ditemukan.")
            continue
        hasil, skor = q(row.get("hasil")), q(row.get("skor"))
        jawaban = row.get("jawaban", "")
        print(f"{code}: hasil={hasil} | skor={skor} | jawaban={jawaban or '-'}")
        exp_hasil, exp_skor = EXPECTED[code]
        if hasil != exp_hasil or skor != exp_skor:
            errors.append(
                f"{code} berbeda: hasil/skor aktual {hasil}/{skor}, target validasi {exp_hasil}/{exp_skor}."
            )

    print("-" * 78)
    print(f"TOTAL KPMR        : {q(calc.score_total)}")
    print(f"RATING            : {calc.rating}")

    if q(calc.score_total) != EXPECTED_TOTAL:
        errors.append(f"Total aktual {q(calc.score_total)}, target validasi {EXPECTED_TOTAL}.")
    if str(calc.rating).upper() != EXPECTED_RATING:
        errors.append(f"Rating aktual {calc.rating}, target validasi {EXPECTED_RATING}.")

    if errors:
        print("\nVALIDASI GAGAL - TIDAK ADA DATA KPMR YANG DISIMPAN")
        for err in errors:
            print("-", err)
        raise SystemExit(2)

    print("\nVALIDASI BERHASIL: KPMR = 81.00 / FAIR")
    if not args.apply:
        print("DRY RUN: tidak ada data KPMR resmi yang diubah.")
        return

    with transaction.atomic():
        period = save_kpmr_calculation(calc)
    print(f"TERSIMPAN: KPMRPeriode id={period.id}, skor={period.skor_total}, rating={period.rating}")


if __name__ == "__main__":
    main()
