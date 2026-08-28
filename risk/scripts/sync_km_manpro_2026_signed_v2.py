#!/usr/bin/env python3
"""
SYNC SIGNED KM MANPRO 2026 -> production KM id=12 (VPMANPRO)

Source:
  KM MANPRO 2026.pdf
  Signed 27 February 2026
  Unit: BID MANPRO
  Canonical KPI: 14
  Canonical bobot: 100

Safety:
- ONLY targets KontrakManajemen id=12.
- KM id=16 and id=17 are NOT modified.
- Existing canonical IDs are locked and verified.
- Creates only the two signed KPIs missing from KM id=12:
    no.8  PLTS 100 MWac
    no.10 IPP PLTGU Batam 3 & 4 (300 MW)
- Existing extra/technical rows are preserved.
- RKM references are verified to remain unchanged.
- SQLite backup before apply.
- Default mode is DRY-RUN. Use --apply only after reviewing output.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path("/home/adminsvr/erm")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.prod")

import django
django.setup()

from django.conf import settings
from django.db import transaction
from risk.models import (
    BagianKontrakManajemen,
    ItemKontrakManajemen,
    KontrakManajemen,
    MasterBagianKM,
    RKMItem,
    RKMSummary,
)

KM_ID = 12
UNIT_NAME = "BID MANPRO"
TITLE = "VPMANPRO"
YEAR = 2026
SIGNED_DATE = date(2026, 2, 27)

SECTIONS = {
    "A": ("Nilai Ekonomi dan Sosial Untuk Indonesia", Decimal("46")),
    "B": ("Inovasi Model Bisnis", Decimal("18")),
    "C": ("Kepemimpinan Teknologi", Decimal("18")),
    "D": ("Peningkatan Investasi", Decimal("10")),
    "E": ("Pengembangan Talenta", Decimal("8")),
    "F": ("Kepatuhan", Decimal("0")),
}

PROGRESS = (
    "Realisasi Progres Sesuai Kontrak (kurva s) x 100% / "
    "Target Progress Sesuai Kontrak (kurva s) yang Disahkan"
)

HC_FORMULA = """Rata-rata Pencapaian:
1. Produktivitas Pegawai dan Penguatan Budaya
2. Pengelolaan Human Capital Services"""

COMPLIANCE_FORMULA = """Jumlah nilai pengurang dari unsur:
- Maturity Level GCG
- Kepatuhan pengelolaan HSSE
- Tindak lanjut temuan SPI, BPK, dan Auditor lainnya
- Keterlambatan Laporan Kinerja (termasuk laporan manajemen risiko)
- Planning Accuracy Compliance Adjustment (PACA)"""


@dataclass(frozen=True)
class Row:
    no: int
    section: str
    indicator: str
    formula: str
    unit: str
    weight: Decimal
    target: str
    polarity: str | None


ROWS = [
    Row(1, "A", "Sewa PLTMG Batam - Batu Ampar 30 MW",
        PROGRESS, "%", Decimal("6"), "100", "positif"),
    Row(2, "A", "Sewa PLTMG Batam - Sei Harapan 30 MW",
        PROGRESS, "%", Decimal("6"), "100", "positif"),
    Row(3, "A", "Sewa PLTMG Batam - Sekupang 90 MW",
        PROGRESS, "%", Decimal("6"), "100", "positif"),
    Row(4, "A", "Sewa PLTMG Batam - Muka Kuning 50 MW",
        PROGRESS, "%", Decimal("6"), "100", "positif"),
    Row(5, "A", "Sewa PLTMG Batam - Tanjung Sengkuang 80 MW",
        PROGRESS, "%", Decimal("6"), "100", "positif"),
    Row(6, "A", "Maturity Level Sustainability",
        "Hasil Asesmen Maturity Level Sustainability",
        "%", Decimal("8"), "100", "positif"),
    Row(7, "A", "Kualitas Penerapan Manajemen Risiko (KPMR)",
        "Penerapan Manajemen Risiko (KPMR) di Bidang MANPRO",
        "Skor", Decimal("8"), "80", "positif"),

    Row(8, "B",
        "Pembangunan Pembangkit Listrik IPP Tenaga Surya (PLTS) 100 MWac dengan skema IPP",
        PROGRESS, "%", Decimal("9"), "100", "positif"),
    Row(9, "B", "Pekerjaan Bay Trafo 7X60 MVA",
        PROGRESS, "%", Decimal("9"), "100", "positif"),

    Row(10, "C", "Pembangunan IPP PLTGU Batam 3 dan 4 (300MW)",
        PROGRESS, "%", Decimal("9"), "100", "positif"),
    Row(11, "C", "Reroute T.26 Baloi-Sengkuang",
        "Tersedianya Berita Acara Commercial Operation Date (COD)",
        "Waktu", Decimal("9"), "06 April 2026", "negatif"),

    Row(12, "D", "Pembangunan PLTGU Batam#1 120 MW - Kabil",
        PROGRESS, "%", Decimal("10"), "100", "positif"),

    Row(13, "E", "Pengelolaan Human Capital",
        HC_FORMULA, "%", Decimal("8"), "100", "positif"),

    # Signed source has no polarity arrow on Compliance; preserve DB polarity.
    Row(14, "F", "Compliance",
        COMPLIANCE_FORMULA, "Nilai Pengurang", Decimal("0"), "Max -10", None),
]

# Canonical existing IDs verified by production audit.
KNOWN_IDS = {
    1: 230,
    2: 231,
    3: 232,
    4: 233,
    5: 234,
    6: 235,
    7: 236,
    9: 237,
    11: 238,
    12: 239,
    13: 240,
    14: 241,
}

# Strong name safeguards for known existing rows.
NAME_TOKENS = {
    1: ("batu ampar 30 mw",),
    2: ("sei harapan 30 mw",),
    3: ("90 mw",),  # DB legacy says Sagulung; signed source says Sekupang.
    4: ("muka kuning 50 mw",),
    5: ("tanjung sengkuang 80 mw",),
    6: ("maturity level sustainability",),
    7: ("kpmr", "kualitas penerapan manajemen risiko"),
    9: ("bay trafo 7x60 mva",),
    11: ("reroute", "baloi", "sengkuang"),
    12: ("120 mw", "kabil"),
    13: ("pengelolaan human capital",),
    14: ("compliance",),
}


def norm(value) -> str:
    s = str(value or "").casefold().replace("#", " ").replace("×", "x")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def backup_sqlite():
    engine = settings.DATABASES["default"].get("ENGINE", "")
    if "sqlite" not in engine:
        print("BACKUP DB: skipped; database bukan SQLite.")
        return None

    src = Path(settings.DATABASES["default"]["NAME"]).resolve()
    dst_dir = Path("/home/adminsvr/backup")
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"db_before_sync_km_manpro_2026_{datetime.now():%Y%m%d_%H%M%S}.sqlite3"

    with sqlite3.connect(src) as source:
        with sqlite3.connect(dst) as target:
            source.backup(target)

    with sqlite3.connect(dst) as con:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]

    print("BACKUP DB:", dst)
    print("INTEGRITY:", integrity)
    if integrity != "ok":
        raise RuntimeError("STOP: backup SQLite gagal integrity_check.")
    return dst


def source_audit():
    print("=" * 142)
    print("SOURCE AUDIT - SIGNED KM MANPRO 2026")
    print("=" * 142)
    print("Tanggal kontrak : 27 Februari 2026")
    print("Target KM       : id=12 / VPMANPRO / BID MANPRO")
    print("Jumlah KPI      :", len(ROWS))

    sums = {}
    for row in ROWS:
        sums[row.section] = sums.get(row.section, Decimal("0")) + row.weight
        print(
            f"{row.no:02d} | {row.section} | bobot={row.weight:<2} | "
            f"target={row.target:<14} | {row.indicator}"
        )

    print("-" * 142)
    for code in "ABCDEF":
        actual = sums.get(code, Decimal("0"))
        expected = SECTIONS[code][1]
        print(f"Bagian {code}: {actual} / expected {expected}")
        if actual != expected:
            raise RuntimeError(f"STOP: bobot source bagian {code} mismatch")

    total = sum(sums.values(), Decimal("0"))
    print("TOTAL BOBOT:", total)
    if total != Decimal("100"):
        raise RuntimeError("STOP: total bobot source bukan 100")


def load_target():
    km = (
        KontrakManajemen.objects
        .select_related("unit_bisnis", "template")
        .get(pk=KM_ID)
    )

    if km.judul != TITLE:
        raise RuntimeError(f"STOP: KM id=12 judul={km.judul!r}, expected={TITLE!r}")
    if km.tahun != YEAR:
        raise RuntimeError(f"STOP: KM id=12 tahun={km.tahun}, expected={YEAR}")
    if str(km.unit_bisnis) != UNIT_NAME:
        raise RuntimeError(f"STOP: KM id=12 unit={km.unit_bisnis!r}, expected={UNIT_NAME!r}")
    if not km.template_id:
        raise RuntimeError("STOP: KM id=12 tidak memiliki template.")

    # Ensure the two temporary KM records remain separate and untouched.
    for pk in (16, 17):
        other = KontrakManajemen.objects.get(pk=pk)
        if other.unit_bisnis_id != km.unit_bisnis_id:
            raise RuntimeError(f"STOP: KM temporary id={pk} unexpected unit.")

    masters = {
        x.kode_bagian: x
        for x in MasterBagianKM.objects.filter(template=km.template)
    }
    missing = [c for c in "ABCDEF" if c not in masters]
    if missing:
        raise RuntimeError(f"STOP: master bagian tidak lengkap: {missing}")

    items = list(
        ItemKontrakManajemen.objects
        .filter(kontrak=km)
        .select_related("master_bagian", "bagian")
        .order_by("master_bagian__urutan", "no_urut", "id")
    )

    by_id = {x.id: x for x in items}

    mapping = {}
    for row in ROWS:
        if row.no in (8, 10):
            # Signed KPIs genuinely missing from audited KM id=12.
            mapping[row.no] = None
            continue

        expected_id = KNOWN_IDS[row.no]
        item = by_id.get(expected_id)
        if item is None:
            raise RuntimeError(
                f"STOP: canonical expected item id={expected_id} for no.{row.no} tidak ditemukan."
            )

        name = norm(item.indikator_kinerja_kunci)
        tokens = NAME_TOKENS[row.no]
        if not all(norm(t) in name for t in tokens):
            raise RuntimeError(
                f"STOP: name safeguard no.{row.no} id={item.id}: "
                f"{item.indikator_kinerja_kunci!r}"
            )
        mapping[row.no] = item

    return km, masters, items, mapping


def refs_for_item(item):
    return RKMItem.objects.filter(km_item=item).count()


def preview(km, items, mapping):
    print()
    print("=" * 142)
    print("TARGET DATABASE / PREVIEW")
    print("=" * 142)
    print(
        f"KM id={km.id} | judul={km.judul!r} | unit={km.unit_bisnis} | "
        f"tahun={km.tahun} | status={km.status!r} | tanggal={km.tanggal_kontrak}"
    )
    print("Existing items:", len(items))
    print("RKM summary refs:", RKMSummary.objects.filter(kontrak_manajemen=km).count())
    print("RKM item refs   :", RKMItem.objects.filter(km_item__kontrak=km).count())

    canonical_existing_ids = {x.id for x in mapping.values() if x is not None}
    canonical_updates = 0
    field_changes = 0

    for row in ROWS:
        item = mapping[row.no]
        if item is None:
            print(
                f"CREATE {row.no:02d} | {row.section} | bobot={row.weight:<2} | "
                f"target={row.target:<14} | {row.indicator}"
            )
            canonical_updates += 1
            field_changes += 7
            continue

        desired_pol = row.polarity if row.polarity is not None else item.polaritas
        wanted = [
            ("section", getattr(item.master_bagian, "kode_bagian", None), row.section),
            ("no_urut", item.no_urut, row.no),
            ("indikator", item.indikator_kinerja_kunci, row.indicator),
            ("formula", item.formula, row.formula),
            ("satuan", item.satuan, row.unit),
            ("bobot", Decimal(str(item.bobot or 0)), row.weight),
            ("target", item.target, row.target),
            ("polaritas", item.polaritas, desired_pol),
        ]
        diffs = [(f, a, b) for f, a, b in wanted if a != b]

        print(
            f"{'UPDATE' if diffs else 'OK    '} {row.no:02d} | "
            f"id={item.id:<4} | {row.section} | {row.indicator}"
        )
        for field, before, after in diffs:
            print(f"        {field}: {before!r} -> {after!r}")

        if diffs:
            canonical_updates += 1
            field_changes += len(diffs)

    extras = [x for x in items if x.id not in canonical_existing_ids]

    print()
    print("-" * 142)
    print("EXTRA EXISTING ITEMS - DIPERTAHANKAN")
    print("-" * 142)
    for x in extras:
        print(
            f"id={x.id:<4} | section={getattr(x.master_bagian,'kode_bagian',None)} | "
            f"no={x.no_urut!s:<3} | bobot={x.bobot!s:<6} | "
            f"RKM_ref={refs_for_item(x):<3} | {x.indikator_kinerja_kunci!r}"
        )

    print()
    print("PREVIEW SUMMARY")
    print("Signed canonical KPI :", 14)
    print("Existing rows        :", len(items))
    print("Create canonical     :", 2)
    print("Update/create items  :", canonical_updates)
    print("Canonical field diff :", field_changes)
    print("Extras preserved     :", len(extras))
    print("Canonical bobot      : 100")
    print("KM id=16 touched     : NO")
    print("KM id=17 touched     : NO")
    print("Database             : BELUM DIUBAH")


def get_bagian(km, master):
    existing = (
        ItemKontrakManajemen.objects
        .filter(kontrak=km, master_bagian=master)
        .exclude(bagian=None)
        .select_related("bagian")
        .first()
    )
    if existing and existing.bagian:
        return existing.bagian

    obj, _ = BagianKontrakManajemen.objects.get_or_create(
        kontrak=km,
        kode_bagian=master.kode_bagian,
        defaults={"nama_bagian": SECTIONS[master.kode_bagian][0]},
    )
    return obj


def snapshot_rkm_links():
    return {
        x.id: (x.summary_id, x.km_item_id)
        for x in RKMItem.objects
        .filter(km_item__kontrak_id__in=[12, 16, 17])
        .order_by("id")
    }


def apply_sync(km, masters):
    backup_sqlite()

    before_links = snapshot_rkm_links()
    before_16 = list(
        ItemKontrakManajemen.objects
        .filter(kontrak_id=16)
        .values_list("id", "no_urut", "indikator_kinerja_kunci", "bobot", "target")
        .order_by("id")
    )
    before_17 = list(
        ItemKontrakManajemen.objects
        .filter(kontrak_id=17)
        .values_list("id", "no_urut", "indikator_kinerja_kunci", "bobot", "target")
        .order_by("id")
    )

    with transaction.atomic():
        locked_km = (
            KontrakManajemen.objects
            .select_for_update()
            .select_related("unit_bisnis", "template")
            .get(pk=KM_ID)
        )

        locked_items = list(
            ItemKontrakManajemen.objects
            .select_for_update()
            .filter(kontrak=locked_km)
            .select_related("master_bagian", "bagian")
            .order_by("id")
        )
        by_id = {x.id: x for x in locked_items}

        mapping = {}
        for row in ROWS:
            if row.no in (8, 10):
                mapping[row.no] = None
            else:
                mapping[row.no] = by_id[KNOWN_IDS[row.no]]

        # SAFE_RENUMBER_DESCENDING_MANPRO_V2
        # Move existing rows to their signed positions first, from highest
        # number down, before creating missing no.8 and no.10.
        for row in reversed(ROWS):
            item = mapping[row.no]
            if item is None:
                continue
            if item.no_urut != row.no:
                item.no_urut = row.no
                item.save(update_fields=["no_urut"])

        canonical_ids = []

        for row in ROWS:
            item = mapping[row.no]
            master = masters[row.section]

            if item is None:
                item = ItemKontrakManajemen(
                    kontrak=locked_km,
                    bagian=get_bagian(locked_km, master),
                    master_bagian=master,
                )

            desired_pol = row.polarity if row.polarity is not None else (item.polaritas or "positif")

            item.master_bagian = master
            if item.bagian_id is None:
                item.bagian = get_bagian(locked_km, master)
            item.no_urut = row.no
            item.indikator_kinerja_kunci = row.indicator
            item.formula = row.formula
            item.satuan = row.unit
            item.bobot = row.weight
            item.target = row.target
            item.polaritas = desired_pol

            item.full_clean()
            item.save()
            canonical_ids.append(item.id)

        locked_km.tanggal_kontrak = SIGNED_DATE
        locked_km.status = "Final"
        locked_km.full_clean()
        locked_km.save(update_fields=["tanggal_kontrak", "status"])

        # Canonical post-check.
        canonical = list(
            ItemKontrakManajemen.objects
            .filter(id__in=canonical_ids, kontrak=locked_km)
            .select_related("master_bagian")
            .order_by("no_urut", "id")
        )
        if len(canonical) != 14:
            raise RuntimeError(f"STOP: canonical count={len(canonical)}, expected=14")

        source_by_no = {r.no: r for r in ROWS}
        total = Decimal("0")
        per_section = {}

        for x in canonical:
            row = source_by_no[x.no_urut]
            if x.indikator_kinerja_kunci != row.indicator:
                raise RuntimeError(f"STOP: indicator mismatch no.{row.no}")
            if getattr(x.master_bagian, "kode_bagian", None) != row.section:
                raise RuntimeError(f"STOP: section mismatch no.{row.no}")
            if Decimal(str(x.bobot or 0)) != row.weight:
                raise RuntimeError(f"STOP: bobot mismatch no.{row.no}")
            if x.target != row.target:
                raise RuntimeError(f"STOP: target mismatch no.{row.no}")

            b = Decimal(str(x.bobot or 0))
            total += b
            per_section[row.section] = per_section.get(row.section, Decimal("0")) + b

        if total != Decimal("100"):
            raise RuntimeError(f"STOP: canonical bobot={total}, expected=100")

        for code, (_, expected) in SECTIONS.items():
            actual = per_section.get(code, Decimal("0"))
            if actual != expected:
                raise RuntimeError(
                    f"STOP: section {code} bobot={actual}, expected={expected}"
                )

        # Ensure temporary KMs and all RKM links are unchanged.
        after_16 = list(
            ItemKontrakManajemen.objects
            .filter(kontrak_id=16)
            .values_list("id", "no_urut", "indikator_kinerja_kunci", "bobot", "target")
            .order_by("id")
        )
        after_17 = list(
            ItemKontrakManajemen.objects
            .filter(kontrak_id=17)
            .values_list("id", "no_urut", "indikator_kinerja_kunci", "bobot", "target")
            .order_by("id")
        )
        after_links = snapshot_rkm_links()

        if before_16 != after_16:
            raise RuntimeError("STOP: KM id=16 berubah; rollback.")
        if before_17 != after_17:
            raise RuntimeError("STOP: KM id=17 berubah; rollback.")
        if before_links != after_links:
            raise RuntimeError("STOP: relasi RKM berubah; rollback.")

    print()
    print("=" * 142)
    print("APPLY BERHASIL - KM MANPRO 2026")
    print("=" * 142)
    print("KM id              : 12")
    print("Judul              : VPMANPRO")
    print("Canonical KPI      : 14")
    print("Canonical bobot    : 100")
    print("Tanggal kontrak    : 27-02-2026")
    print("Status             : Final")
    print("Missing KPI created: 2 (No.8 PLTS 100 MWac, No.10 IPP PLTGU Batam 3&4)")
    print("Extra rows         : dipertahankan")
    print("KM id=16           : tidak diubah")
    print("KM id=17           : tidak diubah")
    print("RKM relations      : tidak diubah")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    source_audit()
    km, masters, items, mapping = load_target()
    preview(km, items, mapping)

    if not args.apply:
        print()
        print("DRY-RUN OK: target KM id=12 tervalidasi; database belum diubah.")
        print("Jika output sesuai, jalankan ulang dengan --apply.")
        return

    apply_sync(km, masters)


if __name__ == "__main__":
    main()
