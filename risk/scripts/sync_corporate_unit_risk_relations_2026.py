#!/usr/bin/env python
"""
Sinkronisasi mapping Risiko Korporat 2026 -> Risiko Bidang/Unit Bisnis.

Default : DRY RUN
Apply   : python risk/scripts/sync_corporate_unit_risk_relations_2026.py --apply

Prinsip:
- Tidak membuat Corporate Risk atau ReAssessmentItem baru.
- Resolver menggunakan tahun + unit + no_risiko + exact risk event.
- Berhenti bila source data tidak cocok/ambigu.
- Saat --apply, mapping R1-R15 disinkronkan secara atomic.
"""

from __future__ import annotations

import argparse
import os
import string
import sys
from pathlib import Path

import django
from django.db import transaction


BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.dev")
django.setup()


from risk.models import (  # noqa: E402
    ProfilRisikoKorporatItem,
    ProfilRisikoKorporatSumber,
    ReAssessmentItem,
)


YEAR = 2026


# corporate_no: [(unit, unit_risk_no, exact_event), ...]
MAPPING = {
    1: [
        (
            "UB BES",
            1,
            "Penurunan Likuiditas untuk pendanaan operasi dan investasi (Meningkatnya umur piutang)",
        ),
        (
            "BID KEU",
            7,
            "Arus kas operasi bulanan perusahaan negatif",
        ),
    ],
    2: [
        (
            "BID OPS",
            1,
            "Potensi demand dan kebutuhan Tenaga Listrik Pelanggan tidak dapat terpenuhi",
        ),
    ],
    3: [
        (
            "BID AGA",
            2,
            "Harga Jual rata-rata di bawah target RKAP",
        ),
        (
            "UB DISYAN",
            1,
            "Harga jual rata - rata di bawah BPP",
        ),
    ],
    4: [
        (
            "BID BIS",
            9,
            "Tidak tercapainya pendapatan dari luar PLN Group",
        ),
        (
            "UB BES",
            14,
            "Ketidakpastian Pendapatan dari Revenue Stream Offgrid",
        ),
    ],
    5: [
        (
            "UB DISYAN",
            7,
            "Terjadi gangguan penyulang",
        ),
        (
            "UB KITRAN",
            1,
            "Terjadinya pemadaman meluas dan atau blackout di sistem kelistrikan Batam - Bintan",
        ),
    ],
    6: [
        (
            "UB KITRAN",
            20,
            "Terjadi Defisit Daya Pada Sistem Batam-Bintan",
        ),
    ],
    7: [
        (
            "UB KITRAN",
            1,
            "Terjadi Defisit Daya Pada Sistem Batam-Bintan",
        ),
    ],
    8: [
        (
            "UB BES",
            15,
            "Gangguan Pembangkit MPP",
        ),
    ],
    9: [
        (
            "BID OPS",
            3,
            "Risiko Kendala pasokan Energi Primer dan peningkatan biaya energi primer yang memengaruhi keandalan operasi sistem",
        ),
    ],
    10: [
        (
            "BID OPS",
            3,
            "Risiko Kendala pasokan Energi Primer dan peningkatan biaya energi primer yang memengaruhi keandalan operasi sistem",
        ),
    ],
    11: [
        (
            "UB INFRA",
            30,
            "Terjadinya insiden keamanan siber pada sistem IT/OT yang mengganggu layanan dan berpotensi menyebabkan kebocoran data.",
        ),
    ],
    12: [
        (
            "SETPER",
            1,
            "Kendala Pemenuhan Parameter Sustainability (Enviromental, Social Governance) ESG Risk Rating",
        ),
    ],
    13: [
        (
            "BID HCGA",
            13,
            "Ketidaksiapan organisasi dan SDM dalam mendukung sasaran strategis Perusahaan",
        ),
    ],
    14: [
        (
            "SETPER",
            27,
            "Terjadinya kecelakaan kerja dalam lingkungan kerja perusahaan sehingga berpotensi mempengaruhi nilai kepatuhan K3 Perusahaan",
        ),
        (
            "UB BES",
            16,
            "Terjadinya kecelakaan kerja dalam lingkungan kerja perusahaan",
        ),
        (
            "UB INFRA",
            10,
            "Terjadi kecelakaan kerja dalam lingkungan kerja",
        ),
        (
            "UB KITRAN",
            20,
            "Terjadinya Kecelakaan Kerja",
        ),
    ],
    15: [
        (
            "BID KEU",
            5,
            "Kenaikan beban operasi akibat pelemahan nilai tukar rupiah terhadap dollar",
        ),
    ],
}


def normalized(value):
    return " ".join(str(value or "").split()).casefold()


