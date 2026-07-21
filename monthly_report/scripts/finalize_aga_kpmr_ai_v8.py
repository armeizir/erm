"""Finalizer KPMR BID AGA TW II 2026 - AI Assessment V8.

Tujuan
------
Membentuk output KPMR BID AGA TW II 2026 berdasarkan:
1. Profil/Re-Assessment Risiko BID AGA yang tersedia (baseline lama 13 risiko).
2. Laporan Realisasi Risiko BID AGA Juni 2026 (snapshot 14 risiko).
3. Metodologi KPMR yang sama dengan implementasi SPI/BIS.

PENTING
-------
Kertas Kerja KPMR resmi BID AGA belum tersedia. Karena itu hasil V8 disimpan
sebagai AI ASSESSMENT / DRAFT, bukan dinyatakan sebagai asesmen resmi User.

I1 masih bersifat PROVISIONAL karena:
- Total Exposure Target yang tersedia berasal dari profil baseline 13 risiko:
  393,379,250,796
- Total Exposure Residual Juni berasal dari struktur revisi 14 risiko:
  1,409,601,834,159
- Residual > Target => c / 40 / skor 12

Output AI:
I1 = c -> 40 x 30% = 12
I2 = a -> 100 x 20% = 20
I3 = a -> 80 x 20% = 16
I4 = a,a,a,a -> 90 x 30% = 27
TOTAL = 75
I4.3/RENCANA = a untuk TW II/Juni 2026 karena perubahan profil s.d. Juni
masih diakomodasi oleh Sub Bidang Manajemen Risiko.

Dry run:
    python monthly_report/scripts/finalize_aga_kpmr_ai_v8.py

Apply/save draft AI:
    python monthly_report/scripts/finalize_aga_kpmr_ai_v8.py --apply

Script tidak mengubah MonthlyRiskReport/ReAssessmentItem. Saat --apply, script:
- membuat backup SQLite otomatis bila DB SQLite,
- menyimpan KPMRPeriode + indikator/subindikator melalui save_kpmr_calculation(),
- mempertahankan status KPMR sebagai "draft",
- menandai catatan sebagai AI PROVISIONAL agar tidak disalahartikan sebagai
  Kertas Kerja KPMR resmi.
"""
from __future__ import annotations

import argparse
import copy
import os
import shutil
import sys
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.dev")

import django

django.setup()

from django.conf import settings
from django.db import transaction

from monthly_report.models import MonthlyRiskReport
from risk.models import KPMRPeriode
from risk.services import kpmr_automation as kpmr


YEAR = 2026
MONTH = 6
QUARTER = 2
UNIT_NAME = "BID AGA"
CANONICAL_CODE = "MRR-BIDAGA-2026-06"
EXPECTED_ITEMS = 14

# Sumber angka hasil analisis dua lampiran yang diberikan User.
TARGET_EXPOSURE_13_RISK = Decimal("393379250796")
RESIDUAL_EXPOSURE_14_RISK = Decimal("1409601834159")
TOTAL_BUDGET = Decimal("10649771685")
TOTAL_ACTUAL_COST = Decimal("787636100")
DUE_OUTPUT_TARGET = Decimal("10")
DUE_OUTPUT_REALIZED = Decimal("10")

EXPECTED_TOTAL = Decimal("75.00")
EXPECTED = {
    "I1": (Decimal("40.00"), Decimal("12.00"), "c"),
    "I2": (Decimal("100.00"), Decimal("20.00"), "a"),
    "I3": (Decimal("80.00"), Decimal("16.00"), "a"),
    "I4": (Decimal("90.00"), Decimal("27.00"), "a,a,a,a"),
}

AI_MARKER = "AI PROVISIONAL KPMR BID AGA TW II 2026"


def q(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value).quantize(Decimal("0.01"))


def fmt_money(value: Decimal) -> str:
    return f"{value:,.0f}"


