"""Finalizer KPMR SEKPER/SETPER TW II 2026 - AI Assessment V9.

Sumber analisis:
1. Profil Risiko SETPER-2026 Update 060326.
2. Laporan Mitigasi Risiko Bidang Setper s.d. Juni 2026.

Karena Kertas Kerja KPMR resmi SEKPER belum tersedia, hasil disimpan sebagai
DRAFT / AI PROVISIONAL dan tidak boleh dianggap sebagai asesmen resmi User.

Hasil AI V9:
- I1 = a / 90 / skor 27 [PROVISIONAL]
  * 8 dari 8 risiko aktif SEKPER Juni memiliki data Q2 yang lengkap.
  * Target Q2 8 risiko lengkap      = 118,838,856,648.288
  * Residual Juni 8 risiko lengkap  = 116,755,406,618.720
  * Residual < Target => a.
  * Dua risiko K3L telah keluar dari scope SEKPER Juni dan tidak menjadi denominator KPMR Juni.
- I2 = d / 60 / skor 12
  * Output jatuh tempo s.d. Juni = 24
  * Output terealisasi           = 15
  * 15/24 = 62.50% => d.
- I3 = a / 80 / skor 16
  * Anggaran perlakuan = 15,521,000,000
  * Realisasi biaya    = 9,423,869,999
  * Serapan 60.72%, tidak melebihi anggaran => a.
- I4 = a,a,a,a / hasil 90 / skor 27
  * I4.1 Identifikasi = a
  * I4.2 Kuantifikasi = a (8/8 = 100% lengkap; ambang a >=95%)
  * I4.3 Rencana      = a (akomodasi perubahan profil s.d. Juni 2026)
  * I4.4 Prioritisasi = a

TOTAL = 82.00
RATING = mengikuti rating_for_score(82) pada aplikasi.

Dry-run:
    python monthly_report/scripts/finalize_sekper_kpmr_ai_v9.py

Apply draft AI:
    python monthly_report/scripts/finalize_sekper_kpmr_ai_v9.py --apply

Keamanan:
- Dry-run tidak mengubah database.
- --apply membuat backup SQLite otomatis.
- Script menolak overwrite bila menemukan jawaban KPMR yang sudah terisi dan
  bukan hasil AI PROVISIONAL script ini.
- Tidak mengubah MonthlyRiskReport/ReAssessmentItem.
"""
from __future__ import annotations

import argparse
import copy
import os
import re
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
from risk.models import KPMRIndikatorResmi, KPMRPeriode
from risk.services import kpmr_automation as kpmr


YEAR = 2026
MONTH = 6
QUARTER = 2
EXPECTED_RISK_ITEMS = 8

# Data hasil analisis Lampiran 1 + Lampiran 2.
TARGET_EXPOSURE_COMPLETE_8 = Decimal("118838856648.288")
RESIDUAL_EXPOSURE_COMPLETE_8 = Decimal("116755406618.720")

DUE_OUTPUT_TARGET = Decimal("24")
DUE_OUTPUT_REALIZED = Decimal("15")
OUTPUT_COMPLETION = DUE_OUTPUT_REALIZED / DUE_OUTPUT_TARGET * Decimal("100")

TOTAL_BUDGET = Decimal("15521000000")
TOTAL_ACTUAL_COST = Decimal("9423869999")

QUANTIFIED_RISKS = Decimal("8")
TOTAL_RISKS = Decimal("8")
QUANTIFICATION_RATIO = QUANTIFIED_RISKS / TOTAL_RISKS * Decimal("100")

EXPECTED_TOTAL = Decimal("82.00")
EXPECTED = {
    "I1": (Decimal("90.00"), Decimal("27.00"), "a"),
    "I2": (Decimal("60.00"), Decimal("12.00"), "d"),
    "I3": (Decimal("80.00"), Decimal("16.00"), "a"),
    "I4": (Decimal("90.00"), Decimal("27.00"), "a,a,a,a"),
}
EXPECTED_SUBS = {
    "IDENTIFIKASI": ("a", Decimal("90.00"), Decimal("22.50")),
    "KUANTIFIKASI": ("a", Decimal("90.00"), Decimal("22.50")),
    "RENCANA": ("a", Decimal("90.00"), Decimal("22.50")),
    "PRIORITISASI": ("a", Decimal("90.00"), Decimal("22.50")),
}

