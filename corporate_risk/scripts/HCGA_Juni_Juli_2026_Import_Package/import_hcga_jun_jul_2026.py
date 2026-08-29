#!/usr/bin/env python3
"""
IMPORT LAPORAN RISIKO BID HCGA — JUNI & JULI 2026

Prinsip:
- Default DRY RUN; database tidak berubah tanpa --apply.
- Sumber Juni/Juli diverifikasi SHA256.
- Menggunakan master/profile HCGA existing (Profile ID=4 / Unit BID HCGA ID=12).
- Mapping berbasis peristiwa risiko, mengikuti importer HCGA Feb-Mei V2.
- 15 logical RiskEvent per bulan, termasuk tiga cause/KRI organisasi sebagai
  RiskEvent terpisah (org_a / org_b / org_c).
- Juni memakai residual Q2.
- Juli memakai residual Q3.
- KRI aktual hanya diambil dari kolom bulan yang bersangkutan:
    Juni  = AO/AP
    Juli  = AQ/AR
  Jika kosong pada sumber, tidak mengambil/fallback nilai Mei dari AM/AN.
- Tidak menghapus report/item/profile/risk event.
- Existing report hanya boleh draft/revision.
- Jika report Juni/Juli belum ada, dibuat sebagai draft dengan prepared_by
  mengikuti report HCGA existing terbaru.
- APPLY membuat backup SQLite dan memproses bulan yang dipilih dalam satu
  transaction.atomic().
- Setelah APPLY dilakukan verify terhadap jumlah item dan field utama.

Kebutuhan:
- monthly_report/scripts/import_hcga_feb_may_2026_v2.py harus tersedia.
  Script Juni/Juli ini memakai parser/mapping matang dari importer tersebut
  dan hanya memperluas periode serta kolom Q2/Q3/KRI bulan terkait.

Penggunaan dari root project:
  python monthly_report/scripts/import_hcga_jun_jul_2026.py

Apply setelah dry-run direview:
  python monthly_report/scripts/import_hcga_jun_jul_2026.py --apply

Opsional satu bulan:
  python monthly_report/scripts/import_hcga_jun_jul_2026.py --month 6
  python monthly_report/scripts/import_hcga_jun_jul_2026.py --month 7 --apply
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.prod")

import django
django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction

from monthly_report.models import MonthlyRiskReport


YEAR = 2026
PROFILE_ID = 4
UNIT_ID = 12
UNIT_NAME = "BID HCGA"
ALLOWED_STATUSES = {"draft", "revision"}

SOURCE_DIR = Path(
    os.getenv(
        "HCGA_JUN_JUL_SOURCE_DIR",
        "/home/adminsvr/erm/tmp/hcga_jun_jul_2026",
    )
).expanduser().resolve()

SOURCE_FILES = {
    6: (
        SOURCE_DIR / 'Laporan Realisasi Manajemen Risiko Juni HCGA.xlsx',
        '53a8a827581b2049dceb4a35e79aa163993daa369530b746154f63e505ea0140',
    ),
    7: (
        SOURCE_DIR / 'Laporan Realisasi Manajemen Risiko Juli HCGA.xlsx',
        'b5589fdd4f6e25ffb64cc8a7bd1726318becf3150be3d56e2d05657dd4ad78b0',
    ),
}

MONTH_NAMES = {6: "Juni", 7: "Juli"}
MONTH_KEYS = [
    "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8",
    "rencana", "wellness", "provider", "yanhc",
    "org_a", "org_b", "org_c",
]

BASE_SCRIPT = ROOT / "monthly_report" / "scripts" / "import_hcga_feb_may_2026_v2.py"


def stop(message):
    raise RuntimeError(f"STOP: {message}")


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_base():
    if not BASE_SCRIPT.exists():
        stop(
            "Importer basis tidak ditemukan: "
            f"{BASE_SCRIPT}. Pastikan import_hcga_feb_may_2026_v2.py tersedia."
        )
    spec = importlib.util.spec_from_file_location("hcga_feb_may_base", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        stop(f"Gagal membuat loader untuk {BASE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load_base()

# Extend konfigurasi importer Feb-Mei ke Juni/Juli.
base.MONTH_NAMES.update(MONTH_NAMES)
base.MONTH_KEYS[6] = list(MONTH_KEYS)
base.MONTH_KEYS[7] = list(MONTH_KEYS)

# Juni = residual Q2; Juli = residual Q3.
base.RESIDUAL_COLS[6] = dict(
    impact="P",
    impact_scale="T",
    probability="AB",
    probability_scale="AF",
    exposure="AN",
    score="AR",
    level="AZ",
)
base.RESIDUAL_COLS[7] = dict(
    impact="Q",
    impact_scale="U",
    probability="AC",
    probability_scale="AG",
    exposure="AO",
    score="AS",
    level="BA",
)
base.PROGRESS_COL[6] = "AE"  # progress Q2
base.PROGRESS_COL[7] = "AF"  # progress Q3
base.TIMELINE_COL[6] = "U"   # Juni
base.TIMELINE_COL[7] = "V"   # Juli


# Base parser Feb-Mei membaca KRI bulan aktif dari AM/AN.
# Untuk Juni/Juli kita alihkan AM/AN secara IN-MEMORY ke kolom bulan sebenarnya.
# Workbook sumber tidak dimodifikasi.
ORIGINAL_XLSX_READER = base.XlsxReader
CURRENT_PARSE_MONTH = None
KRI_MONTH_COLS = {
    6: ("AO", "AP"),
    7: ("AQ", "AR"),
}


class MonthlyKRIXlsxReader(ORIGINAL_XLSX_READER):
    def sheet_cells(self, name):
        cells = super().sheet_cells(name)
        if name == "III.B" and CURRENT_PARSE_MONTH in KRI_MONTH_COLS:
            status_col, score_col = KRI_MONTH_COLS[CURRENT_PARSE_MONTH]
            # Alias hanya untuk parser; sumber asli tetap tidak berubah.
            for row in range(1, 200):
                cells[f"AM{row}"] = cells.get(f"{status_col}{row}")
                cells[f"AN{row}"] = cells.get(f"{score_col}{row}")
        return cells


base.XlsxReader = MonthlyKRIXlsxReader


def load_sources(months):
    sources = {}
    for month in months:
        path, expected_sha = SOURCE_FILES[month]
        if not path.exists():
            stop(f"File sumber {MONTH_NAMES[month]} tidak ditemukan: {path}")
        actual_sha = sha256(path)
        if actual_sha != expected_sha:
            stop(
                f"SHA256 sumber {MONTH_NAMES[month]} berubah. "
                f"expected={expected_sha}, actual={actual_sha}"
            )
        data = path.read_bytes()

        global CURRENT_PARSE_MONTH
        CURRENT_PARSE_MONTH = month
        try:
            source = base.parse_month(data, month)
        finally:
            CURRENT_PARSE_MONTH = None

        if len(source["keys"]) != 15:
            stop(
                f"{MONTH_NAMES[month]} menghasilkan {len(source['keys'])} "
                "logical risk; expected 15."
            )
        if set(source["keys"]) != set(MONTH_KEYS):
            stop(
                f"Mapping key {MONTH_NAMES[month]} berubah: "
                f"{source['keys']}"
            )

        sources[month] = source
        print(
            f"{MONTH_NAMES[month]} source OK | SHA256={actual_sha} "
            f"| logical risk={len(source['keys'])}"
        )

        # Audit KRI bulan sumber: hanya nilai bulan yang benar-benar tersedia.
        kri_actual = []
        for key in source["keys"]:
            kri = source["risks"][key].get("kri") or {}
            status = kri.get("kri_status")
            actual = kri.get("kri_actual")
            if status is not None or actual is not None:
                kri_actual.append((key, status, actual))
        print(
            f"  KRI {MONTH_NAMES[month]} terisi pada sumber: "
            f"{len(kri_actual)} / 15"
        )
        for row in kri_actual:
            print("   -", row)

    return sources


def report_candidates(profile, month):
    return list(
        MonthlyRiskReport.objects
        .select_related("periode", "prepared_by")
        .filter(
            reassessment=profile,
            periode__tanggal_mulai__year=YEAR,
            periode__tanggal_mulai__month=month,
        )
        .order_by("-versi", "-pk")
    )


def prepared_user_for(profile):
    report = (
        MonthlyRiskReport.objects
        .select_related("prepared_by")
        .filter(reassessment=profile, prepared_by__isnull=False)
        .order_by("-periode__tanggal_mulai", "-pk")
        .first()
    )
    if report is not None:
        return report.prepared_by

    # Fallback mengikuti konfigurasi importer HCGA lama.
    user_id = getattr(base, "PREPARED_USER_ID", None)
    if user_id is None:
        stop("prepared_by tidak dapat ditentukan.")
    return get_user_model().objects.get(pk=user_id)


def resolve_or_plan_report(profile, month, *, apply=False):
    candidates = report_candidates(profile, month)
    editable = [r for r in candidates if r.status in ALLOWED_STATUSES]

    print(f"\n=== REPORT {MONTH_NAMES[month].upper()} {YEAR} ===")
    if candidates:
        for r in candidates:
            print(
                f"candidate id={r.pk} | status={r.status} "
                f"| versi={getattr(r, 'versi', None)} "
                f"| prepared={getattr(r.prepared_by, 'username', None)} "
                f"| item={r.items.count()} | total={r.total_risiko}"
            )
        if len(editable) != 1:
            stop(
                f"{MONTH_NAMES[month]} memiliki {len(editable)} report "
                "draft/revision; harus tepat 1."
            )
        return editable[0], False

    period = base.get_period(month)
    yearbook = base.get_yearbook()
    prepared = prepared_user_for(profile)

    print(
        f"WOULD CREATE {MONTH_NAMES[month]} | profile={profile.pk} "
        f"| period={period.pk} | yearbook={yearbook.pk} "
        f"| prepared={prepared.pk} {prepared.username}"
    )

    if not apply:
        return None, True

    kwargs = dict(
        reassessment=profile,
        periode=period,
        tahun_buku=yearbook,
        prepared_by=prepared,
        status="draft",
    )
    if base.get_field(MonthlyRiskReport, "versi") is not None:
        kwargs["versi"] = 1

    report = MonthlyRiskReport(**kwargs)
    report.full_clean()
    report.save()
    print(
        f"CREATED REPORT {MONTH_NAMES[month]}: "
        f"id={report.pk} | kode={getattr(report, 'kode', None)}"
    )
    return report, True


def backup_sqlite():
    engine = settings.DATABASES["default"].get("ENGINE", "")
    if "sqlite" not in engine:
        stop(f"Database aktif bukan SQLite: {engine}")

    db_path = Path(str(settings.DATABASES["default"]["NAME"])).resolve()
    if not db_path.exists():
        stop(f"SQLite database tidak ditemukan: {db_path}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = Path(
        os.getenv(
            "ERM_BACKUP_ROOT",
            "/home/adminsvr/erm_prod_archive",
        )
    ).expanduser().resolve()
    dest_dir = root / f"hcga_jun_jul_2026_{stamp}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "db.sqlite3.before_hcga_jun_jul"

    src = sqlite3.connect(str(db_path), timeout=30)
    dst = sqlite3.connect(str(dest), timeout=30)
    try:
        src.backup(dst)
        check = dst.execute("PRAGMA quick_check;").fetchone()[0]
    finally:
        dst.close()
        src.close()

    if check != "ok":
        stop(f"Backup SQLite gagal quick_check: {check}")

    print("BACKUP DB :", dest)
    print("BACKUP OK : quick_check=ok")
    return dest


def validate_profile_and_mapping():
    profile = base.resolve_profile()
    if profile.pk != PROFILE_ID or profile.unit_bisnis_id != UNIT_ID:
        stop(
            f"Profile HCGA berubah: profile={profile.pk}, "
            f"unit={profile.unit_bisnis_id}"
        )
    mappings = base.map_profile(profile)
    missing = [key for key in MONTH_KEYS if mappings.get(key) is None]
    if missing:
        stop(f"Master RiskEvent HCGA belum lengkap: {missing}")

    print(
        f"\nPROFILE OK | id={profile.pk} | {profile} "
        f"| unit={profile.unit_bisnis_id} {profile.unit_bisnis} "
        f"| master={profile.item.count()}"
    )
    for key in MONTH_KEYS:
        event = mappings[key]
        print(
            f"  {key:8} -> RE={event.pk} "
            f"| no_item={getattr(event, 'no_item', None)} "
            f"| event={getattr(event, 'peristiwa_risiko', None)}"
        )
    return profile, mappings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--month",
        choices=["all", "6", "7"],
        default="all",
        help="Default all = Juni dan Juli.",
    )
    args = ap.parse_args()

    months = [6, 7] if args.month == "all" else [int(args.month)]

    print("=" * 108)
    print("IMPORT BID HCGA JUNI & JULI 2026")
    print("Mode  :", "APPLY" if args.apply else "DRY RUN")
    print("Month :", ", ".join(MONTH_NAMES[m] for m in months))
    print("Source:", SOURCE_DIR)
    print("=" * 108)

    sources = load_sources(months)
    profile, mappings = validate_profile_and_mapping()

    reports = {}
    planned_new = {}
    for month in months:
        report, is_new = resolve_or_plan_report(profile, month, apply=False)
        reports[month] = report
        planned_new[month] = is_new

    previews = {}
    print("\n=== RINGKASAN DRY RUN ===")
    for month in months:
        p = base.preview_month(
            reports[month],
            sources[month],
            mappings,
            planned_new[month],
        )
        previews[month] = p
        print(
            f"{MONTH_NAMES[month]:5} | "
            f"Report={getattr(reports[month], 'pk', None) or 'NEW'} "
            f"| source={len(sources[month]['keys'])} "
            f"| create={p['creates']} "
            f"| update-items={p['updates']} "
            f"| field-change={p['fields']} "
            f"| residual-incomplete={p['incomplete']}"
        )

    print("\nCATATAN INTEGRITAS:")
    print("- Mapping berbasis event, bukan nomor source.")
    print("- Tidak ada report/item/master yang dihapus.")
    print("- Juni memakai residual Q2; Juli memakai residual Q3.")
    print("- KRI Juni/Juli tidak fallback ke nilai Mei.")
    print("- III.D tidak berisi perubahan profil pada sumber.")
    print("- III.E berisi contoh/template KEU lama; tidak diimpor sebagai loss event HCGA.")

    if not args.apply:
        print("\nDRY RUN SELESAI — database TIDAK BERUBAH.")
        return

    backup_sqlite()

    with transaction.atomic():
        real_reports = {}
        for month in months:
            report, _ = resolve_or_plan_report(profile, month, apply=True)
            real_reports[month] = report

        # Konsisten dengan importer HCGA sebelumnya: budget positif source
        # hanya disinkronkan bila tidak konflik dengan master existing.
        base.sync_positive_budgets(sources, mappings)

        results = {}
        for month in months:
            results[month] = base.apply_month(
                real_reports[month],
                sources[month],
                mappings,
            )

        for month in months:
            base.verify_month(
                real_reports[month],
                sources[month],
                mappings,
            )

    print("\n" + "=" * 108)
    print("APPLY & VERIFY HCGA JUNI/JULI BERHASIL")
    print("=" * 108)
    for month in months:
        report = MonthlyRiskReport.objects.get(pk=real_reports[month].pk)
        result = results[month]
        print(
            f"{MONTH_NAMES[month]:5} | "
            f"Report ID={report.pk} "
            f"| kode={getattr(report, 'kode', None)} "
            f"| status={report.status} "
            f"| item={report.items.count()} "
            f"| total={report.total_risiko} "
            f"| created={result['created']} "
            f"| updated={result['updated']} "
            f"| unchanged={result['unchanged']}"
        )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"\n{exc}", file=sys.stderr)
        raise SystemExit(2)