def find_report() -> MonthlyRiskReport:
    qs = (
        MonthlyRiskReport.objects.select_related(
            "reassessment",
            "reassessment__unit_bisnis",
            "periode",
        )
        .filter(
            reassessment__tahun=YEAR,
            reassessment__unit_bisnis__name__iexact=UNIT_NAME,
            periode__tanggal_mulai__year=YEAR,
            periode__tanggal_mulai__month=MONTH,
        )
        .order_by("id")
    )
    reports = list(qs)
    if not reports:
        raise RuntimeError("Laporan BID AGA Juni 2026 tidak ditemukan.")

    canonical = next((r for r in reports if r.kode == CANONICAL_CODE), None)
    if canonical is not None:
        report = canonical
    else:
        exact_14 = [r for r in reports if r.items.count() == EXPECTED_ITEMS]
        if len(exact_14) == 1:
            report = exact_14[0]
        elif len(reports) == 1:
            report = reports[0]
        else:
            detail = ", ".join(
                f"id={r.id}/kode={r.kode!r}/items={r.items.count()}" for r in reports
            )
            raise RuntimeError(
                "Ada lebih dari satu kandidat laporan BID AGA Juni dan report canonical "
                f"{CANONICAL_CODE!r} tidak ditemukan. Kandidat: {detail}"
            )

    if report.items.count() != EXPECTED_ITEMS:
        raise RuntimeError(
            f"Jumlah item report BID AGA Juni = {report.items.count()}, "
            f"diharapkan {EXPECTED_ITEMS}. Finalisasi dihentikan."
        )
    return report


def set_indicator(
    row: dict,
    *,
    hasil: Decimal,
    skor: Decimal,
    jawaban: str,
    keterangan: str,
) -> None:
    row["hasil"] = q(hasil)
    row["skor"] = q(skor)
    row["jawaban"] = jawaban
    row["keterangan"] = keterangan


