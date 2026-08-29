#!/usr/bin/env python3
"""
Synchronize signed Kontrak Manajemen SM UBBES 2026 into ERM.

Source:
  KM SM UBBES 2026.pdf
  Signed contract date: 27 February 2026
  Unit: UB BES / Senior Manager Unit Bisnis Bright Energy Service
  Canonical KPI count: 17
  Canonical weighted total: 100
  Compliance: penalty KPI, weight 0 / "Nilai Pengurang"

IMPORTANT
---------
This script is intentionally conservative because RKM UB BES Mei 2026 was
already imported before the signed KM was synchronized.

Default mode = DRY-RUN:
    python risk/scripts/sync_km_sm_ubbes_2026_signed.py

Apply:
    python risk/scripts/sync_km_sm_ubbes_2026_signed.py --apply

Safety rules:
- Target only KontrakManajemen id=11 / SMUBBES / UB BES / 2026.
- Reuse the 16 known canonical KM items already present in production.
- Create only the missing signed KPI no.14 (ICOFR), if still absent.
- Do NOT delete/overwrite technical zero-weight KM bridge rows used by the
  already-imported RKM UB BES Mei 2026.
- Do NOT modify RKM data.
- Preserve Compliance polarity because the signed PDF shows it as a penalty
  ("Nilai Pengurang", Max -10) but does not show a polarity arrow.
- Back up SQLite before APPLY.
"""

from __future__ import annotations

import argparse
import os
import shutil
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

try:
    from risk.models import ReAssessmentItem
except Exception:
    ReAssessmentItem = None

try:
    from monthly_report.models import MonthlyRiskReportItem
except Exception:
    MonthlyRiskReportItem = None


KM_ID = 11
UNIT_ID = 4
YEAR = 2026
EXPECTED_TITLE = "SMUBBES"
EXPECTED_UNIT = "UB BES"
SIGNED_DATE = date(2026, 2, 27)

SECTIONS = {
    "A": "Nilai Ekonomi dan Sosial Untuk Indonesia",
    "B": "Inovasi Model Bisnis",
    "C": "Kepemimpinan Teknologi",
    "D": "Peningkatan Investasi",
    "E": "Pengembangan Talenta",
    "F": "Kepatuhan",
}

# 16 canonical rows already known in production from prior audit.
KNOWN_IDS = {
    1: 179,
    2: 185,
    3: 186,
    4: 193,
    5: 200,
    6: 203,
    7: 207,
    8: 210,
    9: 213,
    10: 217,
    11: 220,
    12: 222,
    13: 225,
    15: 227,
    16: 228,
    17: 229,
}

COMPLIANCE_FORMULA = """Jumlah nilai pengurang dari unsur:
- Maturity Level GCG
- Kepatuhan pengelolaan HSSE
- Tindak lanjut temuan SPI, BPK, dan Auditor lainnya
- Keterlambatan Laporan Kinerja (termasuk laporan manajemen risiko)
- Pengendalian Nilai Non Allowable Cost/NAC sesuai RKAP 2026
- Planning Accuracy Compliance Adjustment (PACA)"""

HC_FORMULA = """Rata-rata Pencapaian:
1. Produktivitas Pegawai dan Penguatan Budaya
2. Pengelolaan Human Capital Services"""

SMT_FORMULA = """Prosentase Rata-rata Waktu Pemenuhan Eviden di tanggal 30 September 2026:
1. Maturity ISO 45001 Sistem Manajemen Keselamatan dan Kesehatan Kerja (K3) Level 3
2. Maturity PERMEN ESDM 10/2021 Sistem Manajemen Keselamatan Ketenagalistrikan (SMK2) Level 3
3. Maturity Sistem Manajemen Aset 55001 Level 2"""

ICOFR_FORMULA = """Jumlah defisiensi yang sudah ditindaklanjuti di UB BES x 100%
Jumlah defisiensi yang harus ditindaklanjuti di UB BES"""


@dataclass(frozen=True)
class SourceRow:
    no: int
    section: str
    indicator: str
    formula: str
    unit: str
    weight: Decimal
    target: str
    polarity: str | None


