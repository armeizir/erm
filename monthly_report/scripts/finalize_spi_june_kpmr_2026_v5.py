"""Finalizer KPMR SPI Juni 2026 / TW II V5 (dynamic report resolver).

Dry run:
  python monthly_report/scripts/finalize_spi_june_kpmr_2026_v5.py

Apply only after exact output 81/FAIR:
  python monthly_report/scripts/finalize_spi_june_kpmr_2026_v5.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.dev")

import django
django.setup()

from django.db import transaction
from monthly_report.models import MonthlyRiskReport
from risk.services.kpmr_automation import calculate_kpmr_for_report, save_kpmr_calculation

EXPECTED_TOTAL = Decimal("81.00")
EXPECTED_RATING = "FAIR"
EXPECTED = {
    "I1": (Decimal("60.00"), Decimal("18.00"), "b"),
    "I2": (Decimal("100.00"), Decimal("20.00"), "a"),
    "I3": (Decimal("80.00"), Decimal("16.00"), "a"),
    "I4": (Decimal("90.00"), Decimal("27.00"), "a,a,a,a"),
}


def get_spi_june_report():
    candidates = list(
        MonthlyRiskReport.objects
        .select_related("reassessment", "reassessment__unit_bisnis", "periode")
        .filter(
            reassessment__tahun=2026,
            reassessment__unit_bisnis__name__icontains="SPI",
            periode__tanggal_mulai__year=2026,
            periode__tanggal_mulai__month=6,
        )
        .order_by("id")
    )
    if len(candidates) != 1:
        detail = "\n".join(
            f"- report={r.id} | profile={r.reassessment_id} | "
            f"unit={r.reassessment.unit_bisnis} | periode={r.periode} | "
            f"items={r.items.count()} | {r}"
            for r in candidates
        )
        raise RuntimeError(
            "SPI Juni 2026 harus tepat satu report. "
            f"Ditemukan {len(candidates)}:\n{detail}"
        )
    return candidates[0]


def q(v):
    return None if v is None else Decimal(v).quantize(Decimal("0.01"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    report = get_spi_june_report()

    calc = calculate_kpmr_for_report(report)
    inds = {x["kode"]: x for x in calc.indicators}
    errors = []

    print("=" * 82)
    print("KPMR SPI - JUNI 2026 / SNAPSHOT TW II V5")
    print("=" * 82)
    print("Report ID         :", report.id)
    print("Report            :", report)
    print("Jumlah item       :", report.items.count())
    print("Logical risk event: 15")
    print("Treatment items   : 22")

    if report.items.count() != 22:
        errors.append(f"Jumlah item {report.items.count()} != 22")

    for code in ("I1", "I2", "I3", "I4"):
        ind = inds.get(code)
        if not ind:
            errors.append(f"{code} tidak ditemukan")
            continue
        raw, weighted, answer = EXPECTED[code]
        actual_answer = str(ind.get("jawaban") or "").replace(" ", "").lower()
        print(
            f"{code}: hasil={q(ind.get('hasil'))} | "
            f"skor={q(ind.get('skor'))} | jawaban={ind.get('jawaban') or '-'}"
        )
        if q(ind.get("hasil")) != raw:
            errors.append(f"{code} hasil != {raw}")
        if q(ind.get("skor")) != weighted:
            errors.append(f"{code} skor != {weighted}")
        if code != "I4" and actual_answer != answer:
            errors.append(f"{code} jawaban != {answer}")
        if code == "I4" and actual_answer and actual_answer != answer:
            errors.append(f"I4 jawaban {actual_answer} != {answer}")

    print("-" * 82)
    print("TOTAL KPMR        :", q(calc.score_total))
    print("RATING            :", calc.rating)

    if q(calc.score_total) != EXPECTED_TOTAL:
        errors.append("TOTAL != 81.00")
    if str(calc.rating).upper() != EXPECTED_RATING:
        errors.append("RATING != FAIR")

    i4 = inds.get("I4", {})
    agg = str(i4.get("jawaban") or "").replace(" ", "").lower()
    if agg:
        parts = agg.split(",")
        if len(parts) < 3 or parts[2] != "a":
            errors.append("I4.3 Rencana Perlakuan Risiko harus jawaban a")

    if errors:
        print("\nVALIDASI BELUM SESUAI - KPMR TIDAK DISIMPAN")
        for err in errors:
            print("-", err)
        raise SystemExit(2)

    print("\nVALIDASI BERHASIL: KPMR SPI = 81.00 / FAIR")
    print("I4.3 Rencana Perlakuan Risiko = jawaban a.")
    if not args.apply:
        print("DRY RUN: tidak ada data KPMR resmi yang diubah.")
        return

    with transaction.atomic():
        period = save_kpmr_calculation(calc)
    print(
        f"TERSIMPAN: KPMRPeriode id={period.id}, "
        f"skor={period.skor_total}, rating={period.rating}"
    )


if __name__ == "__main__":
    main()
