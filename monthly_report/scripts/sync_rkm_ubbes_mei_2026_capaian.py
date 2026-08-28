#!/usr/bin/env python3
"""
SYNC CAPAIAN RKM UB BES MEI 2026

Masalah yang diperbaiki:
- Import awal berhasil membuat 19 RKMItem.
- Nilai persen_capaian dari workbook sumber ditulis sebelum obj.save().
- Model RKMItem.save() menghitung ulang persen_capaian dan menghasilkan None
  karena target bulanan tidak tersedia pada sheet RKM.
- Script ini mempertahankan nilai "Capaian" sumber secara eksplisit setelah
  validasi identitas 19 item.

Default: DRY-RUN (tidak mengubah database)
Apply  : --apply

Target:
  RKMSummary id=6
  UB BES
  KM id=11
  Periode Mei 2026
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import django
from django.conf import settings
from django.db import transaction

django.setup()

from risk.models import RKMSummary, RKMItem


SUMMARY_ID = 6
UNIT_ID = 4
KM_ID = 11
YEAR = 2026
MONTH = 5

# no_item: (expected km_item_id, expected KPI token, source capaian %)
EXPECTED = {
    1:  (179, "Pendapatan penjualan listrik MPP", Decimal("41.67")),
    2:  (185, "Optimalisasi Biaya Pemeliharaan", Decimal("41.67")),
    3:  (186, "Periode Pengumpulan Piutang", Decimal("41.67")),
    4:  (193, "Equivalent Availability Factor", Decimal("41.67")),
    5:  (200, "Equivalent Forced Outage Rate", Decimal("41.67")),
    6:  (203, "Optimalisasi Kesiapan pasokan Pembangkit MPP", Decimal("41.67")),
    7:  (367, "Implementasi Roadmap Perbaikan Penerapan Manajemen Risiko", Decimal("0.00")),
    8:  (165, "Penyelesaian Program Improvement K3L", Decimal("0.00")),
    9:  (213, "Sinergi antar Subholding", Decimal("0.00")),
    10: (217, "Indeks Kepuasan Pelanggan", Decimal("8.33")),
    11: (220, "Tata Kelola Pembangkit", Decimal("0.00")),
    12: (368, "Penyerapan Investasi", Decimal("0.00")),
    13: (225, "Pengendalian Penggunaan Anggaran Investasi", Decimal("41.67")),
    14: (369, "Ketepatan Waktu Pengadaaan Investasi", Decimal("0.00")),
    15: (167, "Implementasi Peningkatan Penggunaan Produk Dalam Negeri", Decimal("0.00")),
    16: (370, "Human Capital Readiness", Decimal("8.33")),
    17: (371, "Nihil Kecelakaan", Decimal("0.00")),
    18: (228, "Penyelesaian Program Improvement K3L", Decimal("41.67")),
    19: (229, "Compliance", None),
}


def backup_sqlite():
    engine = settings.DATABASES["default"].get("ENGINE", "")
    if "sqlite" not in engine:
        print("BACKUP DB: dilewati (database bukan SQLite)")
        return None

    src = Path(settings.DATABASES["default"]["NAME"]).resolve()
    dst_dir = Path("/home/adminsvr/backup")
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"db_before_sync_rkm_ubbes_capaian_{datetime.now():%Y%m%d_%H%M%S}.sqlite3"

    with sqlite3.connect(src) as source:
        with sqlite3.connect(dst) as target:
            source.backup(target)

    with sqlite3.connect(dst) as con:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]

    print("BACKUP    :", dst)
    print("INTEGRITY :", integrity)
    if integrity != "ok":
        raise RuntimeError("Backup SQLite gagal integrity_check")

    return dst


def validate():
    summary = RKMSummary.objects.select_related("unit_bisnis", "kontrak_manajemen").get(pk=SUMMARY_ID)

    if summary.unit_bisnis_id != UNIT_ID:
        raise RuntimeError(f"STOP: unit summary={summary.unit_bisnis_id}, expected={UNIT_ID}")
    if summary.kontrak_manajemen_id != KM_ID:
        raise RuntimeError(f"STOP: KM summary={summary.kontrak_manajemen_id}, expected={KM_ID}")
    if summary.tahun != YEAR or summary.bulan != MONTH:
        raise RuntimeError(
            f"STOP: periode summary={summary.bulan}/{summary.tahun}, expected={MONTH}/{YEAR}"
        )

    items = list(
        RKMItem.objects.filter(summary=summary)
        .select_related("km_item")
        .order_by("no_item", "pk")
    )

    if len(items) != 19:
        raise RuntimeError(f"STOP: jumlah item={len(items)}, expected=19")

    actual_nos = [x.no_item for x in items]
    if actual_nos != list(range(1, 20)):
        raise RuntimeError(f"STOP: no_item bukan 1..19: {actual_nos}")

    for item in items:
        expected_km, token, _ = EXPECTED[item.no_item]

        if item.km_item_id != expected_km:
            raise RuntimeError(
                f"STOP: item {item.no_item} km_item={item.km_item_id}, expected={expected_km}"
            )

        indicator = item.kpi_indikator or ""
        if token.lower() not in indicator.lower():
            raise RuntimeError(
                f"STOP: item {item.no_item} KPI mismatch: {indicator!r}; token={token!r}"
            )

    return summary, items


def show(items, title):
    print("=" * 125)
    print(title)
    print("=" * 125)
    for item in items:
        expected = EXPECTED[item.no_item][2]
        print(
            f"{item.no_item:02d} | "
            f"RKM_ITEM={item.pk:<4} | "
            f"KM_ITEM={item.km_item_id:<4} | "
            f"DB={str(item.persen_capaian):<8} | "
            f"SOURCE={str(expected):<8} | "
            f"{item.kpi_indikator}"
        )
    print("-" * 125)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    summary, items = validate()

    print("RKM   :", summary.pk, summary.judul)
    print("Unit  :", summary.unit_bisnis.name)
    print("KM    :", summary.kontrak_manajemen_id)
    print("Status:", summary.status, "/", summary.status_pengajuan)
    print("Items :", len(items))
    print()

    show(items, "BEFORE / SOURCE CHECK")

    changes = sum(
        1 for item in items
        if item.persen_capaian != EXPECTED[item.no_item][2]
    )
    print("WOULD CHANGE:", changes, "item")

    if not args.apply:
        print()
        print("DRY-RUN OK: database belum diubah.")
        print("Jika sesuai, jalankan ulang dengan --apply.")
        return

    backup_sqlite()

    with transaction.atomic():
        locked = list(
            RKMItem.objects.select_for_update()
            .filter(summary_id=SUMMARY_ID)
            .order_by("no_item", "pk")
        )

        if len(locked) != 19:
            raise RuntimeError("STOP: jumlah item berubah saat transaction lock.")

        for item in locked:
            expected = EXPECTED[item.no_item][2]
            # QuerySet.update() sengaja dipakai agar nilai sumber tidak dihitung
            # ulang oleh RKMItem.save().
            RKMItem.objects.filter(pk=item.pk).update(
                persen_capaian=expected
            )

    _, after = validate()
    show(after, "AFTER APPLY")

    for item in after:
        expected = EXPECTED[item.no_item][2]
        if item.persen_capaian != expected:
            raise RuntimeError(
                f"STOP: post-check item {item.no_item}: "
                f"DB={item.persen_capaian}, source={expected}"
            )

    print("APPLY BERHASIL: persen_capaian 19/19 sesuai sumber.")


if __name__ == "__main__":
    main()