ROWS = [
    SourceRow(1, "A", "Pendapatan Penjualan Listrik MPP",
              "Jumlah Pendapatan Penjualan Listrik MPP (Non ISAK)",
              "Rp. Miliar", Decimal("7"), "1.718,13", "positif"),
    SourceRow(2, "A", "Optimalisasi Biaya Pemeliharaan",
              "Realisasi Optimalisasi Biaya Pemeliharaan",
              "%", Decimal("6"), "95 - 100", "positif"),
    SourceRow(3, "A", "Periode Pengumpulan Piutang (Collection Period)",
              "(Rata-rata Saldo Piutang Tagihan MPP / ∑Penjualan MPP) x ∑Hari",
              "Hari", Decimal("6"), "85", "negatif"),
    SourceRow(4, "A", "EAF MPP",
              "∑ (AH - EPDH - EUDH - ESDH) x DMN x 100% / ∑(PH x DMN)",
              "%", Decimal("9"), "89,56", "positif"),
    SourceRow(5, "A", "EFOR MPP",
              "{(FOH + EFDH) x DMN / (FOH + SH + EFDHRS) x DMN} x 100%",
              "%", Decimal("9"), "15,19", "negatif"),
    SourceRow(6, "A", "Optimalisasi Kesiapan Pasokan Pembangkit MPP",
              "∑ Daya Mampu Pasok / Daya Mampu Netto x rata-rata tertimbang DMN x 100%",
              "%", Decimal("9"), "87,35", "positif"),
    SourceRow(7, "A", "Maturity Level Sustainability",
              "Hasil Asesmen Maturity Level Sustainability",
              "%", Decimal("6"), "100", "positif"),
    SourceRow(8, "A", "Kualitas Penerapan Manajemen Risiko (KPMR)",
              "Penerapan Manajemen Risiko (KPMR) di UB BES",
              "Skor", Decimal("6"), "80", "positif"),

    SourceRow(9, "B", "Sinergi antar Subholding, Anak Perusahaan Lain & Pusharlis",
              "∑ Transaksi antara Subholding, Anak Perusahaan Lain dan Pusharlis",
              "Rp Miliar", Decimal("5"), "139,44", "positif"),

    SourceRow(10, "C", "Indeks Kepuasan Pelanggan",
              "Rata-rata Hasil Survey Kepuasan Pelanggan di Seluruh Site MPP",
              "%", Decimal("6"), "94,76", "positif"),
    SourceRow(11, "C", "Tata Kelola Pembangkit",
              "Maturity Level Tata Kelola Aset Manajemen di Pembangkit MPP",
              "Level", Decimal("6"), "2,91", "positif"),
    SourceRow(12, "C", "Implementasi Sistem Manajemen Terintegrasi",
              SMT_FORMULA,
              "%", Decimal("5"), "100", "positif"),

    SourceRow(13, "D", "Pengendalian Penggunaan Anggaran Investasi sesuai RKAP 2026",
              "Kesesuaian Realisasi Anggaran Investasi dengan Pos Anggaran Investasi Sesuai Peruntukannya",
              "%", Decimal("5"), "95 - 100", "positif"),
    SourceRow(14, "D", "Penyelesaian Tindak Lanjut defisiensi ICOFR tahun 2025",
              ICOFR_FORMULA,
              "%", Decimal("4"), "50", "positif"),

    SourceRow(15, "E", "Pengelolaan Human Capital",
              HC_FORMULA,
              "%", Decimal("6"), "100", "positif"),
    SourceRow(16, "E", "Penyelesaian Program Improvement K3L",
              "Penyelesaian Program Improvement K3L sesuai Target x 100 %",
              "%", Decimal("5"), "100", "positif"),

    # Signed source has no polarity arrow on Compliance; preserve DB polarity.
    SourceRow(17, "F", "Compliance",
              COMPLIANCE_FORMULA,
              "Nilai Pengurang", Decimal("0"), "Max -10", None),
]

EXPECTED_SECTION_WEIGHTS = {
    "A": Decimal("58"),
    "B": Decimal("5"),
    "C": Decimal("17"),
    "D": Decimal("9"),
    "E": Decimal("11"),
    "F": Decimal("0"),
}


