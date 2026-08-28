#!/usr/bin/env python3
"""
CREATE KM SETPER RESMI 2026 V2 SAFE

Purpose
-------
Create a NEW official SETPER 2026 Kontrak Manajemen containing exactly the
11 KPIs from the official KM screenshot.

Safety design
-------------
- Existing KM id=15 is NEVER modified.
- Existing 24 ItemKontrakManajemen under KM id=15 are NEVER modified/deleted.
- Existing RKM id=10 is NEVER modified.
- Existing MonthlyRiskReport / ReAssessment references remain untouched.
- New official KM uses a different title so it can coexist with legacy KM 15.
- Official KM contains exactly 11 KPI rows; NO technical bridge rows.
- Default is DRY RUN using transaction rollback.
- --apply creates an SQLite backup first, then commits atomically.

Why versioning is required
--------------------------
Production audit proved KMItem 248 and several other legacy SETPER KM items
already have historical MonthlyRiskReportItem/ReAssessmentItem references.
Changing their semantic identity would rewrite history.

Expected official subtotal
--------------------------
A = 48
B = 16
C = 18
D = 8
E = 10
F = 0
TOTAL = 100

Existing legacy objects expected
--------------------------------
Unit Group id = 11 (SETPER)
Legacy KM id  = 15 (SETPER, 2026, Final)
RKM id        = 10 (RKM SETPER Juli 2026) -- stays on legacy KM in V2
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] if "risk/scripts" in str(Path(__file__).resolve()) else Path.cwd()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.prod")

import django
django.setup()

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from risk.models import (
    BagianKontrakManajemen,
    ItemKontrakManajemen,
    KontrakManajemen,
    RKMSummary,
)

UNIT_ID = 11
LEGACY_KM_ID = 15
RKM_ID = 10
YEAR = 2026

OFFICIAL_TITLE = "SETPER RESMI 2026"

SECTIONS = {
    "A": ("Nilai Ekonomi dan Sosial Untuk Indonesia", Decimal("48")),
    "B": ("Inovasi Model Bisnis", Decimal("16")),
    "C": ("Kepemimpinan Teknologi", Decimal("18")),
    "D": ("Peningkatan Investasi", Decimal("8")),
    "E": ("Pengembangan Talenta", Decimal("10")),
    "F": ("Kepatuhan", Decimal("0")),
}


@dataclass(frozen=True)
class OfficialRow:
    no: int
    section: str
    indicator: str
    formula: str
    unit: str
    weight: Decimal
    target: str
    polarity: str


ROWS = [
    OfficialRow(
        1, "A",
        "Pengelolaan Komunikasi & TJSL",
        "Rata-rata persen pencapaian aktifitas Komunikasi dan TJSL",
        "%", Decimal("14"), "100", "positif",
    ),
    OfficialRow(
        2, "A",
        "Maturity Level Sustainability",
        "Hasil Asesmen Maturity Level Sustainability",
        "%", Decimal("12"), "100", "positif",
    ),
    OfficialRow(
        3, "A",
        "Kualitas Penerapan Manajemen Risiko (KPMR)",
        "Penerapan Manajemen Risiko (KPMR) di SETPER",
        "Skor", Decimal("12"), "80", "positif",
    ),
    OfficialRow(
        4, "A",
        "Penyelesaian Proyek RUPTL",
        "Rata-rata Penyelesaian Reviu Kontrak Proyek EPC & Non EPC",
        "Hari kerja", Decimal("10"), "10", "negatif",
    ),
    OfficialRow(
        5, "B",
        "Reviu Draf Kontrak/Amandemen/HOA/MOU dari Unit Bisnis/Bidang",
        "Rata-rata Realisasi Laporan Hasil Reviu Draf Kontrak/Amandemen/HOA/MOU "
        "Sejak Dokumen Lengkap (exclude Kontrak Proyek RUPTL - EPC & Non EPC)",
        "Hari kerja", Decimal("8"), "3,50", "negatif",
    ),
    OfficialRow(
        6, "B",
        "Penerbitan Advis Hukum/Pendapat Hukum/Legal Opinion",
        "Rata-rata Realisasi Laporan Hasil Advis Hukum Pendapat Hukum Legal Opini "
        "Sejak Dokumen Lengkap",
        "Hari kerja", Decimal("8"), "10", "negatif",
    ),
    OfficialRow(
        7, "C",
        "Maturity Level Tata Kelola Perusahaan",
        "Nilai Maturity Level Tata Kelola Perusahaan",
        "Skor", Decimal("10"), "Sesuai Penetapan PLN (Persero)", "positif",
    ),
    OfficialRow(
        8, "C",
        "Implementasi Governance Risk Compliance (GRC)",
        "Rata-rata Penyampaian Laporan Hasil Reviu GRC",
        "Hari kerja", Decimal("8"), "5,00", "negatif",
    ),
    OfficialRow(
        9, "D",
        "Koordinasi Antar Lembaga dan Stakeholder PLN Batam",
        "Jumlah koordinasi eksternal antar lembaga dan stakeholder terhadap "
        "target rencana yang disahkan Direksi",
        "%", Decimal("8"), "100", "positif",
    ),
    OfficialRow(
        10, "E",
        "Pengelolaan Human Capital",
        "Rata-rata Pencapaian:\n"
        "1. Produktivitas Pegawai dan Penguatan Budaya\n"
        "2. Pengelolaan Human Capital Services",
        "%", Decimal("10"), "100", "positif",
    ),
    OfficialRow(
        11, "F",
        "Compliance",
        "Jumlah nilai pengurang dari unsur:\n"
        "- Maturity Level GCG\n"
        "- Kepatuhan Pengelolaan HSSE\n"
        "- Tindak lanjut temuan SPI, BPK, dan Auditor lainnya\n"
        "- Keterlambatan Laporan Kinerja (termasuk laporan manajemen risiko)\n"
        "- Planning Accuracy Compliance Adjustment (PACA)",
        "Nilai Pengurang", Decimal("0"), "Max -10", "negatif",
    ),
]


class DryRunRollback(Exception):
    pass


def banner(title: str) -> None:
    print("\n" + "=" * 140)
    print(title)
    print("=" * 140)


def backup_sqlite() -> Path:
    engine = settings.DATABASES["default"]["ENGINE"]
    if "sqlite3" not in engine:
        raise RuntimeError(
            f"STOP: backup otomatis script ini hanya mendukung SQLite; engine={engine!r}"
        )

    source = Path(str(settings.DATABASES["default"]["NAME"])).expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"STOP: file database SQLite tidak ditemukan: {source}")

    backup_dir = ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / (
        "db_before_create_km_setper_resmi_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".sqlite3"
    )

    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()

    check = sqlite3.connect(str(target))
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()

    if integrity != "ok":
        raise RuntimeError(f"STOP: backup integrity_check={integrity!r}")

    print("BACKUP SQLITE:", target)
    print("INTEGRITY    :", integrity)
    return target


def preflight():
    banner("PRE-FLIGHT")

    legacy = (
        KontrakManajemen.objects
        .select_related("unit_bisnis", "template")
        .get(pk=LEGACY_KM_ID)
    )
    rkm = RKMSummary.objects.get(pk=RKM_ID)

    print(
        f"Legacy KM : id={legacy.pk} | judul={legacy.judul!r} | "
        f"tahun={legacy.tahun} | unit={legacy.unit_bisnis_id} "
        f"{legacy.unit_bisnis.name!r} | status={legacy.status!r}"
    )
    print(
        f"Legacy rows: "
        f"{ItemKontrakManajemen.objects.filter(kontrak=legacy).count()}"
    )
    print(
        f"RKM       : id={rkm.pk} | judul={rkm.judul!r} | "
        f"KM={rkm.kontrak_manajemen_id} | unit={rkm.unit_bisnis_id} | "
        f"items={rkm.items.count() if hasattr(rkm, 'items') else 'n/a'}"
    )

    if legacy.unit_bisnis_id != UNIT_ID or legacy.tahun != YEAR:
        raise RuntimeError("STOP: legacy KM bukan SETPER 2026.")
    if rkm.kontrak_manajemen_id != LEGACY_KM_ID or rkm.unit_bisnis_id != UNIT_ID:
        raise RuntimeError("STOP: RKM ID=10 tidak lagi terhubung ke legacy KM15.")

    existing = KontrakManajemen.objects.filter(
        judul=OFFICIAL_TITLE,
        tahun=YEAR,
        unit_bisnis_id=UNIT_ID,
    )
    if existing.count() > 1:
        raise RuntimeError(
            f"STOP: duplicate official KM title ditemukan: "
            f"{list(existing.values_list('pk', flat=True))}"
        )

    if existing.exists():
        official = existing.get()
        print(
            f"Official candidate existing: id={official.pk} | "
            f"status={official.status!r} | "
            f"items={ItemKontrakManajemen.objects.filter(kontrak=official).count()}"
        )
    else:
        official = None
        print(f"Official KM belum ada -> akan dibuat {OFFICIAL_TITLE!r}")

    # Use the same template as legacy so section master references stay aligned.
    if not legacy.template_id:
        raise RuntimeError("STOP: legacy KM15 tidak memiliki template.")
    print("Template reuse:", legacy.template_id)

    return legacy, rkm, official


def section_templates(legacy):
    result = {}
    for code in "ABCDEF":
        item = (
            ItemKontrakManajemen.objects
            .filter(
                kontrak=legacy,
                master_bagian__kode_bagian=code,
            )
            .exclude(master_bagian__isnull=True)
            .order_by("pk")
            .first()
        )
        if item is None:
            raise RuntimeError(
                f"STOP: tidak ada master_bagian section {code} pada legacy KM15."
            )
        result[code] = item.master_bagian
        print(
            f"Section {code}: MasterBagian={item.master_bagian_id} "
            f"| {item.master_bagian.nama_bagian!r}"
        )
    return result


def official_matches(km) -> bool:
    items = list(
        ItemKontrakManajemen.objects
        .filter(kontrak=km)
        .select_related("master_bagian")
        .order_by("no_urut", "pk")
    )
    if len(items) != 11:
        return False

    by_no = {x.no_urut: x for x in items}
    if set(by_no) != set(range(1, 12)):
        return False

    for row in ROWS:
        x = by_no[row.no]
        if x.master_bagian.kode_bagian != row.section:
            return False
        if x.indikator_kinerja_kunci != row.indicator:
            return False
        if (x.formula or "") != row.formula:
            return False
        if (x.satuan or "") != row.unit:
            return False
        if Decimal(str(x.bobot or 0)) != row.weight:
            return False
        if (x.target or "") != row.target:
            return False
        if (x.polaritas or "") != row.polarity:
            return False
    return True


def create_or_validate_official(legacy, existing, masters):
    if existing is not None:
        if official_matches(existing):
            print(
                f"Official KM id={existing.pk} sudah identik dengan source. "
                f"Tidak membuat ulang."
            )
            return existing
        raise RuntimeError(
            f"STOP: official KM id={existing.pk} sudah ada tetapi tidak identik. "
            "Script tidak overwrite."
        )

    official = KontrakManajemen(
        judul=OFFICIAL_TITLE,
        tahun=YEAR,
        unit_bisnis_id=UNIT_ID,
        status="Final",
        template_id=legacy.template_id,
    )
    official.full_clean()
    official.save()

    print(
        f"CREATE KM id={official.pk} | {official.judul!r} | "
        f"tahun={official.tahun} | status={official.status}"
    )

    parts = {}
    for code, (name, _weight) in SECTIONS.items():
        part = BagianKontrakManajemen(
            kontrak=official,
            kode_bagian=code,
            nama_bagian=name,
        )
        part.full_clean()
        part.save()
        parts[code] = part
        print(f"CREATE BAGIAN {code} | {name}")

    for row in ROWS:
        item = ItemKontrakManajemen(
            kontrak=official,
            bagian=parts[row.section],
            master_bagian=masters[row.section],
            no_urut=row.no,
            indikator_kinerja_kunci=row.indicator,
            formula=row.formula,
            satuan=row.unit,
            bobot=row.weight,
            target=row.target,
            polaritas=row.polarity,
        )
        item.full_clean()
        item.save()
        print(
            f"CREATE KPI {row.no:02d} | section={row.section} | "
            f"bobot={row.weight:<3} | {row.indicator}"
        )

    return official


def verify(legacy, rkm, official):
    banner("VERIFY IN TRANSACTION")

    # Legacy objects must remain untouched structurally.
    if ItemKontrakManajemen.objects.filter(kontrak=legacy).count() != 24:
        raise RuntimeError(
            "STOP: jumlah legacy KM15 berubah; seharusnya tetap 24."
        )
    if rkm.kontrak_manajemen_id != LEGACY_KM_ID:
        raise RuntimeError("STOP: RKM ID10 berpindah KM pada V2, tidak diizinkan.")

    items = list(
        ItemKontrakManajemen.objects
        .filter(kontrak=official)
        .select_related("master_bagian")
        .order_by("no_urut", "pk")
    )
    if len(items) != 11:
        raise RuntimeError(f"STOP: official item={len(items)}, expected=11.")

    subtotal = {k: Decimal("0") for k in SECTIONS}
    total = Decimal("0")

    for row, item in zip(ROWS, items):
        section = item.master_bagian.kode_bagian

        checks = {
            "no_urut": (item.no_urut, row.no),
            "section": (section, row.section),
            "indicator": (item.indikator_kinerja_kunci, row.indicator),
            "formula": (item.formula or "", row.formula),
            "unit": (item.satuan or "", row.unit),
            "weight": (Decimal(str(item.bobot or 0)), row.weight),
            "target": (item.target or "", row.target),
            "polarity": (item.polaritas or "", row.polarity),
        }
        for label, (actual, expected) in checks.items():
            if actual != expected:
                raise RuntimeError(
                    f"STOP: KPI official no={row.no} {label} mismatch: "
                    f"actual={actual!r}, expected={expected!r}"
                )

        subtotal[section] += Decimal(str(item.bobot or 0))
        total += Decimal(str(item.bobot or 0))

    expected_subtotal = {k: v[1] for k, v in SECTIONS.items()}
    if subtotal != expected_subtotal:
        raise RuntimeError(
            f"STOP: subtotal={subtotal}, expected={expected_subtotal}"
        )
    if total != Decimal("100"):
        raise RuntimeError(f"STOP: total bobot={total}, expected=100.")

    print("Legacy KM id=15 rows : 24 = UNTOUCHED")
    print("RKM id=10 legacy KM  : 15 = UNTOUCHED")
    print("Official KM id       :", official.pk)
    print("Official KPI         : 11 = PASS")
    print("Subtotal             :", subtotal)
    print("Total bobot          :", total)
    print("Technical bridge     : 0 in official KM = PASS")
    print("VERIFY               : PASS")


def execute(apply: bool):
    legacy, rkm, existing = preflight()

    banner("SECTION MASTER PREFLIGHT")
    masters = section_templates(legacy)

    if existing is not None and official_matches(existing):
        banner("RESULT")
        verify(legacy, rkm, existing)
        print("Official KM sudah tersedia dan identik. Database tidak diubah.")
        return

    if apply:
        backup_sqlite()

    official_id = None
    try:
        with transaction.atomic():
            legacy = (
                KontrakManajemen.objects
                .select_for_update()
                .select_related("unit_bisnis", "template")
                .get(pk=LEGACY_KM_ID)
            )
            rkm = RKMSummary.objects.select_for_update().get(pk=RKM_ID)

            existing_locked = (
                KontrakManajemen.objects
                .filter(
                    judul=OFFICIAL_TITLE,
                    tahun=YEAR,
                    unit_bisnis_id=UNIT_ID,
                )
                .first()
            )

            official = create_or_validate_official(
                legacy, existing_locked, masters
            )
            official_id = official.pk
            verify(legacy, rkm, official)

            if not apply:
                raise DryRunRollback()

    except DryRunRollback:
        banner("RINGKASAN DRY RUN")
        print("Legacy KM id=15     : UNTOUCHED")
        print("Legacy KM items     : 24 UNTOUCHED")
        print("RKM id=10           : UNTOUCHED")
        print("Official KM         : 1 (ROLLBACK)")
        print("Official KPI        : 11 (ROLLBACK)")
        print("Technical bridges   : 0")
        print("Official total bobot: 100")
        print("Database             : TIDAK BERUBAH")
        print("\nDRY RUN SELESAI — transaction rollback berhasil.")
        return

    banner("APPLY BERHASIL — KM SETPER RESMI 2026")
    official = KontrakManajemen.objects.get(pk=official_id)
    print("Official KM id      :", official.pk)
    print("Judul               :", official.judul)
    print("Unit                :", official.unit_bisnis)
    print("Tahun               :", official.tahun)
    print("Status              :", official.status)
    print(
        "Official KPI        :",
        ItemKontrakManajemen.objects.filter(kontrak=official).count(),
    )
    print("Legacy KM id=15     : UNTOUCHED")
    print("RKM id=10           : UNTOUCHED")
    print("VERIFY              : PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit perubahan. Default dry-run rollback.",
    )
    args = parser.parse_args()

    banner("CREATE KM SETPER RESMI 2026 V2 SAFE")
    print("Mode    :", "APPLY" if args.apply else "DRY RUN")
    print("Settings:", os.environ.get("DJANGO_SETTINGS_MODULE"))

    try:
        execute(args.apply)
    except (RuntimeError, ValidationError) as exc:
        print(f"\nSTOP: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
