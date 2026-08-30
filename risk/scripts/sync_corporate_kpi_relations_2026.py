#!/usr/bin/env python3

import argparse
import os
import shutil
import sys
from datetime import datetime
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

from risk.models import (
    ItemKontrakManajemen,
    ProfilRisikoKorporatItem,
    ProfilRisikoKorporatKinerja,
)


YEAR = 2026
KM_TITLE = "KM Korporat 2026"


MAPPING = {
    1:  [1, 3],
    2:  [3, 4, 8],
    3:  [1, 3],
    4:  [6],
    5:  [4],
    6:  [4],
    7:  [4, 8],
    8:  [2, 4],
    9:  [2, 4],
    10: [1, 2],
    11: [4, 10],
    12: [5],
    13: [9],
    14: [9],
    15: [1],
}


NOTES = {
    1: "Likuiditas berdampak pada EBIT dan pendapatan penjualan.",
    2: "Demand berdampak pada penjualan, reliabilitas, dan kesiapan proyek.",
    3: "Tarif keekonomian berdampak pada EBIT dan pendapatan penjualan.",
    4: "Pendapatan off-grid terkait pendapatan inovatif/non-reguler.",
    5: "Blackout/pemadaman premium berdampak langsung pada reliabilitas.",
    6: "Risiko iklim dapat memengaruhi reliabilitas sistem.",
    7: "Reserve margin terkait reliabilitas dan penyelesaian proyek sistem.",
    8: "Gangguan MPP berdampak pada efisiensi pembangkitan dan reliabilitas.",
    9: "Pasokan energi primer berdampak pada efisiensi biaya dan reliabilitas.",
    10: "Harga energi primer berdampak pada EBIT dan efisiensi biaya.",
    11: "Cyber berdampak pada reliabilitas layanan serta compliance/critical event.",
    12: "Risiko ESG terkait pencapaian SDGs.",
    13: "Organisasi/SDM terkait Human Capital dan Safety Culture.",
    14: "Kecelakaan kerja terkait Human Capital dan Safety Culture.",
    15: "Risiko nilai tukar berdampak pada EBIT.",
}


def normalize_risk_no(obj):
    raw = str(
        obj.no_risiko
        or obj.no_item
        or ""
    ).strip().upper()

    if raw.startswith("R"):
        raw = raw[1:]

    try:
        return int(raw)
    except Exception:
        return None


def master_data():
    corporate = list(
        ProfilRisikoKorporatItem.objects
        .filter(summary__tahun=YEAR)
        .select_related("summary")
        .order_by("no_item", "pk")
    )

    by_risk = {}

    for obj in corporate:
        no = normalize_risk_no(obj)

        if no is None:
            continue

        if no in by_risk:
            raise RuntimeError(
                f"STOP: risiko korporat R{no} duplikat."
            )

        by_risk[no] = obj

    expected_risks = set(range(1, 16))

    if set(by_risk) != expected_risks:
        raise RuntimeError(
            "STOP: Risiko Korporat 2026 tidak tepat R1-R15. "
            f"Found={sorted(by_risk)}"
        )

    items = list(
        ItemKontrakManajemen.objects
        .filter(
            kontrak__tahun=YEAR,
            kontrak__judul=KM_TITLE,
            kontrak__unit_bisnis__name__iexact="KORPORAT",
        )
        .select_related(
            "kontrak",
            "kontrak__unit_bisnis",
        )
        .order_by("no_urut")
    )

    by_ikk = {x.no_urut: x for x in items}

    if set(by_ikk) != set(range(1, 11)):
        raise RuntimeError(
            "STOP: IKK Korporat tidak tepat 1-10. "
            f"Found={sorted(by_ikk)}"
        )

    return by_risk, by_ikk


def backup_sqlite():
    db = settings.DATABASES["default"]

    if "sqlite3" not in db["ENGINE"]:
        print(
            "BACKUP: SKIP "
            f"(engine={db['ENGINE']})"
        )
        return

    source = Path(db["NAME"])

    backup_dir = ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    target = backup_dir / (
        "db_before_corporate_kpi_relations_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".sqlite3"
    )

    shutil.copy2(source, target)

    print("BACKUP SQLITE:", target)


def run(apply=False):
    by_risk, by_ikk = master_data()

    desired = []

    print("=" * 130)
    print("CORPORATE RISK <-> IKK MAPPING 2026")
    print("=" * 130)

    for risk_no in range(1, 16):
        corporate = by_risk[risk_no]

        for ikk_no in MAPPING[risk_no]:
            item = by_ikk[ikk_no]

            desired.append(
                (
                    corporate,
                    item,
                    NOTES[risk_no],
                )
            )

            print(
                f"R{risk_no:<2} -> "
                f"IKK {ikk_no:02} | "
                f"{item.indikator_kinerja_kunci}"
            )

    print("-" * 130)
    print("RISIKO KORPORAT :", len(by_risk))
    print("IKK KORPORAT    :", len(by_ikk))
    print("RELASI TARGET   :", len(desired))

    if len(desired) != 24:
        raise RuntimeError(
            f"STOP: target relation={len(desired)}, expected=24"
        )

    desired_pairs = {
        (corp.pk, item.pk)
        for corp, item, _note in desired
    }

    existing = list(
        ProfilRisikoKorporatKinerja.objects
        .filter(
            risiko_korporat__summary__tahun=YEAR
        )
        .select_related(
            "risiko_korporat",
            "item_kinerja",
        )
    )

    existing_pairs = {
        (
            x.risiko_korporat_id,
            x.item_kinerja_id,
        )
        for x in existing
    }

    missing = desired_pairs - existing_pairs
    extra = existing_pairs - desired_pairs

    print()
    print("EXISTING :", len(existing_pairs))
    print("MISSING  :", len(missing))
    print("EXTRA    :", len(extra))

    if extra:
        print(
            "WARNING: ada relasi existing di luar "
            "mapping canonical. Script tidak menghapusnya."
        )

    if not apply:
        print()
        print("DRY-RUN: DATABASE TIDAK DIUBAH")
        return

    backup_sqlite()

    with transaction.atomic():
        created = 0

        for corporate, item, note in desired:
            obj, was_created = (
                ProfilRisikoKorporatKinerja.objects
                .get_or_create(
                    risiko_korporat=corporate,
                    item_kinerja=item,
                    defaults={
                        "keterangan": note,
                    },
                )
            )

            if was_created:
                obj.full_clean()
                created += 1

        final_pairs = set(
            ProfilRisikoKorporatKinerja.objects
            .filter(
                risiko_korporat__summary__tahun=YEAR
            )
            .values_list(
                "risiko_korporat_id",
                "item_kinerja_id",
            )
        )

        missing_after = desired_pairs - final_pairs

        if missing_after:
            raise RuntimeError(
                "STOP: masih ada mapping yang belum terbentuk: "
                f"{missing_after}"
            )

    print()
    print("=" * 130)
    print("APPLY BERHASIL")
    print("=" * 130)
    print("CREATED          :", created)
    print("TARGET CANONICAL :", len(desired_pairs))
    print("MISSING AFTER    : 0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
    )

    args = parser.parse_args()

    run(apply=args.apply)