def norm(value) -> str:
    import re
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def backup_sqlite():
    engine = settings.DATABASES["default"].get("ENGINE", "")
    if "sqlite" not in engine:
        print("BACKUP DB: skipped; default DB is not SQLite.")
        return None

    src = Path(settings.DATABASES["default"]["NAME"]).resolve()
    dst_dir = Path("/home/adminsvr/backup")
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"db_before_sync_km_sm_ubbes_2026_{datetime.now():%Y%m%d_%H%M%S}.sqlite3"

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
    print("=" * 138)
    print("SOURCE AUDIT - SIGNED KM SM UBBES 2026")
    print("=" * 138)
    print("Tanggal kontrak : 27 Februari 2026")
    print("Pihak pertama   : Direktur Pembina Direktorat Operasi / Dinda Alamsyah")
    print("Pihak kedua     : Senior Manager Unit Bisnis Bright Energy Service / Agus Wibowo")
    print("Jumlah KPI      :", len(ROWS))
    print()

    sums = {}
    for row in ROWS:
        sums[row.section] = sums.get(row.section, Decimal("0")) + row.weight
        print(
            f"{row.no:02d} | {row.section} | bobot={row.weight:<2} | "
            f"target={row.target:<10} | {row.indicator}"
        )

    print("-" * 138)
    for code in "ABCDEF":
        actual = sums.get(code, Decimal("0"))
        expected = EXPECTED_SECTION_WEIGHTS[code]
        print(f"Bagian {code}: {actual} / expected {expected}")
        if actual != expected:
            raise RuntimeError(f"STOP: bobot source bagian {code} mismatch.")

    weighted_total = sum(sums.values(), Decimal("0"))
    print("TOTAL BOBOT:", weighted_total)
    if weighted_total != Decimal("100"):
        raise RuntimeError("STOP: total bobot source bukan 100.")


def resolve_target():
    km = (
        KontrakManajemen.objects
        .select_related("unit_bisnis", "template")
        .get(pk=KM_ID)
    )

    if km.judul != EXPECTED_TITLE:
        raise RuntimeError(f"STOP: KM id={KM_ID} judul={km.judul!r}, expected={EXPECTED_TITLE!r}")
    if km.tahun != YEAR:
        raise RuntimeError(f"STOP: KM id={KM_ID} tahun={km.tahun}, expected={YEAR}")
    if km.unit_bisnis_id != UNIT_ID or str(km.unit_bisnis) != EXPECTED_UNIT:
        raise RuntimeError(
            f"STOP: KM id={KM_ID} unit={km.unit_bisnis_id}/{km.unit_bisnis}, "
            f"expected={UNIT_ID}/{EXPECTED_UNIT}"
        )
    if not km.template_id:
        raise RuntimeError("STOP: KM SMUBBES tidak memiliki template.")

    masters = {
        x.kode_bagian: x
        for x in MasterBagianKM.objects.filter(template=km.template)
    }
    missing = [x for x in "ABCDEF" if x not in masters]
    if missing:
        raise RuntimeError(f"STOP: master bagian template tidak lengkap: {missing}")

    existing = list(
        ItemKontrakManajemen.objects
        .filter(kontrak=km)
        .select_related("master_bagian", "bagian")
        .order_by("master_bagian__urutan", "no_urut", "id")
    )

    return km, masters, existing


def count_refs(item):
    rkm = RKMItem.objects.filter(km_item=item).count()
    profile = (
        ReAssessmentItem.objects.filter(km_item=item).count()
        if ReAssessmentItem is not None else None
    )
    monthly = (
        MonthlyRiskReportItem.objects.filter(km_item=item).count()
        if MonthlyRiskReportItem is not None else None
    )
    return rkm, profile, monthly


def canonical_mapping(km, existing):
    by_id = {x.pk: x for x in existing}
    result = {}

    for row in ROWS:
        if row.no == 14:
            candidates = [
                x for x in existing
                if "defisiensi icofr" in norm(x.indikator_kinerja_kunci)
                and "2025" in norm(x.indikator_kinerja_kunci)
            ]
            if len(candidates) > 1:
                raise RuntimeError(
                    "STOP: kandidat KPI ICOFR ambigu: "
                    + ", ".join(str(x.pk) for x in candidates)
                )
            result[row.no] = candidates[0] if candidates else None
            continue

        expected_id = KNOWN_IDS[row.no]
        item = by_id.get(expected_id)
        if item is None:
            raise RuntimeError(
                f"STOP: canonical existing KPI no.{row.no} id={expected_id} tidak ditemukan."
            )

        # Name safeguards: allow known abbreviations for EAF/EFOR and Compliance.
        name = norm(item.indikator_kinerja_kunci)
        if row.no == 4:
            ok = "eaf mpp" in name
        elif row.no == 5:
            ok = "efor mpp" in name
        elif row.no == 12:
            # Existing DB memiliki typo legacy:
            # "Implementasi Sistem Manajemen Terintegritas"
            # Signed KM 2026 yang benar:
            # "Implementasi Sistem Manajemen Terintegrasi"
            ok = (
                "implementasi sistem manajemen terintegrasi" in name
                or "implementasi sistem manajemen terintegritas" in name
            )
        elif row.no == 17:
            ok = name.startswith("compliance")
        else:
            token = norm(row.indicator)
            ok = token == name or token in name or name in token

        if not ok:
            raise RuntimeError(
                f"STOP: ID safeguard gagal no.{row.no} id={item.pk}: "
                f"DB={item.indikator_kinerja_kunci!r} SOURCE={row.indicator!r}"
            )
        result[row.no] = item

    return result


