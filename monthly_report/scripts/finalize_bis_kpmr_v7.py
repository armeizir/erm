"""Audit/finalisasi KPMR BIS TW II 2026 dengan official assessment precedence.

Dry run:
  python monthly_report/scripts/finalize_bis_kpmr_v7.py

Apply:
  python monthly_report/scripts/finalize_bis_kpmr_v7.py --apply
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
from risk.models import KPMRIndikatorResmi, KPMRSubIndikatorResmi
from risk.services.kpmr_automation import calculate_kpmr_for_report, save_kpmr_calculation

EXPECTED = {
    "I1": (Decimal("60.00"), Decimal("18.00"), "b"),
    "I2": (Decimal("100.00"), Decimal("20.00"), "a"),
    "I3": (Decimal("80.00"), Decimal("16.00"), "a"),
    "I4": (Decimal("90.00"), Decimal("27.00"), "a,a,a,a"),
}


def q(value):
    return Decimal(value or 0).quantize(Decimal("0.01"))


def get_report():
    candidates = list(
        MonthlyRiskReport.objects
        .select_related("reassessment", "reassessment__unit_bisnis", "periode")
        .filter(
            reassessment__tahun=2026,
            reassessment__unit_bisnis__name__icontains="BIS",
            periode__tanggal_mulai__year=2026,
            periode__tanggal_mulai__month=6,
        )
        .order_by("id")
    )
    if len(candidates) != 1:
        raise RuntimeError(
            f"BIS Juni 2026 harus tepat satu report; ditemukan {len(candidates)}"
        )
    return candidates[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    report = get_report()
    official = {
        x.kode: x
        for x in KPMRIndikatorResmi.objects.filter(
            periode__tahun=2026,
            periode__triwulan=2,
            periode__unit_bisnis=report.reassessment.unit_bisnis,
        )
    }

    required = {"I1", "I2", "I3", "I4"}
    missing = required - set(official)
    if missing:
        raise RuntimeError(f"Indikator resmi BIS belum lengkap: {sorted(missing)}")

    official_subs = {
        x.kode: x
        for x in KPMRSubIndikatorResmi.objects.filter(indikator=official["I4"])
    }
    required_subs = {"IDENTIFIKASI", "KUANTIFIKASI", "RENCANA", "PRIORITISASI"}
    missing_subs = required_subs - set(official_subs)
    if missing_subs:
        raise RuntimeError(
            f"Subindikator resmi I4 BIS belum lengkap: {sorted(missing_subs)}"
        )

    calc = calculate_kpmr_for_report(report)
    by = {x["kode"]: x for x in calc.indicators}
    errors = []

    print("=" * 96)
    print("KPMR BID BIS - TW II 2026 - OFFICIAL ASSESSMENT PRECEDENCE V7")
    print("=" * 96)
    print("Report :", report.id, "-", report)
    print("Unit   :", report.reassessment.unit_bisnis)
    print("Items  :", report.items.count(), "(monitoring detail tetap dipertahankan)")
    print()

    for code in ("I1", "I2", "I3", "I4"):
        ind = by[code]
        raw = q(ind["hasil"])
        score = q(ind["skor"])
        answer = str(ind.get("jawaban") or "")
        print(f"{code}: hasil={raw} | skor={score} | jawaban={answer or '-'}")

        eraw, escore, eanswer = EXPECTED[code]
        if raw != eraw:
            errors.append(f"{code} hasil {raw} != {eraw}")
        if score != escore:
            errors.append(f"{code} skor {score} != {escore}")
        if answer != eanswer:
            errors.append(f"{code} jawaban {answer!r} != {eanswer!r}")

    i4_subs = {x["kode"]: x for x in by["I4"].get("subindikator") or []}
    rencana = i4_subs.get("RENCANA")
    if not rencana or rencana.get("jawaban") != "a":
        errors.append("I4.3/RENCANA harus jawaban resmi a")

    print("-" * 96)
    print("TOTAL  :", q(calc.score_total))
    print("RATING :", calc.rating)
    print()
    print("OFFICIAL USER ASSESSMENT")
    print("I1=b | I2=a | I3=a | I4=a,a,a,a | I4.3/RENCANA=a")
    print(
        "I1 workbook user: Total Exposure Target = 150,490,808,780 dan "
        "Total Exposure Residual = 150,490,808,780 => b / 60 / skor 18."
    )
    print(
        "I4.3: perubahan profil sampai dengan Juni 2026 masih diakomodasi; "
        "jawaban resmi BIS TW II = a."
    )

    if q(calc.score_total) != Decimal("81.00"):
        errors.append(f"Total {q(calc.score_total)} != 81.00")
    if str(calc.rating).upper() != "FAIR":
        errors.append(f"Rating {calc.rating} != FAIR")

    if errors:
        print("\nVALIDASI GAGAL - KPMR TIDAK DISIMPAN")
        for error in errors:
            print("-", error)
        raise SystemExit(2)

    print("\nVALIDASI BERHASIL: KPMR BID BIS = 81.00 / FAIR")
    print("I4.3 RENCANA = a sesuai asesmen resmi User.")

    if not args.apply:
        print("DRY RUN: tidak ada KPMR resmi yang diubah.")
        return

    with transaction.atomic():
        period = save_kpmr_calculation(calc)
        marker = "Official assessment precedence BIS TW II 2026"
        note = (
            marker + ": I1=b, I2=a, I3=a, I4=a,a,a,a; "
            "I4.3/RENCANA=a. Perubahan profil sampai dengan Juni 2026 "
            "masih diakomodasi sesuai kebijakan Sub Bidang Manajemen Risiko. "
            "Monitoring Juni tetap menggunakan 17 item detail."
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