AI_MARKER = "AI PROVISIONAL KPMR SEKPER TW II 2026"


def q(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value).quantize(Decimal("0.01"))


def fmt_money(value: Decimal) -> str:
    return f"{value:,.0f}"


def norm(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def is_sekper_text(value: object) -> bool:
    text = norm(value)
    return any(token in text for token in ("SEKPER", "SETPER", "SEKRETARIATPERUSAHAAN"))


def find_report() -> MonthlyRiskReport:
    qs = (
        MonthlyRiskReport.objects.select_related(
            "reassessment",
            "reassessment__unit_bisnis",
            "periode",
        )
        .filter(
            reassessment__tahun=YEAR,
            periode__tanggal_mulai__year=YEAR,
            periode__tanggal_mulai__month=MONTH,
        )
        .order_by("id")
    )

    candidates = []
    for report in qs:
        unit_name = getattr(report.reassessment.unit_bisnis, "name", "")
        searchable = " | ".join(
            [
                str(unit_name or ""),
                str(getattr(report, "kode", "") or ""),
                str(report),
            ]
        )
        if is_sekper_text(searchable):
            candidates.append(report)

    if not candidates:
        raise RuntimeError(
            "Laporan Juni 2026 untuk SEKPER/SETPER tidak ditemukan. "
            "Cari unit/kode laporan yang mengandung SEKPER, SETPER, atau Sekretariat Perusahaan."
        )

    exact_item_candidates = [
        report for report in candidates if report.items.count() == EXPECTED_RISK_ITEMS
    ]
    if len(exact_item_candidates) == 1:
        return exact_item_candidates[0]

    if len(candidates) == 1:
        report = candidates[0]
        if report.items.count() != EXPECTED_RISK_ITEMS:
            raise RuntimeError(
                f"Kandidat laporan ditemukan tetapi items={report.items.count()}, "
                f"diharapkan {EXPECTED_RISK_ITEMS}. Finalisasi dihentikan untuk mencegah salah unit."
            )
        return report

    detail = ", ".join(
        f"id={r.id}/kode={getattr(r, 'kode', '')!r}/unit={r.reassessment.unit_bisnis}/"
        f"items={r.items.count()}/nama={str(r)!r}"
        for r in candidates
    )
    raise RuntimeError(
        "Ada lebih dari satu kandidat laporan SEKPER/SETPER Juni 2026. "
        f"Kandidat: {detail}"
    )


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
            "AI PROVISIONAL. Perbandingan dilakukan pada 8 risiko aktif SEKPER Juni yang "
            "memiliki Target Residual Q2 dan Realisasi Residual Juni lengkap. "
            f"Total Target Q2 8 risiko = {fmt_money(TARGET_EXPOSURE_COMPLETE_8)}; "
            f"Total Residual Juni 8 risiko = {fmt_money(RESIDUAL_EXPOSURE_COMPLETE_8)}; "
            "Residual < Target => a / 90 / skor 27. "
            "Delapan risiko aktif Juni memiliki pasangan kuantifikasi Q2 yang lengkap. "
            "Hasil tetap bersifat provisional sampai direkonsiliasi dengan Kertas Kerja KPMR resmi."
        ),
    )

    set_indicator(
        by_code["I2"],
        hasil=Decimal("60"),
        skor=Decimal("12"),
        jawaban="d",
        keterangan=(
            "AI assessment berbasis output perlakuan yang jatuh tempo sampai Juni. "
            f"Target output jatuh tempo = {int(DUE_OUTPUT_TARGET)}; "
            f"output terealisasi = {int(DUE_OUTPUT_REALIZED)}; "
            f"pencapaian = {q(OUTPUT_COMPLETION)}%. "
            "Rentang 60-69% => jawaban d / hasil 60 / skor 12."
        ),
    )

    absorption = TOTAL_ACTUAL_COST / TOTAL_BUDGET * Decimal("100")
    set_indicator(
        by_code["I3"],
        hasil=Decimal("80"),
        skor=Decimal("16"),
        jawaban="a",
        keterangan=(
            f"AI assessment biaya: total realisasi {fmt_money(TOTAL_ACTUAL_COST)} "
            f"dibanding total anggaran {fmt_money(TOTAL_BUDGET)} = {q(absorption)}%. "
            "Realisasi tidak melebihi anggaran agregat dan tidak ditemukan realisasi biaya "
            "positif tanpa baseline anggaran pada data yang dianalisis => a / 80 / skor 16."
        ),
    )

    set_indicator(
        by_code["I4"],
        hasil=Decimal("90"),
        skor=Decimal("27"),
        jawaban="a,a,a,a",
        keterangan=(
            "AI assessment I4: IDENTIFIKASI=a, KUANTIFIKASI=a, RENCANA=a, "
            "PRIORITISASI=a => (90+90+90+90)/4 = 90; skor 90 x 30% = 27."
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
            "AI assessment: 8 risiko aktif SEKPER telah masuk struktur monitoring Juni "
            "Juni dan tidak ditemukan indikasi risiko material baru yang belum teridentifikasi "
            "dalam dokumen yang dianalisis => a / 90."
        ),
        "KUANTIFIKASI": (
            f"AI assessment: kuantifikasi Q2 lengkap pada 8 dari 8 risiko aktif Juni = "
            f"{q(QUANTIFICATION_RATIO)}%. Ambang a adalah >=95%; "
            "karena 100% >=95% maka KUANTIFIKASI=a / 90."
        ),
        "RENCANA": (
            "AI assessment TW II 2026: perubahan/reassessment profil sampai dengan Juni "
            "masih diakomodasi oleh Sub Bidang Manajemen Risiko => I4.3 RENCANA=a / 90. "
            "Mulai Juli/TW III tidak otomatis diwariskan dan harus mengikuti kondisi aktual."
        ),
        "PRIORITISASI": (
            "AI assessment: risiko SETPER/SEKPER telah terintegrasi dalam profil dan monitoring Juni; "
            "tidak ditemukan indikasi risiko material yang tidak masuk prioritisasi => a / 90."
        ),
    }

    for code, (answer, hasil, skor) in EXPECTED_SUBS.items():
        row = sub_by_code[code]
        row["hasil"] = hasil
        row["skor"] = skor
        row["jawaban"] = answer
        row["keterangan"] = sub_notes[code]

    total = q(sum(Decimal(row["skor"]) for row in indicators))
    if total != EXPECTED_TOTAL:
        raise RuntimeError(f"Total hasil konstruksi AI {total} != {EXPECTED_TOTAL}")

    rating = kpmr.rating_for_score(total)

    notes = [
        f"{AI_MARKER}.",
        (
            "Sumber analisis: Profil Risiko SETPER-2026 Update 060326 dan Laporan Mitigasi "
            "Risiko Bidang Setper s.d. Juni 2026. Kertas Kerja KPMR resmi SEKPER belum tersedia."
        ),
        (
            "I1 PROVISIONAL: 8/8 risiko aktif Juni memiliki pasangan Target Residual Q2 dan Realisasi "
            f"Residual Juni lengkap. Target 8 risiko = {fmt_money(TARGET_EXPOSURE_COMPLETE_8)}; "
            f"Residual 8 risiko = {fmt_money(RESIDUAL_EXPOSURE_COMPLETE_8)}; Residual < Target "
            "=> a / skor 27. Dua risiko K3L di luar scope SEKPER Juni tidak dihitung sebagai denominator."
        ),
        (
            f"I2 AI: output jatuh tempo s.d. Juni = {int(DUE_OUTPUT_TARGET)}; "
            f"output terealisasi = {int(DUE_OUTPUT_REALIZED)}; "
            f"pencapaian = {q(OUTPUT_COMPLETION)}% => d / skor 12."
        ),
        (
            f"I3 AI: anggaran = {fmt_money(TOTAL_BUDGET)}; realisasi = "
            f"{fmt_money(TOTAL_ACTUAL_COST)}; serapan = {q(absorption)}% "
            "=> a / skor 16."
        ),
        (
            "I4 AI: IDENTIFIKASI=a; KUANTIFIKASI=a; RENCANA=a; PRIORITISASI=a "
            "=> hasil 90 / skor 27. I4.3 RENCANA=a hanya untuk TW II/Juni sesuai kebijakan "
            "akomodasi perubahan profil sampai Juni; tidak otomatis berlaku mulai Juli."
        ),
        (
            f"Hasil AI sementara: I1=27, I2=12, I3=16, I4=27, TOTAL={total}, "
            f"RATING={rating}. Status DRAFT/AI PROVISIONAL, bukan asesmen resmi User."
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
    print("=" * 100)
    print("KPMR SEKPER/SETPER - AI ASSESSMENT TW II 2026 - V9")
    print("=" * 100)
    print(f"Report : {report.id} - {report}")
    print(f"Kode   : {getattr(report, 'kode', '')}")
    print(f"Unit   : {report.reassessment.unit_bisnis}")
    print(f"Items  : {report.items.count()} (risiko monitoring tetap dipertahankan)")
    print()

    for row in calc.indicators:
        print(
            f"{row['kode']}: hasil={q(row.get('hasil'))} | "
            f"skor={q(row.get('skor'))} | jawaban={row.get('jawaban') or '-'}"
        )

    print("-" * 100)
    print(f"TOTAL  : {q(calc.score_total)}")
    print(f"RATING : {calc.rating}")
    print()
    print("DASAR AI ASSESSMENT")
    print(
        f"I1: 8/8 risiko aktif Juni lengkap | Target={fmt_money(TARGET_EXPOSURE_COMPLETE_8)} | "
        f"Residual={fmt_money(RESIDUAL_EXPOSURE_COMPLETE_8)} => a / 90 / 27 [PROVISIONAL]"
    )
    print(
        f"I2: output jatuh tempo/realisasi = {int(DUE_OUTPUT_REALIZED)}/"
        f"{int(DUE_OUTPUT_TARGET)} = {q(OUTPUT_COMPLETION)}% => d / 60 / 12"
    )
    print(
        f"I3: anggaran={fmt_money(TOTAL_BUDGET)} | realisasi={fmt_money(TOTAL_ACTUAL_COST)} "
        f"=> a / 80 / 16"
    )
    print(
        f"I4: a,a,a,a => 90 / 27 | Kuantifikasi lengkap "
        f"{int(QUANTIFIED_RISKS)}/{int(TOTAL_RISKS)} = {q(QUANTIFICATION_RATIO)}%"
    )
    print()
    print(
        "PERINGATAN: I1 masih PROVISIONAL sampai direkonsiliasi dengan Kertas Kerja KPMR resmi."
    )


def validate(report: MonthlyRiskReport, calc) -> None:
    errors: list[str] = []

    if report.items.count() != EXPECTED_RISK_ITEMS:
        errors.append(
            f"Jumlah item report {report.items.count()} != {EXPECTED_RISK_ITEMS}."
        )

    by_code = {row["kode"]: row for row in calc.indicators}
    for code, (exp_hasil, exp_skor, exp_answer) in EXPECTED.items():
        row = by_code.get(code)
        if row is None:
            errors.append(f"{code} tidak ditemukan.")
            continue
        if q(row.get("hasil")) != exp_hasil:
            errors.append(f"{code} hasil {q(row.get('hasil'))} != {exp_hasil}.")
        if q(row.get("skor")) != exp_skor:
            errors.append(f"{code} skor {q(row.get('skor'))} != {exp_skor}.")
        if (row.get("jawaban") or "") != exp_answer:
            errors.append(
                f"{code} jawaban {(row.get('jawaban') or '')!r} != {exp_answer!r}."
            )

    i4 = by_code.get("I4") or {}
    sub_answers = {
        row.get("kode"): row
        for row in (i4.get("subindikator") or [])
    }
    for code, (exp_answer, exp_hasil, exp_skor) in EXPECTED_SUBS.items():
        row = sub_answers.get(code)
        if row is None:
            errors.append(f"I4.{code} tidak ditemukan.")
            continue
        if row.get("jawaban") != exp_answer:
            errors.append(
                f"I4.{code} jawaban {row.get('jawaban')!r} != {exp_answer!r}."
            )
        if q(row.get("hasil")) != exp_hasil:
            errors.append(
                f"I4.{code} hasil {q(row.get('hasil'))} != {exp_hasil}."
            )
        if q(row.get("skor")) != exp_skor:
            errors.append(
                f"I4.{code} skor {q(row.get('skor'))} != {exp_skor}."
            )

    if q(calc.score_total) != EXPECTED_TOTAL:
        errors.append(f"Total {q(calc.score_total)} != {EXPECTED_TOTAL}.")

    expected_rating = kpmr.rating_for_score(EXPECTED_TOTAL)
    if calc.rating != expected_rating:
        errors.append(
            f"Rating {calc.rating!r} != rating_for_score({EXPECTED_TOTAL})={expected_rating!r}."
        )

    if errors:
        raise RuntimeError(
            "VALIDASI KPMR SEKPER V9 GAGAL:\n- " + "\n- ".join(errors)
        )


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
    dest = backup_dir / f"db_before_kpmr_sekper_ai_v9_{stamp}.sqlite3"
    shutil.copy2(db_path, dest)
    return dest


def existing_period(calc):
    return KPMRPeriode.objects.filter(
        tahun=calc.year,
        triwulan=calc.quarter,
        unit_bisnis=calc.unit,
    ).first()


def ensure_safe_to_apply(period: KPMRPeriode | None) -> None:
    if period is None:
        return

    existing_answers = list(
        KPMRIndikatorResmi.objects.filter(periode=period)
        .exclude(jawaban__isnull=True)
        .exclude(jawaban="")
        .values_list("kode", "jawaban")
    )

    if existing_answers and AI_MARKER not in (period.catatan or ""):
        raise RuntimeError(
            "APPLY DIBATALKAN: sudah ada jawaban KPMR tersimpan untuk periode ini: "
            f"{existing_answers}. Audit dulu apakah itu asesmen resmi User. "
            "Script tidak akan menimpa asesmen yang sudah ada."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Finalizer AI KPMR SEKPER/SETPER TW II 2026 - V9"
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
        print("\nKPMRPeriode SEKPER TW II 2026 saat ini: BELUM ADA.")

    print(
        f"\nVALIDASI BERHASIL: AI KPMR SEKPER = {q(calc.score_total)} / {calc.rating}"
    )
    print("I4.3 RENCANA = a untuk TW II/Juni 2026.")
    print("I4.2 KUANTIFIKASI = a karena 8/8 risiko aktif Juni memiliki data lengkap.")

    if not args.apply:
        print("DRY RUN: tidak ada data KPMR yang diubah.")
        print(
            "CATATAN: jangan --apply sebelum Report/Unit/Items dan status KPMR lama "
            "direviu dari output dry-run."
        )
        return

    ensure_safe_to_apply(current)

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
        period.status = "draft"
        note = (
            f"{AI_MARKER}. KPMR ini merupakan hasil analisis AI dari Profil Risiko "
            "SETPER-2026 Update 060326 dan Laporan Mitigasi Risiko Bidang Setper s.d. Juni 2026. "
            "Belum menggantikan Kertas Kerja KPMR/asesmen resmi User. "
            "I1 bersifat provisional sampai direkonsiliasi dengan Kertas Kerja KPMR resmi."
        )
        if note not in (period.catatan or ""):
            period.catatan = ((period.catatan or "") + "\n\n" + note).strip()
        period.save()

    print(
        f"TERSIMPAN DRAFT AI: KPMRPeriode id={period.id}, "
        f"skor={period.skor_total}, rating={period.rating}, status={period.status}"
    )
    print(
        "PENTING: ketika Kertas Kerja KPMR SEKPER resmi tersedia, rekonsiliasi hasil AI "
        "provisional dengan asesmen resmi User."
    )


if __name__ == "__main__":
    main()
