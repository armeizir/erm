"""Finalisasi KPMR SPI TW II sesuai asesmen user.

Expected:
I1 = 90 x 30% = 27
I2 = 100 x 20% = 20
I3 = 80 x 20% = 16
I4 = 90 x 30% = 27
TOTAL = 90 / SATISFACTORY
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
from risk.services.kpmr_automation import (
    _aggregate_exposure_for_i1,
    calculate_kpmr_for_report,
    save_kpmr_calculation,
)

EXPECTED_TOTAL = Decimal("90.00")
EXPECTED_RATING = "SATISFACTORY"
EXPECTED = {
    "I1": (Decimal("90.00"), Decimal("27.00"), "a"),
    "I2": (Decimal("100.00"), Decimal("20.00"), "a"),
    "I3": (Decimal("80.00"), Decimal("16.00"), "a"),
    "I4": (Decimal("90.00"), Decimal("27.00"), ""),
}


def q(v):
    return None if v is None else Decimal(v).quantize(Decimal("0.01"))


def get_report():
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
        raise RuntimeError(f"SPI Juni 2026 harus tepat satu report; ditemukan {len(candidates)}")
    return candidates[0]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    report = get_report()
    calc = calculate_kpmr_for_report(report)
    by = {x["kode"]: x for x in calc.indicators}
    exposure = _aggregate_exposure_for_i1(
        list(report.items.select_related("risk_event").all()),
        2,
    )
    errors = []

    print("=" * 84)
    print("KPMR SPI - KOREKSI SESUAI ASESMEN USER")
    print("=" * 84)
    print(f"Report                : {report.id} - {report}")
    print(f"Treatment items       : {report.items.count()}")
    if exposure:
        print(f"Top-risk/group        : {exposure['group_count']}")
        print(f"Total Exposure Target : {exposure['total_target']:,.2f}")
        print(f"Total Exposure Residual: {exposure['total_residual']:,.2f}")
    print()

    if report.items.count() != 22:
        errors.append(f"Jumlah treatment item {report.items.count()} != 22")
    if exposure is None:
        errors.append("Exposure summary tidak tersedia")
    else:
        if exposure["group_count"] != 9:
            errors.append(f"Top-risk/group {exposure['group_count']} != 9")
        if exposure["total_target"] != Decimal("4423810890"):
            errors.append("Total Exposure Target tidak sama data user")
        if exposure["total_residual"] != Decimal("3756065850"):
            errors.append("Total Exposure Residual tidak sama data user")

    for code in ("I1", "I2", "I3", "I4"):
        ind = by.get(code)
        if not ind:
            errors.append(f"{code} tidak ditemukan")
            continue
        actual_raw = q(ind.get("hasil"))
        actual_score = q(ind.get("skor"))
        actual_answer = str(ind.get("jawaban") or "").strip().lower()
        expected_raw, expected_score, expected_answer = EXPECTED[code]
        print(
            f"{code}: hasil={actual_raw} | skor={actual_score} | "
            f"jawaban={actual_answer or '-'}"
        )
        if actual_raw != expected_raw:
            errors.append(f"{code} hasil {actual_raw} != {expected_raw}")
        if actual_score != expected_score:
            errors.append(f"{code} skor {actual_score} != {expected_score}")
        if code != "I4" and actual_answer != expected_answer:
            errors.append(f"{code} jawaban {actual_answer!r} != {expected_answer!r}")

    i4 = by.get("I4") or {}
    plan_sub = next(
        (
            s for s in (i4.get("subindikator") or [])
            if s.get("kode") == "RENCANA"
        ),
        None,
    )
    if not plan_sub or str(plan_sub.get("jawaban") or "").lower() != "a":
        errors.append("I4.3/RENCANA harus jawaban a")

    print("-" * 84)
    print("TOTAL KPMR        :", q(calc.score_total))
    print("RATING            :", calc.rating)

    if q(calc.score_total) != EXPECTED_TOTAL:
        errors.append(f"Total {q(calc.score_total)} != 90.00")
    if str(calc.rating).upper() != EXPECTED_RATING:
        errors.append(f"Rating {calc.rating} != SATISFACTORY")

    if errors:
        print("\nVALIDASI GAGAL - TIDAK ADA KPMR YANG DISIMPAN")
        for err in errors:
            print("-", err)
        raise SystemExit(2)

    print("\nVALIDASI BERHASIL: KPMR SPI = 90.00 / SATISFACTORY")
    print("I1 mengikuti asesmen user: 3,756,065,850 < 4,423,810,890 => a / 90 / 27.")
    print("I4.3 Rencana Perlakuan Risiko = a.")

    if not args.apply:
        print("DRY RUN: tidak ada data KPMR resmi yang diubah.")
        return

    with transaction.atomic():
        period = save_kpmr_calculation(calc)
        marker = "Koreksi asesmen user KPMR SPI TW II 2026"
        note = (
            "Koreksi asesmen user KPMR SPI TW II 2026: "
            "I1 menggunakan perbandingan agregat Total Exposure Residual "
            "3.756.065.850 terhadap Total Exposure Target 4.423.810.890; "
            "jawaban a, hasil 90, skor berbobot 27. Total KPMR 90 (SATISFACTORY)."
        )
        if marker not in (period.catatan or ""):
            period.catatan = ((period.catatan or "") + "\n\n" + note).strip()
            period.save(update_fields=["catatan"])

    print(
        f"TERSIMPAN: KPMRPeriode id={period.id}, "
        f"skor={period.skor_total}, rating={period.rating}"
    )


if __name__ == "__main__":
    main()