def build_ai_calculation(report: MonthlyRiskReport):
    """Mulai dari struktur kalkulasi ERM, lalu terapkan asesmen AI terverifikasi."""
    base = kpmr.calculate_kpmr_for_report(report)
    indicators = copy.deepcopy(base.indicators)
    by_code = {row["kode"]: row for row in indicators}

    missing = [code for code in ("I1", "I2", "I3", "I4") if code not in by_code]
    if missing:
        raise RuntimeError(f"Indikator KPMR tidak lengkap: {missing}")

    set_indicator(
        by_code["I1"],
        hasil=Decimal("40"),
        skor=Decimal("12"),
        jawaban="c",
        keterangan=(
            "AI PROVISIONAL. Total Exposure Residual Juni "
            f"{fmt_money(RESIDUAL_EXPOSURE_14_RISK)} lebih tinggi dari Total Exposure "
            f"Target {fmt_money(TARGET_EXPOSURE_13_RISK)} => c / 40 / skor 12. "
            "Catatan material: target berasal dari baseline profil 13 risiko, sedangkan "
            "snapshot Juni telah menjadi 14 risiko; nilai I1 harus direviu ulang ketika "
            "target residual profil revisi 14 risiko/Kertas Kerja KPMR resmi tersedia."
        ),
    )

    set_indicator(
        by_code["I2"],
        hasil=Decimal("100"),
        skor=Decimal("20"),
        jawaban="a",
        keterangan=(
            "AI assessment berbasis pencapaian output yang jatuh tempo sampai Juni: "
            f"{int(DUE_OUTPUT_REALIZED)}/{int(DUE_OUTPUT_TARGET)} output terealisasi = 100% "
            "=> a / 100 / skor 20."
        ),
    )

    absorption = (
        TOTAL_ACTUAL_COST / TOTAL_BUDGET * Decimal("100")
        if TOTAL_BUDGET > 0
        else Decimal("0")
    )
    set_indicator(
        by_code["I3"],
        hasil=Decimal("80"),
        skor=Decimal("16"),
        jawaban="a",
        keterangan=(
            f"AI assessment biaya: total realisasi {fmt_money(TOTAL_ACTUAL_COST)} "
            f"dibanding total anggaran {fmt_money(TOTAL_BUDGET)} = {q(absorption)}%. "
            "Realisasi tidak melebihi anggaran agregat => a / 80 / skor 16."
        ),
    )

    set_indicator(
        by_code["I4"],
        hasil=Decimal("90"),
        skor=Decimal("27"),
        jawaban="a,a,a,a",
        keterangan=(
            "AI assessment I4: IDENTIFIKASI=a, KUANTIFIKASI=a, RENCANA=a, "
            "PRIORITISASI=a => rata-rata 90 / skor 27. "
            "Khusus I4.3/RENCANA TW II 2026 = a karena perubahan profil sampai dengan "
            "Juni 2026 masih diakomodasi oleh Sub Bidang Manajemen Risiko. Override ini "
            "tidak otomatis berlaku mulai Juli/TW III."
        ),
    )

    i4 = by_code["I4"]
    sub_rows = i4.get("subindikator") or []
    sub_by_code = {row.get("kode"): row for row in sub_rows}
    expected_sub_codes = ("IDENTIFIKASI", "KUANTIFIKASI", "RENCANA", "PRIORITISASI")
    missing_sub = [code for code in expected_sub_codes if code not in sub_by_code]
    if missing_sub:
        raise RuntimeError(f"Subindikator I4 tidak lengkap: {missing_sub}")

    sub_notes = {
        "IDENTIFIKASI": (
            "AI assessment: struktur 14 risiko pada snapshot Juni telah teridentifikasi "
            "dan dimonitor => a / 90."
        ),
        "KUANTIFIKASI": (
            "AI assessment: 14/14 risiko pada snapshot Juni memiliki basis penilaian "
            "untuk monitoring/kuantifikasi => a / 90."
        ),
        "RENCANA": (
            "AI assessment TW II 2026: perubahan/reassessment profil sampai dengan Juni "
            "masih diakomodasi oleh Sub Bidang Manajemen Risiko => I4.3 RENCANA = a / 90. "
            "Mulai Juli/TW III harus mengikuti kondisi aktual/asesmen baru."
        ),
        "PRIORITISASI": (
            "AI assessment: risiko hasil perubahan profil telah masuk struktur monitoring "
            "Juni dan tidak ada indikasi risiko material yang dibiarkan di luar proses "
            "prioritisasi => a / 90."
        ),
    }
    for code in expected_sub_codes:
        row = sub_by_code[code]
        row["hasil"] = Decimal("90.00")
        row["skor"] = Decimal("22.50")
        row["jawaban"] = "a"
        row["keterangan"] = sub_notes[code]

    total = q(sum(Decimal(row["skor"]) for row in indicators))
    if total != EXPECTED_TOTAL:
        raise RuntimeError(f"Total hasil konstruksi AI {total} != {EXPECTED_TOTAL}")

    rating = kpmr.rating_for_score(total)
    notes = [
        f"{AI_MARKER}.",
        (
            "Sumber analisis: Lampiran 1 Profil/Re-Assessment Risiko BID AGA dan "
            "Lampiran 2 Laporan Realisasi Risiko BID AGA posisi Juni 2026. "
            "Kertas Kerja KPMR resmi BID AGA belum tersedia."
        ),
        (
            "I1 PROVISIONAL: Total Exposure Target baseline 13 risiko = "
            f"{fmt_money(TARGET_EXPOSURE_13_RISK)}; Total Exposure Residual snapshot "
            f"Juni 14 risiko = {fmt_money(RESIDUAL_EXPOSURE_14_RISK)}; residual > target "
            "=> c / 40 / skor 12. Karena struktur 13 vs 14 tidak apple-to-apple, "
            "I1 wajib direviu saat target residual profil revisi/Kertas Kerja KPMR resmi tersedia."
        ),
        (
            f"I2 AI: target output jatuh tempo s.d. Juni = {int(DUE_OUTPUT_TARGET)}; "
            f"realisasi = {int(DUE_OUTPUT_REALIZED)} => 100% => a / skor 20."
        ),
        (
            f"I3 AI: anggaran = {fmt_money(TOTAL_BUDGET)}; realisasi = "
            f"{fmt_money(TOTAL_ACTUAL_COST)}; serapan = {q(absorption)}% "
            "=> a / skor 16."
        ),
        (
            "I4 AI: a,a,a,a => skor 27. I4.3/RENCANA=a untuk TW II karena perubahan "
            "profil sampai Juni masih diakomodasi. Mulai Juli/TW III tidak otomatis diwariskan."
        ),
        (
            f"Hasil AI sementara: I1=12, I2=20, I3=16, I4=27, TOTAL={total}, "
            f"RATING={rating}. Status disimpan sebagai DRAFT/AI PROVISIONAL, bukan asesmen resmi User."
        ),
    ]

    return replace(
        base,
        score_total=total,
        rating=rating,
        indicators=indicators,
        notes=notes,
    )


