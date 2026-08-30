#!/usr/bin/env python3

import argparse
import os
import shutil
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "riskproject.settings.prod",
)

django.setup()

from django.conf import settings
from django.db import transaction

from risk.km_scoring import calculate_km_score
from risk.models import (
    ItemKontrakManajemen,
    KontrakManajemen,
    RKMItem,
    RKMSummary,
)
from risk.views import _kontrak_manajemen_detail


YEAR = 2026
MONTH = 7
EXPECTED_NKO = Decimal("102.88")

ROWS = {
    1:  ("541.34",  "702.74",  Decimal("13.20")),
    2:  ("100",     "94.70",   Decimal("11.36")),
    3:  ("4430.99", "4231.30", Decimal("9.54")),
    4:  ("100",     "107.15",  Decimal("17.14")),
    5:  ("100",     "104.38",  Decimal("10.43")),
    6:  ("100",     "110.00",  Decimal("11.00")),
    7:  ("3.35",    "3.38",    Decimal("9.91")),
    8:  ("100",     "96.49",   Decimal("9.64")),
    9:  ("100",     "106.69",  Decimal("10.66")),
    10: (None,      "0",       Decimal("0.00")),
}


def D(value):
    if value in (None, ""):
        return None
    return Decimal(str(value))


def get_master():
    km = (
        KontrakManajemen.objects
        .select_related("unit_bisnis")
        .get(
            tahun=YEAR,
            judul="KM Korporat 2026",
            unit_bisnis__name__iexact="KORPORAT",
        )
    )

    items = list(
        ItemKontrakManajemen.objects
        .filter(kontrak=km)
        .select_related(
            "master_bagian",
            "kontrak",
            "kontrak__unit_bisnis",
        )
        .order_by("no_urut")
    )

    if len(items) != 10:
        raise RuntimeError(
            f"STOP: jumlah IKK Korporat={len(items)}, expected=10"
        )

    by_no = {x.no_urut: x for x in items}

    if set(by_no) != set(range(1, 11)):
        raise RuntimeError(
            f"STOP: nomor IKK={sorted(by_no)}, expected 1..10"
        )

    return km, by_no


def audit_engine(items):
    print("=" * 130)
    print("AUDIT ENGINE NKO KORPORAT JULI 2026")
    print("=" * 130)

    total = Decimal("0")

    for no in range(1, 11):
        target, realisasi, expected = ROWS[no]
        item = items[no]

        achievement, score = calculate_km_score(
            item,
            D(target),
            D(realisasi),
        )

        if score != expected:
            raise RuntimeError(
                f"STOP IKK {no:02}: "
                f"score={score}, expected={expected}"
            )

        total += score

        pct = (
            achievement.quantize(Decimal("0.01"))
            if achievement is not None
            else "-"
        )

        print(
            f"IKK {no:02} | "
            f"target={str(target):<9} | "
            f"real={realisasi:<9} | "
            f"capaian={str(pct):<8} | "
            f"nilai={score}"
        )

    print("-" * 130)
    print("TOTAL ENGINE :", total)
    print("EXPECTED NKO :", EXPECTED_NKO)

    if total != EXPECTED_NKO:
        raise RuntimeError(
            f"STOP: total engine={total}, expected={EXPECTED_NKO}"
        )


def find_rkm(km):
    return (
        RKMSummary.objects
        .filter(
            tahun=YEAR,
            bulan=MONTH,
            unit_bisnis=km.unit_bisnis,
            kontrak_manajemen=km,
        )
        .first()
    )


def backup_sqlite():
    db = settings.DATABASES["default"]

    if "sqlite3" not in db["ENGINE"]:
        raise RuntimeError(
            f"STOP: importer backup hanya untuk SQLite: {db['ENGINE']}"
        )

    source = Path(db["NAME"])
    backup_dir = ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    target = backup_dir / (
        "db_before_rkm_korporat_juli_2026_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".sqlite3"
    )

    shutil.copy2(source, target)
    print("BACKUP SQLITE:", target)


def verify(km, rkm):
    count = RKMItem.objects.filter(summary=rkm).count()

    detail = _kontrak_manajemen_detail(
        km,
        YEAR,
        MONTH,
    )

    nko = D(detail.get("total_nilai"))

    print()
    print("=" * 130)
    print("POST-CHECK")
    print("=" * 130)
    print("RKM ID     :", rkm.pk)
    print("RKM STATUS :", rkm.status)
    print("RKM ITEMS  :", count)
    print("NKO SYSTEM :", nko)
    print("EXPECTED   :", EXPECTED_NKO)

    if count != 10:
        raise RuntimeError(
            f"STOP: RKM items={count}, expected=10"
        )

    if nko != EXPECTED_NKO:
        raise RuntimeError(
            f"STOP: NKO system={nko}, expected={EXPECTED_NKO}"
        )


def run(apply=False):
    km, items = get_master()

    audit_engine(items)

    existing = find_rkm(km)

    print()
    print("=" * 130)
    print("DATABASE BASELINE")
    print("=" * 130)
    print("KM :", km.pk, km.judul)

    if existing:
        print(
            "RKM: FOUND",
            existing.pk,
            existing.judul,
        )
        verify(km, existing)
        print("DATABASE TIDAK DIUBAH")
        return

    print("RKM: MISSING")

    if not apply:
        print()
        print("=" * 130)
        print("DRY-RUN RESULT")
        print("=" * 130)
        print("- create RKMSummary Korporat Juli 2026")
        print("- create 10 RKMItem")
        print("- status Final")
        print("- expected NKO 102.88")
        print("- DATABASE TIDAK DIUBAH")
        return

    backup_sqlite()

    with transaction.atomic():
        rkm = RKMSummary.objects.create(
            judul="RKM Korporat Juli 2026",
            tahun=YEAR,
            bulan=MONTH,
            unit_bisnis=km.unit_bisnis,
            kontrak_manajemen=km,
            status="Final",
        )

        for no in range(1, 11):
            km_item = items[no]
            target, realisasi, expected = ROWS[no]

            kategori = (
                km_item.master_bagian.kode_bagian
                if km_item.master_bagian_id
                else None
            )

            obj = RKMItem.objects.create(
                summary=rkm,
                no_item=no,
                km_item=km_item,
                kategori_rkm=kategori,
                sasaran=km_item.indikator_kinerja_kunci,
                kpi_indikator=km_item.indikator_kinerja_kunci,
                kpi_satuan=km_item.satuan,
                kpi_target=km_item.target,
                target_akumulasi=target,
                target_akumulasi_satuan=km_item.satuan,
                target_bulanan=target,
                target_juli=target,
                realisasi_juli=realisasi,
                keterangan="Realisasi KM Korporat s.d. Juli 2026",
            )

            print(
                f"CREATE IKK {no:02} | "
                f"RKM_ITEM={obj.pk} | "
                f"CAPAIAN={obj.persen_capaian} | "
                f"NILAI={expected}"
            )

        verify(km, rkm)

    print()
    print("=" * 130)
    print("APPLY BERHASIL")
    print("=" * 130)
    print("NKO    : 102.88")
    print("STATUS : Tercapai")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    run(apply=args.apply)
