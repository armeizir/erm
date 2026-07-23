"""Finalizer Rekonsiliasi KPMR BID AGA TW II 2026 - V9.

Tujuan
------
Merekonsiliasi KPMR BID AGA TW II 2026 berdasarkan Kertas Kerja KPMR resmi
BID AGA TW II 2026 dan struktur kalkulasi KPMR pada ERM.

PENTING
-------
Dasar resmi I1:
- Total Exposure Target = 728,842,600,797
- Total Exposure Residual = 715,494,889,511.99
- Residual lebih rendah dari target => a / 90 / skor 27

Hasil rekonsiliasi:
I1 = a -> 90 x 30% = 27
I2 = a -> 100 x 20% = 20
I3 = a -> 80 x 20% = 16
I4 = a,a,a,a -> 90 x 30% = 27
TOTAL = 90
RATING = SATISFACTORY
I4.3/RENCANA = a untuk TW II/Juni 2026 karena perubahan profil s.d. Juni
masih diakomodasi oleh Sub Bidang Manajemen Risiko.

Dry run:
    python monthly_report/scripts/finalize_aga_kpmr_ai_v9.py

Apply/save draft:
    python monthly_report/scripts/finalize_aga_kpmr_ai_v9.py --apply

Script tidak mengubah MonthlyRiskReport/ReAssessmentItem. Saat --apply, script:
- membuat backup SQLite otomatis bila DB SQLite,
- menyimpan KPMRPeriode + indikator/subindikator melalui save_kpmr_calculation(),
- mempertahankan status KPMR sebagai "draft",
- mempertahankan marker audit agar overwrite hanya menyasar KPMRPeriode ID 1
  yang dikenali oleh finalizer.
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
TARGET_EXPOSURE_OFFICIAL = Decimal("728842600797")
RESIDUAL_EXPOSURE_OFFICIAL = Decimal("715494889511.99")
TOTAL_BUDGET = Decimal("10649771685")
TOTAL_ACTUAL_COST = Decimal("787636100")
DUE_OUTPUT_TARGET = Decimal("10")
DUE_OUTPUT_REALIZED = Decimal("10")

EXPECTED_TOTAL = Decimal("90.00")
EXPECTED = {
    "I1": (Decimal("90.00"), Decimal("27.00"), "a"),
    "I2": (Decimal("100.00"), Decimal("20.00"), "a"),
    "I3": (Decimal("80.00"), Decimal("16.00"), "a"),
    "I4": (Decimal("90.00"), Decimal("27.00"), "a,a,a,a"),
}

LEGACY_AI_MARKER = "AI PROVISIONAL KPMR BID AGA TW II 2026"
AI_MARKER = "KPMR RECONCILED BID AGA TW II 2026"
AI_MARKERS = (AI_MARKER, LEGACY_AI_MARKER)


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


def build_reconciled_calculation(report: MonthlyRiskReport):
    """Terapkan hasil Kertas Kerja resmi pada struktur kalkulasi ERM."""
    base = kpmr.calculate_kpmr_for_report(report)
    indicators = copy.deepcopy(base.indicators)
    by_code = {row["kode"]: row for row in indicators}

    missing = [code for code in ("I1", "I2", "I3", "I4") if code not in by_code]
    if missing:
        raise RuntimeError(f"Indikator KPMR tidak lengkap: {missing}")

    set_indicator(
        by_code["I1"],
        hasil=Decimal("90"),
        skor=Decimal("27"),
        jawaban="a",
        keterangan=(
            "Rekonsiliasi berdasarkan Kertas Kerja KPMR resmi BID AGA TW II 2026. "
            f"Total Exposure Target = {fmt_money(TARGET_EXPOSURE_OFFICIAL)}; "
            f"Total Exposure Residual = {fmt_money(RESIDUAL_EXPOSURE_OFFICIAL)}. "
            "Residual lebih rendah dari target => a / 90 / skor 27."
        ),
    )

    set_indicator(
        by_code["I2"],
        hasil=Decimal("100"),
        skor=Decimal("20"),
        jawaban="a",
        keterangan=(
            "Kertas Kerja resmi: pencapaian output yang jatuh tempo sampai Juni "
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
            f"Kertas Kerja resmi: total realisasi {fmt_money(TOTAL_ACTUAL_COST)} "
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
            "Kertas Kerja resmi I4: IDENTIFIKASI=a, KUANTIFIKASI=a, RENCANA=a, "
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
            "Kertas Kerja resmi: seluruh risiko posisi Juni telah teridentifikasi "
            "dan dimonitor => a / 90."
        ),
        "KUANTIFIKASI": (
            "Kertas Kerja resmi: seluruh risiko posisi Juni memiliki basis penilaian "
            "untuk monitoring/kuantifikasi => a / 90."
        ),
        "RENCANA": (
            "Kertas Kerja resmi TW II 2026: perubahan/reassessment profil sampai dengan Juni "
            "masih diakomodasi oleh Sub Bidang Manajemen Risiko => I4.3 RENCANA = a / 90. "
            "Mulai Juli/TW III harus mengikuti kondisi aktual/asesmen baru."
        ),
        "PRIORITISASI": (
            "Kertas Kerja resmi: risiko hasil perubahan profil telah masuk struktur monitoring "
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
        raise RuntimeError(f"Total hasil rekonsiliasi {total} != {EXPECTED_TOTAL}")

    rating = kpmr.rating_for_score(total)
    notes = [
        f"{AI_MARKER}.",
        (
            "Dasar rekonsiliasi: Kertas Kerja KPMR resmi BID AGA TW II 2026."
        ),
        (
            "I1 REKONSILIASI: Total Exposure Target resmi = "
            f"{fmt_money(TARGET_EXPOSURE_OFFICIAL)}; Total Exposure Residual resmi "
            f"{fmt_money(RESIDUAL_EXPOSURE_OFFICIAL)}; residual lebih rendah dari target "
            "=> a / 90 / skor 27. Dasar mengacu Kertas Kerja KPMR resmi BID AGA TW II 2026."
        ),
        (
            f"I2: target output jatuh tempo s.d. Juni = {int(DUE_OUTPUT_TARGET)}; "
            f"realisasi = {int(DUE_OUTPUT_REALIZED)} => 100% => a / skor 20."
        ),
        (
            f"I3: anggaran = {fmt_money(TOTAL_BUDGET)}; realisasi = "
            f"{fmt_money(TOTAL_ACTUAL_COST)}; serapan = {q(absorption)}% "
            "=> a / skor 16."
        ),
        (
            "I4: a,a,a,a => skor 27. I4.3/RENCANA=a untuk TW II karena perubahan "
            "profil sampai Juni masih diakomodasi. Mulai Juli/TW III tidak otomatis diwariskan."
        ),
        (
            f"Hasil rekonsiliasi: I1=27, I2=20, I3=16, I4=27, TOTAL={total}, "
            f"RATING={rating}. Status draft untuk verifikasi dan approval."
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
    print("Finalizer Rekonsiliasi KPMR BID AGA TW II 2026 - V9")
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
    print("DASAR KERTAS KERJA KPMR RESMI")
    print(
        f"I1: Target Exposure resmi = {fmt_money(TARGET_EXPOSURE_OFFICIAL)} | "
        f"Residual Exposure resmi = {fmt_money(RESIDUAL_EXPOSURE_OFFICIAL)} "
        "=> a / 90 / skor 27 [KERTAS KERJA RESMI]"
    )
    print(
        f"I2: output jatuh tempo/realisasi = {int(DUE_OUTPUT_REALIZED)}/"
        f"{int(DUE_OUTPUT_TARGET)} => a / 100 / skor 20"
    )
    print(
        f"I3: anggaran {fmt_money(TOTAL_BUDGET)} | realisasi "
        f"{fmt_money(TOTAL_ACTUAL_COST)} => a / 80 / skor 16"
    )
    print("I4: a,a,a,a => 90 / skor 27 | I4.3/RENCANA=a untuk TW II/Juni")
    print("STATUS: draft untuk verifikasi dan approval.")


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
        raise RuntimeError("VALIDASI REKONSILIASI KPMR AGA V9 GAGAL:\n- " + "\n- ".join(errors))


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
    dest = backup_dir / f"db_before_kpmr_aga_reconciled_v9_{stamp}.sqlite3"
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
        description="Finalizer Rekonsiliasi KPMR BID AGA TW II 2026 - V9"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Simpan hasil rekonsiliasi sebagai KPMR draft. "
            "Tanpa flag ini hanya dry-run/read-only."
        ),
    )
    args = parser.parse_args()

    report = find_report()
    calc = build_reconciled_calculation(report)
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
        f"\nVALIDASI BERHASIL: KPMR BID AGA = {q(calc.score_total)} / {calc.rating}"
    )
    print("I4.3 RENCANA = a untuk TW II/Juni 2026.")

    if not args.apply:
        print("DRY RUN: tidak ada data KPMR yang diubah.")
        print(
            "CATATAN: --apply hanya boleh dilakukan jika KPMR ID 1 masih merupakan "
            "hasil finalizer yang memiliki marker audit dikenali."
        )
        return

    # Safety guard: hanya memperbarui KPMR AGA TW II hasil finalizer yang
    # memiliki marker audit dikenali, bukan asesmen manual pengguna.
    if current is None:
        raise RuntimeError(
            "APPLY DIBATALKAN: KPMRPeriode BID AGA TW II 2026 tidak ditemukan."
        )

    if current.id != 1:
        raise RuntimeError(
            f"APPLY DIBATALKAN: target yang ditemukan id={current.id}; "
            "target yang diizinkan hanya KPMRPeriode id=1."
        )

    existing_note = current.catatan or ""

    if not any(marker in existing_note for marker in AI_MARKERS):
        raise RuntimeError(
            "APPLY DIBATALKAN: KPMR ID 1 tidak memiliki marker "
            "finalizer yang dikenali. Data mungkin sudah diubah secara manual."
        )

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
        # Tetap draft untuk verifikasi dan approval sesuai workflow.
        period.status = "draft"
        note = (
            f"{AI_MARKER}. Hasil telah direkonsiliasi dengan Kertas Kerja KPMR "
            "resmi BID AGA TW II 2026. "
            f"I1 menggunakan Total Exposure Target "
            f"{fmt_money(TARGET_EXPOSURE_OFFICIAL)} dan Total Exposure Residual "
            f"{fmt_money(RESIDUAL_EXPOSURE_OFFICIAL)} "
            "=> a / 90 / skor 27. "
            "Total KPMR hasil rekonsiliasi = 90 / SATISFACTORY."
        )
        if note not in (period.catatan or ""):
            period.catatan = ((period.catatan or "") + "\n\n" + note).strip()
        period.save()

    print(
        f"TERSIMPAN DRAFT: KPMRPeriode id={period.id}, "
        f"skor={period.skor_total}, rating={period.rating}, status={period.status}"
    )
    print(
        "PENTING: hasil telah direkonsiliasi dengan Kertas Kerja KPMR AGA resmi. "
        "Pertahankan audit trail dan lakukan approval sesuai workflow yang berlaku."
    )


if __name__ == "__main__":
    main()