def print_result(report: MonthlyRiskReport, calc) -> None:
    print("=" * 96)
    print("KPMR BID AGA - AI ASSESSMENT TW II 2026 - V8")
    print("=" * 96)
    print(f"Report : {report.id} - {report}")
    print(f"Kode   : {report.kode}")
    print(f"Unit   : {report.reassessment.unit_bisnis}")
    print(f"Items  : {report.items.count()} (monitoring detail tetap dipertahankan)")
    print()

    for row in calc.indicators:
        print(
            f"{row['kode']}: hasil={q(row.get('hasil'))} | "
            f"skor={q(row.get('skor'))} | jawaban={row.get('jawaban') or '-'}"
        )
    print("-" * 96)
    print(f"TOTAL  : {q(calc.score_total)}")
    print(f"RATING : {calc.rating}")
    print()
    print("DASAR AI ASSESSMENT")
    print(
        f"I1: Target baseline 13 risiko = {fmt_money(TARGET_EXPOSURE_13_RISK)} | "
        f"Residual Juni 14 risiko = {fmt_money(RESIDUAL_EXPOSURE_14_RISK)} "
        "=> c / 40 / skor 12 [PROVISIONAL]"
    )
    print(
        f"I2: output jatuh tempo/realisasi = {int(DUE_OUTPUT_REALIZED)}/"
        f"{int(DUE_OUTPUT_TARGET)} => 100 / skor 20"
    )
    print(
        f"I3: anggaran {fmt_money(TOTAL_BUDGET)} | realisasi "
        f"{fmt_money(TOTAL_ACTUAL_COST)} => 80 / skor 16"
    )
    print("I4: a,a,a,a => 90 / skor 27 | I4.3/RENCANA=a untuk TW II/Juni")
    print()
    print(
        "PERINGATAN: I1 belum audit-grade karena membandingkan baseline 13 risiko "
        "dengan snapshot revisi 14 risiko."
    )


def validate(report: MonthlyRiskReport, calc) -> None:
    errors: list[str] = []

    if report.items.count() != EXPECTED_ITEMS:
        errors.append(
            f"Jumlah item {report.items.count()} != {EXPECTED_ITEMS}."
        )

    by_code = {row["kode"]: row for row in calc.indicators}
    for code, (exp_hasil, exp_skor, exp_answer) in EXPECTED.items():
        row = by_code.get(code)
        if row is None:
            errors.append(f"{code} tidak ditemukan.")
            continue
        if q(row.get("hasil")) != exp_hasil:
            errors.append(
                f"{code} hasil {q(row.get('hasil'))} != {exp_hasil}."
            )
        if q(row.get("skor")) != exp_skor:
            errors.append(
                f"{code} skor {q(row.get('skor'))} != {exp_skor}."
            )
        if (row.get("jawaban") or "") != exp_answer:
            errors.append(
                f"{code} jawaban {(row.get('jawaban') or '')!r} != {exp_answer!r}."
            )

    i4 = by_code.get("I4") or {}
    sub_answers = {
        row.get("kode"): row.get("jawaban")
        for row in (i4.get("subindikator") or [])
    }
    for code in ("IDENTIFIKASI", "KUANTIFIKASI", "RENCANA", "PRIORITISASI"):
        if sub_answers.get(code) != "a":
            errors.append(f"I4.{code} bukan a: {sub_answers.get(code)!r}")

    if q(calc.score_total) != EXPECTED_TOTAL:
        errors.append(f"Total {q(calc.score_total)} != {EXPECTED_TOTAL}.")

    expected_rating = kpmr.rating_for_score(EXPECTED_TOTAL)
    if calc.rating != expected_rating:
        errors.append(f"Rating {calc.rating!r} != {expected_rating!r}.")

    if errors:
        raise RuntimeError("VALIDASI KPMR AGA V8 GAGAL:\n- " + "\n- ".join(errors))


