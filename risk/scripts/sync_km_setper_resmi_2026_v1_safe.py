#!/usr/bin/env python3
"""
SYNC KM SETPER RESMI 2026 V1 SAFE

Basis:
- KM resmi SETPER 2026 dari screenshot resmi yang diberikan pengguna.
- Production target:
    Group SETPER = 11
    KontrakManajemen = 15
    RKM SETPER Juli 2026 = 10

Desain:
- Canonical KM resmi = 11 KPI.
- 6 technical bridge tetap dipertahankan karena RKM SETPER Juli memiliki
  16 baris dan model RKMItem mewajibkan km_item unik per summary.
- Technical bridge tidak berbobot (0) dan tetap berprefix "[RKM SETPER ...]".
- Bridge 379 (Legal Opinion) dipromosikan menjadi KPI KM resmi no.6 karena
  semantiknya tepat dan sudah direferensikan RKMItem 105.
- Item 248 dipromosikan menjadi KPI resmi no.4 "Penyelesaian Proyek RUPTL"
  hanya jika tidak memiliki dependency historis.
- Placeholder/legacy 242..247 dan 257 dihapus HANYA jika tidak memiliki
  dependency apa pun.
- RKM ID=10 tidak dihapus/recreate dan FK 16 item tidak diubah.
- Default = DRY RUN transactional rollback.
- --apply = backup SQLite + commit atomik.

Expected final physical rows pada KM 15:
  11 canonical KPI resmi
  + 6 technical bridge
  = 17 ItemKontrakManajemen

Expected official weighted subtotal:
  A=48, B=16, C=18, D=8, E=10, F=0
  TOTAL=100
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
    ItemKontrakManajemen,
    KontrakManajemen,
    RKMItem,
    RKMSummary,
)

UNIT_ID = 11
KM_ID = 15
RKM_ID = 10
YEAR = 2026

TECH_PREFIX = "[RKM SETPER "

# Existing IDs selected from production audit.
OFFICIAL_ID_BY_NO = {
    1: 249,
    2: 250,
    3: 251,
    4: 248,
    5: 252,
    6: 379,  # current bridge Legal Opinion -> promoted to official
    7: 253,
    8: 254,
    9: 255,
    10: 256,
    11: 258,
}

# Remain technical because the RKM source has distinct rows that do not have
# one-to-one official KM KPI identities.
TECHNICAL_IDS = (375, 376, 377, 378, 380, 381)

# Empty/legacy physical rows from the current KM, plus Safety Culture which
# does not exist as a separate KPI in the official SETPER KM screenshot.
DELETE_CANDIDATES = (242, 243, 244, 245, 246, 247, 257)

# Item 248 changes semantic identity from "Optimalisasi Biaya Pemeliharaan"
# to "Penyelesaian Proyek RUPTL". It must not have historical dependencies.
SEMANTIC_REPURPOSE_IDS = (248,)

SECTION_EXPECTED = {
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
        "- Kepatuhan pengelolaan HSSE\n"
        "- Tindak lanjut temuan SPI, BPK, dan Auditor lainnya\n"
        "- Keterlambatan Laporan Kinerja (termasuk laporan manajemen risiko)\n"
        "- Planning Accuracy Compliance Adjustment (PACA)",
        "Nilai Pengurang", Decimal("0"), "Max -10", "negatif",
    ),
]


class DryRunRollback(Exception):
    pass


def banner(title):
    print("\n" + "=" * 140)
    print(title)
    print("=" * 140)


def related_usage(obj):
    """
    Return non-empty reverse relations.
    Conservative: if an object is referenced anywhere, deletion/semantic repurpose
    is blocked unless specifically allowed.
    """
    found = []
    for rel in obj._meta.related_objects:
        accessor = rel.get_accessor_name()
        try:
            manager_or_obj = getattr(obj, accessor)
        except Exception:
            continue

        try:
            if rel.one_to_one:
                related = manager_or_obj
                if related is not None:
                    found.append((rel.related_model._meta.label, accessor, 1))
            else:
                count = manager_or_obj.count()
                if count:
                    found.append((rel.related_model._meta.label, accessor, count))
        except rel.related_model.DoesNotExist:
            pass
        except Exception:
            # Do not silently declare safe if a relation cannot be inspected.
            found.append((rel.related_model._meta.label, accessor, -1))
    return found


def backup_sqlite():
    engine = settings.DATABASES["default"]["ENGINE"]
    if "sqlite3" not in engine:
        raise RuntimeError(
            f"STOP: backup otomatis script ini hanya untuk SQLite; engine={engine!r}"
        )

    source = Path(str(settings.DATABASES["default"]["NAME"])).expanduser().resolve()
    if not source.exists():
        raise RuntimeError(f"STOP: SQLite DB tidak ditemukan: {source}")

    backup_dir = ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / (
        "db_before_sync_km_setper_resmi_"
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
        raise RuntimeError(
            f"STOP: backup integrity_check={integrity!r}"
        )

    print("BACKUP SQLITE:", target)
    print("INTEGRITY    :", integrity)
    return target


def preflight_objects():
    banner("PRE-FLIGHT TARGET")

    km = (
        KontrakManajemen.objects
        .select_related("unit_bisnis")
        .get(pk=KM_ID)
    )
    rkm = RKMSummary.objects.get(pk=RKM_ID)

    print(
        f"KM  : id={km.pk} | judul={km.judul!r} | tahun={km.tahun} | "
        f"unit={km.unit_bisnis_id} {km.unit_bisnis.name!r} | status={km.status!r}"
    )
    print(
        f"RKM : id={rkm.pk} | judul={rkm.judul!r} | tahun={rkm.tahun} | "
        f"bulan={rkm.bulan} | unit={rkm.unit_bisnis_id} | KM={rkm.kontrak_manajemen_id}"
    )

    if km.unit_bisnis_id != UNIT_ID or km.tahun != YEAR:
        raise RuntimeError("STOP: KM target bukan SETPER 2026 yang diharapkan.")
    if rkm.unit_bisnis_id != UNIT_ID or rkm.kontrak_manajemen_id != KM_ID:
        raise RuntimeError("STOP: RKM ID=10 tidak terhubung ke SETPER/KM15.")
    if rkm.tahun != YEAR or rkm.bulan != 7:
        raise RuntimeError("STOP: RKM ID=10 bukan Juli 2026.")

    items = list(
        ItemKontrakManajemen.objects
        .filter(kontrak=km)
        .order_by("no_urut", "pk")
    )
    print("Physical KM items:", len(items))
    for x in items:
        print(
            f"  KMItem={x.pk:<4} | no={x.no_urut!s:<4} | "
            f"bobot={x.bobot!s:<6} | {x.indikator_kinerja_kunci!r}"
        )

    needed = (
        set(OFFICIAL_ID_BY_NO.values())
        | set(TECHNICAL_IDS)
        | set(DELETE_CANDIDATES)
    )
    actual = set(
        ItemKontrakManajemen.objects
        .filter(pk__in=needed, kontrak=km)
        .values_list("pk", flat=True)
    )
    missing = sorted(needed - actual)
    if missing:
        raise RuntimeError(f"STOP: expected KMItem IDs missing dari KM15: {missing}")

    return km, rkm


def preflight_constraints(rkm):
    banner("PRE-FLIGHT RKM CONSTRAINT / LINKS")

    constraint_text = [str(x) for x in RKMItem._meta.constraints]
    for c in constraint_text:
        print(c)

    # Must retain unique km_item mapping: this is why 6 technical bridges remain.
    if not any("summary" in x and "km_item" in x for x in constraint_text):
        raise RuntimeError(
            "STOP: constraint (summary, km_item) tidak terdeteksi; "
            "review desain sebelum sync."
        )

    links = list(
        RKMItem.objects
        .filter(summary=rkm)
        .order_by("no_item", "pk")
        .values_list("pk", "no_item", "km_item_id", "kpi_indikator")
    )
    if len(links) != 16:
        raise RuntimeError(f"STOP: RKM ID=10 items={len(links)}, expected=16.")
    if len({x[2] for x in links}) != 16:
        raise RuntimeError("STOP: current RKM km_item tidak unique 16/16.")

    for pk, no, km_item_id, label in links:
        print(
            f"RKMItem={pk:<4} no={no:<2} km_item={km_item_id:<4} | {label}"
        )

    return links


def preflight_deletions(km):
    banner("PRE-FLIGHT DELETE / REPURPOSE SAFETY")

    # Semantic repurpose: must be dependency-free.
    for pk in SEMANTIC_REPURPOSE_IDS:
        obj = ItemKontrakManajemen.objects.get(pk=pk, kontrak=km)
        usage = related_usage(obj)
        print(
            f"REPURPOSE KMItem={pk} {obj.indikator_kinerja_kunci!r} "
            f"| refs={usage or 'NONE'}"
        )
        if usage:
            raise RuntimeError(
                f"STOP: KMItem {pk} akan berubah semantic tetapi masih direferensikan: {usage}"
            )

    for pk in DELETE_CANDIDATES:
        obj = ItemKontrakManajemen.objects.get(pk=pk, kontrak=km)
        usage = related_usage(obj)
        print(
            f"DELETE candidate KMItem={pk} {obj.indikator_kinerja_kunci!r} "
            f"| refs={usage or 'NONE'}"
        )
        if usage:
            raise RuntimeError(
                f"STOP: delete candidate KMItem {pk} masih direferensikan: {usage}"
            )


def section_template_items(km):
    """
    Use current known official items as section FK templates.
    Avoid modifying shared MasterBagian metadata.
    """
    template_pk = {
        "A": 249,
        "B": 252,
        "C": 253,
        "D": 255,
        "E": 256,
        "F": 258,
    }
    result = {}
    for section, pk in template_pk.items():
        obj = ItemKontrakManajemen.objects.get(pk=pk, kontrak=km)
        if not obj.master_bagian_id:
            raise RuntimeError(
                f"STOP: section template {section} KMItem={pk} tidak punya master_bagian."
            )
        result[section] = obj
    return result


def update_official_items(km):
    banner("SYNC 11 OFFICIAL KM ITEMS")

    section_templates = section_template_items(km)
    official_ids = []

    for row in ROWS:
        pk = OFFICIAL_ID_BY_NO[row.no]
        item = ItemKontrakManajemen.objects.select_for_update().get(
            pk=pk, kontrak=km
        )
        template = section_templates[row.section]

        before = (
            item.no_urut,
            item.indikator_kinerja_kunci,
            item.formula,
            item.satuan,
            str(item.bobot) if item.bobot is not None else None,
            item.target,
            item.polaritas,
            item.master_bagian_id,
            item.bagian_id,
        )

        item.no_urut = row.no
        item.indikator_kinerja_kunci = row.indicator
        item.formula = row.formula
        item.satuan = row.unit
        item.bobot = row.weight
        item.target = row.target
        item.polaritas = row.polarity
        item.master_bagian_id = template.master_bagian_id
        item.bagian_id = template.bagian_id

        item.full_clean()
        item.save()

        after = (
            item.no_urut,
            item.indikator_kinerja_kunci,
            item.formula,
            item.satuan,
            str(item.bobot) if item.bobot is not None else None,
            item.target,
            item.polaritas,
            item.master_bagian_id,
            item.bagian_id,
        )

        changes = sum(1 for a, b in zip(before, after) if a != b)
        official_ids.append(item.pk)

        print(
            f"{row.no:02d}. KMItem={item.pk:<4} | {row.section} | "
            f"bobot={item.bobot:<5} | changes={changes:<2} | "
            f"{item.indikator_kinerja_kunci}"
        )

    return official_ids


def normalize_technical_bridges(km):
    banner("KEEP 6 TECHNICAL BRIDGES")

    # Keep exact identity/FK for RKM source rows.
    expected_tokens = {
        375: "[RKM SETPER A.2]",
        376: "[RKM SETPER B.1]",
        377: "[RKM SETPER B.3]",
        378: "[RKM SETPER C.1]",
        380: "[RKM SETPER C.4]",
        381: "[RKM SETPER C.5]",
    }

    for offset, pk in enumerate(TECHNICAL_IDS, start=1):
        item = ItemKontrakManajemen.objects.select_for_update().get(
            pk=pk, kontrak=km
        )

        token = expected_tokens[pk]
        if not (item.indikator_kinerja_kunci or "").startswith(token):
            raise RuntimeError(
                f"STOP: bridge KMItem={pk} label berubah: "
                f"{item.indikator_kinerja_kunci!r}"
            )

        item.no_urut = 100 + offset
        item.bobot = Decimal("0")
        item.full_clean()
        item.save(update_fields=["no_urut", "bobot"])

        print(
            f"KEEP KMItem={pk} | no={item.no_urut} | bobot={item.bobot} | "
            f"{item.indikator_kinerja_kunci}"
        )


def delete_legacy_rows(km):
    banner("DELETE 7 LEGACY / PLACEHOLDER ITEMS")

    for pk in DELETE_CANDIDATES:
        item = ItemKontrakManajemen.objects.select_for_update().get(
            pk=pk, kontrak=km
        )
        usage = related_usage(item)
        if usage:
            raise RuntimeError(
                f"STOP: KMItem={pk} mendapatkan dependency baru saat transaction: {usage}"
            )
        print(
            f"DELETE KMItem={pk} | no={item.no_urut} | "
            f"{item.indikator_kinerja_kunci!r}"
        )
        item.delete()


def verify_final(km, rkm, before_rkm_links):
    banner("HARD VERIFY IN TRANSACTION")

    physical = list(
        ItemKontrakManajemen.objects
        .filter(kontrak=km)
        .select_related("master_bagian")
        .order_by("no_urut", "pk")
    )

    official_ids = set(OFFICIAL_ID_BY_NO.values())
    official = [x for x in physical if x.pk in official_ids]
    technical = [
        x for x in physical
        if (x.indikator_kinerja_kunci or "").startswith(TECH_PREFIX)
    ]

    if len(physical) != 17:
        raise RuntimeError(
            f"STOP: physical KM rows={len(physical)}, expected 17 (11 official + 6 technical)."
        )
    if len(official) != 11:
        raise RuntimeError(f"STOP: official KM rows={len(official)}, expected 11.")
    if len(technical) != 6:
        raise RuntimeError(f"STOP: technical rows={len(technical)}, expected 6.")

    rows_by_no = {x.no_urut: x for x in official}
    if set(rows_by_no) != set(range(1, 12)):
        raise RuntimeError(
            f"STOP: official no_urut bukan 1..11: {sorted(rows_by_no)}"
        )

    subtotal = {k: Decimal("0") for k in SECTION_EXPECTED}
    total = Decimal("0")

    for row in ROWS:
        item = rows_by_no[row.no]
        section = item.master_bagian.kode_bagian

        checks = {
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
                    f"STOP: official no={row.no} {label} mismatch: "
                    f"actual={actual!r} expected={expected!r}"
                )

        subtotal[section] += Decimal(str(item.bobot or 0))
        total += Decimal(str(item.bobot or 0))

    expected_subtotal = {k: v[1] for k, v in SECTION_EXPECTED.items()}
    if subtotal != expected_subtotal:
        raise RuntimeError(
            f"STOP: subtotal={subtotal}, expected={expected_subtotal}"
        )
    if total != Decimal("100"):
        raise RuntimeError(f"STOP: total bobot={total}, expected=100.")

    for item in technical:
        if Decimal(str(item.bobot or 0)) != Decimal("0"):
            raise RuntimeError(
                f"STOP: technical KMItem={item.pk} bobot bukan 0."
            )

    after_rkm_links = {
        x.pk: x.km_item_id
        for x in RKMItem.objects.filter(summary=rkm).order_by("pk")
    }
    if after_rkm_links != before_rkm_links:
        raise RuntimeError(
            "STOP: FK RKM SETPER ID=10 berubah. Transaction dibatalkan."
        )

    rkm_items = list(
        RKMItem.objects.filter(summary=rkm).order_by("no_item", "pk")
    )
    if len(rkm_items) != 16:
        raise RuntimeError("STOP: RKM SETPER tidak lagi 16 item.")
    if len({x.km_item_id for x in rkm_items}) != 16:
        raise RuntimeError("STOP: RKM km_item tidak unique 16/16.")

    print("Physical KM rows      : 17 = PASS")
    print("Official KM rows      : 11 = PASS")
    print("Technical bridges     : 6  = PASS")
    print("Official subtotal     :", subtotal)
    print("Official total bobot  :", total)
    print("RKM ID=10 items       : 16 = PASS")
    print("RKM FK mapping        : UNCHANGED = PASS")
    print("Technical bobot       : 0 = PASS")
    print("HARD VERIFY           : PASS")


def execute(apply):
    km, rkm = preflight_objects()
    links = preflight_constraints(rkm)
    preflight_deletions(km)

    before_rkm_links = {
        x[0]: x[2] for x in links
    }

    if apply:
        backup_sqlite()

    try:
        with transaction.atomic():
            km = KontrakManajemen.objects.select_for_update().get(pk=KM_ID)
            rkm = RKMSummary.objects.select_for_update().get(pk=RKM_ID)

            # Re-check safety after locks.
            preflight_deletions(km)

            update_official_items(km)
            normalize_technical_bridges(km)
            delete_legacy_rows(km)

            # Keep official KM metadata stable/final.
            if km.status != "Final":
                km.status = "Final"
                km.save(update_fields=["status"])

            verify_final(km, rkm, before_rkm_links)

            if not apply:
                raise DryRunRollback()

    except DryRunRollback:
        banner("RINGKASAN DRY RUN")
        print("Official KPI sync        : 11 (ROLLBACK)")
        print("Technical bridge retained: 6  (ROLLBACK)")
        print("Bridge promoted official : KMItem 379 / Legal Opinion")
        print("Legacy/placeholder delete: 7  (ROLLBACK)")
        print("RKM item count           : 16")
        print("RKM FK changed           : 0")
        print("Official total bobot     : 100")
        print("Final physical KM rows   : 17 = 11 official + 6 technical")
        print("Database                 : TIDAK BERUBAH")
        print("\nDRY RUN SELESAI — rollback berhasil.")
        return

    banner("APPLY BERHASIL — KM SETPER RESMI 2026")
    km = KontrakManajemen.objects.get(pk=KM_ID)
    physical = ItemKontrakManajemen.objects.filter(kontrak=km)
    technical = physical.filter(
        indikator_kinerja_kunci__startswith=TECH_PREFIX
    )

    print("KM                  :", km.pk, km.judul, km.status)
    print("Physical KM rows    :", physical.count())
    print("Official KPI        :", physical.exclude(
        indikator_kinerja_kunci__startswith=TECH_PREFIX
    ).count())
    print("Technical bridges   :", technical.count())
    print("RKM SETPER items    :", RKMItem.objects.filter(summary_id=RKM_ID).count())
    print("VERIFY              : PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit perubahan. Default adalah dry-run transactional rollback.",
    )
    args = parser.parse_args()

    banner("SYNC KM SETPER RESMI 2026 V1 SAFE")
    print("Mode    :", "APPLY" if args.apply else "DRY RUN")
    print("Settings:", os.environ.get("DJANGO_SETTINGS_MODULE"))

    try:
        execute(args.apply)
    except (RuntimeError, ValidationError) as exc:
        print(f"\nSTOP: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