def preview(km, existing, mapping):
    print()
    print("=" * 138)
    print("TARGET DATABASE / PREVIEW")
    print("=" * 138)
    print(
        f"KM id={km.pk} | judul={km.judul!r} | unit={km.unit_bisnis} | "
        f"tahun={km.tahun} | status={km.status!r} | existing_items={len(existing)}"
    )
    print("tanggal_kontrak DB:", getattr(km, "tanggal_kontrak", None))
    print()

    canonical_ids = set()
    change_items = 0
    change_fields = 0

    for row in ROWS:
        item = mapping[row.no]
        if item is None:
            print(
                f"CREATE {row.no:02d} | {row.section} | "
                f"{row.indicator} | bobot={row.weight} | target={row.target}"
            )
            change_items += 1
            change_fields += 7
            continue

        canonical_ids.add(item.pk)
        desired_polarity = row.polarity if row.polarity is not None else item.polaritas
        wanted = {
            "master_bagian": row.section,
            "no_urut": row.no,
            "indikator_kinerja_kunci": row.indicator,
            "formula": row.formula,
            "satuan": row.unit,
            "bobot": float(row.weight),
            "target": row.target,
            "polaritas": desired_polarity,
        }

        diffs = []
        for field, desired in wanted.items():
            if field == "master_bagian":
                current = getattr(item.master_bagian, "kode_bagian", None)
            else:
                current = getattr(item, field)
            if field == "bobot":
                same = Decimal(str(current or 0)) == Decimal(str(desired))
            else:
                same = current == desired
            if not same:
                diffs.append((field, current, desired))

        if diffs:
            change_items += 1
            change_fields += len(diffs)

        print(
            f"{'UPDATE' if diffs else 'OK    '} {row.no:02d} | "
            f"id={item.pk:<4} | {row.section} | {row.indicator}"
        )
        for field, before, after in diffs:
            print(f"        {field}: {before!r} -> {after!r}")

    extras = [x for x in existing if x.pk not in canonical_ids]
    print()
    print("-" * 138)
    print("EXTRA / TECHNICAL KM ITEMS - AKAN DIPERTAHANKAN")
    print("-" * 138)
    for x in extras:
        rkm_ref, profile_ref, monthly_ref = count_refs(x)
        print(
            f"id={x.pk:<4} | bagian={getattr(x.master_bagian,'kode_bagian',None)} "
            f"| no={x.no_urut:<3} | bobot={x.bobot} "
            f"| RKM_ref={rkm_ref} | profile_ref={profile_ref} | monthly_ref={monthly_ref} "
            f"| {x.indikator_kinerja_kunci!r}"
        )

    print()
    print("PREVIEW SUMMARY")
    print("Signed canonical KPI :", len(ROWS))
    print("Existing KM rows      :", len(existing))
    print("Canonical update/create:", change_items)
    print("Canonical field changes:", change_fields)
    print("Extra rows preserved  :", len(extras))
    print("RKM UB BES Mei 2026   :", RKMItem.objects.filter(summary_id=6).count(), "item")
    print("Database              : BELUM DIUBAH")

    return extras


def get_part_for_section(km, section_code, master):
    existing = (
        ItemKontrakManajemen.objects
        .filter(kontrak=km, master_bagian=master)
        .exclude(bagian=None)
        .select_related("bagian")
        .first()
    )
    if existing and existing.bagian:
        return existing.bagian

    part, _ = BagianKontrakManajemen.objects.get_or_create(
        kontrak=km,
        kode_bagian=section_code,
        defaults={"nama_bagian": SECTIONS[section_code]},
    )
    return part