def backup_sqlite() -> Path | None:
    db_name = settings.DATABASES["default"].get("NAME")
    if not db_name:
        return None

    db_path = Path(str(db_name)).resolve()
    if (
        db_path.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}
        or not db_path.exists()
    ):
        return None

    backup_dir = ROOT / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"db_before_kpmr_aga_ai_v8_{stamp}.sqlite3"
    shutil.copy2(db_path, dest)
    return dest


def existing_period(calc):
    return KPMRPeriode.objects.filter(
        tahun=calc.year,
        triwulan=calc.quarter,
        unit_bisnis=calc.unit,
    ).first()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Finalizer AI KPMR BID AGA TW II 2026 - V8"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Simpan hasil AI sebagai KPMR draft. Tanpa flag ini hanya dry-run/read-only.",
    )
    args = parser.parse_args()

    report = find_report()
    calc = build_ai_calculation(report)
    print_result(report, calc)
    validate(report, calc)

    current = existing_period(calc)
    if current:
        print(
            f"\nKPMRPeriode saat ini: id={current.id}, status={current.status}, "
            f"skor={current.skor_total}, rating={current.rating}"
        )
    else:
        print("\nKPMRPeriode BID AGA TW II 2026 saat ini: BELUM ADA.")

    print(
        f"\nVALIDASI BERHASIL: AI KPMR BID AGA = {q(calc.score_total)} / {calc.rating}"
    )
    print("I4.3 RENCANA = a untuk TW II/Juni 2026.")

    if not args.apply:
        print("DRY RUN: tidak ada data KPMR yang diubah.")
        print(
            "CATATAN: jangan --apply sebelum output dan status PROVISIONAL I1 "
            "direviu/disetujui."
        )
        return

    backup = backup_sqlite()
    if backup:
        print("BACKUP DB:", backup)
    else:
        print(
            "PERINGATAN: backup SQLite otomatis tidak dibuat "
            "(DB bukan SQLite atau file tidak ditemukan)."
        )

    with transaction.atomic():
        period = kpmr.save_kpmr_calculation(calc)
        # AI assessment tetap draft sampai Kertas Kerja KPMR/asesmen User tersedia.
        period.status = "draft"
        note = (
            f"{AI_MARKER}. KPMR ini merupakan hasil analisis AI dari dua lampiran "
            "dan belum menggantikan Kertas Kerja KPMR/asesmen resmi User. "
            "I1 bersifat provisional karena baseline target 13 risiko dibanding snapshot "
            "Juni 14 risiko."
        )
        if note not in (period.catatan or ""):
            period.catatan = ((period.catatan or "") + "\n\n" + note).strip()
        period.save()

    print(
        f"TERSIMPAN DRAFT AI: KPMRPeriode id={period.id}, "
        f"skor={period.skor_total}, rating={period.rating}, status={period.status}"
    )
    print(
        "PENTING: ketika Kertas Kerja KPMR AGA resmi tersedia, lakukan rekonsiliasi "
        "dan ganti nilai AI provisional dengan asesmen resmi User."
    )


if __name__ == "__main__":
    main()