def source_letter(index: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA."""
    if index < 1:
        raise ValueError("index harus >= 1")

    chars = []
    while index:
        index, rem = divmod(index - 1, 26)
        chars.append(string.ascii_uppercase[rem])
    return "".join(reversed(chars))


def corporate_risk(no_risiko: int):
    qs = ProfilRisikoKorporatItem.objects.filter(
        summary__tahun=YEAR,
        no_risiko=no_risiko,
    )

    if qs.count() != 1:
        raise RuntimeError(
            f"R{no_risiko}: corporate risk harus tepat 1, ditemukan {qs.count()}."
        )

    return qs.get()


def resolve_unit_risk(unit_name: str, no_risiko: int, event: str):
    qs = (
        ReAssessmentItem.objects
        .filter(
            summary__tahun=YEAR,
            summary__unit_bisnis__name=unit_name,
            no_risiko=no_risiko,
            is_active=True,
        )
        .select_related(
            "summary",
            "summary__unit_bisnis",
        )
    )

    exact = [
        row for row in qs
        if normalized(row.peristiwa_risiko) == normalized(event)
    ]

    if len(exact) != 1:
        print()
        print(
            f"ERROR SOURCE: unit={unit_name!r}, "
            f"R={no_risiko}, event={event!r}"
        )
        print(f"Candidate count exact = {len(exact)}")

        for row in qs:
            print(
                f"  RE={row.pk} | no_item={row.no_item} | "
                f"event={row.peristiwa_risiko!r}"
            )

        raise RuntimeError(
            "Source risk tidak ditemukan secara unik. "
            "Tidak aman untuk meneruskan sinkronisasi."
        )

    return exact[0]


def build_plan():
    plan = {}

    for corporate_no in range(1, 16):
        corp = corporate_risk(corporate_no)
        desired = []

        for unit_name, unit_risk_no, event in MAPPING[corporate_no]:
            source = resolve_unit_risk(
                unit_name,
                unit_risk_no,
                event,
            )
            desired.append(source)

        plan[corp] = desired

    return plan


def print_plan(plan):
    total = 0

    print("=" * 140)
    print(
        "CORPORATE -> UNIT RISK RELATIONSHIP 2026 | "
        "VALIDATION / PLAN"
    )
    print("=" * 140)

    for corp, desired in plan.items():
        print()
        print(
            f"R{corp.no_risiko:02} | "
            f"{corp.peristiwa_risiko} | "
            f"TARGET={len(desired)}"
        )

        for source in desired:
            total += 1
            print(
                f"  -> {source.summary.unit_bisnis} | "
                f"RE={source.pk} | R{source.no_risiko}"
            )
            print(f"     {source.peristiwa_risiko}")

    print()
    print("=" * 140)
    print("CORPORATE :", len(plan))
    print("RELATION  :", total)
    print("=" * 140)


def apply_plan(plan):
    created = 0
    existing = 0
    removed = 0
    updated = 0

    with transaction.atomic():
        for corp, desired in plan.items():
            desired_ids = [row.pk for row in desired]

            stale_qs = ProfilRisikoKorporatSumber.objects.filter(
                risiko_korporat=corp,
            ).exclude(
                reassessment_item_id__in=desired_ids,
            )

            stale_count = stale_qs.count()
            if stale_count:
                stale_qs.delete()
                removed += stale_count

            for index, source in enumerate(desired, start=1):
                letter = source_letter(index)

                relation, was_created = (
                    ProfilRisikoKorporatSumber.objects.get_or_create(
                        risiko_korporat=corp,
                        reassessment_item=source,
                        defaults={
                            "no_penyebab_risiko": letter,
                            "keterangan": (
                                f"Relasi Risiko Korporat R{corp.no_risiko} "
                                f"dengan risiko utama "
                                f"{source.summary.unit_bisnis}."
                            ),
                        },
                    )
                )

                if was_created:
                    created += 1
                else:
                    existing += 1

                changed = False

                if relation.no_penyebab_risiko != letter:
                    relation.no_penyebab_risiko = letter
                    changed = True

                expected_note = (
                    f"Relasi Risiko Korporat R{corp.no_risiko} "
                    f"dengan risiko utama {source.summary.unit_bisnis}."
                )

                if relation.keterangan != expected_note:
                    relation.keterangan = expected_note
                    changed = True

                if changed:
                    relation.save(
                        update_fields=[
                            "no_penyebab_risiko",
                            "keterangan",
                        ]
                    )
                    updated += 1

    print()
    print("=" * 140)
    print("APPLY RESULT")
    print("=" * 140)
    print("CREATED :", created)
    print("EXISTING:", existing)
    print("UPDATED :", updated)
    print("REMOVED :", removed)


def verify():
    print()
    print("=" * 140)
    print("POST VERIFY")
    print("=" * 140)

    unmapped = []
    total = 0

    for no in range(1, 16):
        corp = corporate_risk(no)

        rows = list(
            corp.sumber_risiko
            .select_related(
                "reassessment_item",
                "reassessment_item__summary",
                "reassessment_item__summary__unit_bisnis",
            )
            .order_by(
                "no_penyebab_risiko",
                "pk",
            )
        )

        total += len(rows)

        print(
            f"R{no:02} | REL={len(rows)} | "
            f"{corp.peristiwa_risiko}"
        )

        if not rows:
            unmapped.append(no)

        for relation in rows:
            risk = relation.reassessment_item
            print(
                f"  {relation.no_penyebab_risiko} -> "
                f"{risk.summary.unit_bisnis} | "
                f"RE={risk.pk} | R{risk.no_risiko}"
            )

    print()
    print("TOTAL CORPORATE:", 15)
    print("TOTAL RELATION :", total)
    print("UNMAPPED       :", unmapped)

    if unmapped:
        raise RuntimeError(
            f"Masih ada corporate risk belum terpetakan: {unmapped}"
        )

    if total != 22:
        raise RuntimeError(
            f"Total relation tidak sesuai. Expected=22 Actual={total}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Terapkan perubahan. Tanpa opsi ini hanya dry-run.",
    )
    args = parser.parse_args()

    plan = build_plan()
    print_plan(plan)

    if not args.apply:
        print()
        print("DRY RUN ONLY — DATABASE TIDAK DIUBAH.")
        return

    apply_plan(plan)
    verify()


if __name__ == "__main__":
    main()