def apply_sync(km, masters, mapping):
    backup_sqlite()

    with transaction.atomic():
        km = (
            KontrakManajemen.objects
            .select_for_update()
            .select_related("unit_bisnis", "template")
            .get(pk=KM_ID)
        )

        current_existing = list(
            ItemKontrakManajemen.objects
            .select_for_update()
            .filter(kontrak=km)
            .select_related("master_bagian", "bagian")
            .order_by("master_bagian__urutan", "no_urut", "id")
        )
        current_map = canonical_mapping(km, current_existing)

        before_rkm_links = {
            x.pk: x.km_item_id
            for x in RKMItem.objects.filter(summary_id=6).order_by("pk")
        }

        canonical_ids = []

        # SAFE_RENUMBER_DESCENDING_V2
        # Simpan dari nomor terbesar ke terkecil agar perubahan
        # 14->15, 15->16, 16->17 tidak melanggar unique constraint
        # (kontrak, master_bagian, no_urut).
        for row in reversed(ROWS):
            item = current_map[row.no]
            master = masters[row.section]

            if item is None:
                item = ItemKontrakManajemen(
                    kontrak=km,
                    bagian=get_part_for_section(km, row.section, master),
                    master_bagian=master,
                )

            desired_polarity = row.polarity if row.polarity is not None else (item.polaritas or "positif")

            item.master_bagian = master
            if item.bagian_id is None:
                item.bagian = get_part_for_section(km, row.section, master)
            item.no_urut = row.no
            item.indikator_kinerja_kunci = row.indicator
            item.formula = row.formula
            item.satuan = row.unit
            item.bobot = row.weight
            item.target = row.target
            item.polaritas = desired_polarity

            item.full_clean()
            item.save()
            canonical_ids.append(item.pk)

        km.tanggal_kontrak = SIGNED_DATE
        km.status = "Final"
        km.full_clean()
        km.save(update_fields=["tanggal_kontrak", "status"])

        after_rkm_links = {
            x.pk: x.km_item_id
            for x in RKMItem.objects.filter(summary_id=6).order_by("pk")
        }
        if before_rkm_links != after_rkm_links:
            raise RuntimeError("STOP: relasi RKM UB BES Mei 2026 berubah; transaction dibatalkan.")

        # Verify canonical 17 only, while allowing preserved technical bridge rows.
        canonical = list(
            ItemKontrakManajemen.objects
            .filter(pk__in=canonical_ids, kontrak=km)
            .select_related("master_bagian")
            .order_by("no_urut", "pk")
        )
        if len(canonical) != 17:
            raise RuntimeError(f"STOP: canonical KPI count={len(canonical)}, expected=17.")

        source_by_no = {x.no: x for x in ROWS}
        total = Decimal("0")
        section_sum = {}

        for item in canonical:
            row = source_by_no[item.no_urut]
            if item.master_bagian.kode_bagian != row.section:
                raise RuntimeError(f"STOP: section mismatch no.{row.no}")
            if item.indikator_kinerja_kunci != row.indicator:
                raise RuntimeError(f"STOP: indicator mismatch no.{row.no}")
            if Decimal(str(item.bobot or 0)) != row.weight:
                raise RuntimeError(f"STOP: bobot mismatch no.{row.no}")
            if item.target != row.target:
                raise RuntimeError(f"STOP: target mismatch no.{row.no}")

            total += Decimal(str(item.bobot or 0))
            section_sum[row.section] = section_sum.get(row.section, Decimal("0")) + Decimal(str(item.bobot or 0))

        if total != Decimal("100"):
            raise RuntimeError(f"STOP: canonical total bobot={total}, expected=100")

        for code, expected in EXPECTED_SECTION_WEIGHTS.items():
            actual = section_sum.get(code, Decimal("0"))
            if actual != expected:
                raise RuntimeError(
                    f"STOP: canonical bobot bagian {code}={actual}, expected={expected}"
                )

        if RKMItem.objects.filter(summary_id=6).count() != 19:
            raise RuntimeError("STOP: jumlah RKM UB BES Mei 2026 berubah dari 19.")

    print()
    print("=" * 138)
    print("APPLY BERHASIL - KM SM UBBES 2026")
    print("=" * 138)
    print("KM id              :", KM_ID)
    print("Canonical KPI      : 17")
    print("Canonical bobot    : 100")
    print("Tanggal kontrak    : 27-02-2026")
    print("Status             : Final")
    print("RKM Mei id=6       : 19 item, relasi km_item tidak berubah")
    print("Technical bridge   : dipertahankan, bobot 0 / tidak dihapus")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    source_audit()
    km, masters, existing = resolve_target()
    mapping = canonical_mapping(km, existing)
    preview(km, existing, mapping)

    if not args.apply:
        print()
        print("DRY-RUN OK: signed KM 17 KPI tervalidasi; database belum diubah.")
        print("Kirim output dry-run untuk review sebelum menjalankan --apply.")
        return

    apply_sync(km, masters, mapping)


if __name__ == "__main__":
    main()
