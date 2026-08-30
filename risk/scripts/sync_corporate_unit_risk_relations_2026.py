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


from monthly_report.models import MonthlyRiskReportItem

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
            3,
            "Parameter komersial proyek belum matang - CCUS",
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
            "BID K3L",
            6,
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
    """
    Resolve ReAssessmentItem canonical secara konservatif.

    Urutan:
    1. unit + no_risiko + event exact
    2. jika nomor risiko berbeda antar database, cari unit + event
    3. jika event duplikat, histori MonthlyRiskReportItem menjadi
       canonical signal
    4. jika masih ambigu, STOP

    Tidak pernah memilih kandidat secara arbitrer.
    """
    base_qs = (
        ReAssessmentItem.objects
        .filter(
            summary__tahun=YEAR,
            summary__unit_bisnis__name=unit_name,
            is_active=True,
        )
        .select_related(
            "summary",
            "summary__unit_bisnis",
        )
    )

    # --------------------------------------------------------
    # 1. Preferred: nomor risiko + event sesuai mapping
    # --------------------------------------------------------
    numbered = list(
        base_qs.filter(no_risiko=no_risiko)
    )

    exact = [
        row for row in numbered
        if normalized(row.peristiwa_risiko) == normalized(event)
    ]

    if len(exact) == 1:
        return exact[0]

    if len(exact) > 1:
        usage = []

        for candidate in exact:
            count = (
                MonthlyRiskReportItem.objects
                .filter(risk_event_id=candidate.pk)
                .count()
            )
            usage.append((candidate, count))

        used = [
            (candidate, count)
            for candidate, count in usage
            if count > 0
        ]

        # Hanya aman jika tepat satu kandidat yang benar-benar
        # mempunyai histori Monthly Risk Report.
        if len(used) == 1:
            selected, count = used[0]

            print()
            print(
                "CANONICAL EXACT via Monthly Report history:"
            )
            print(
                f"  unit={unit_name!r} | "
                f"R={no_risiko} | "
                f"RE={selected.pk} | "
                f"usage={count}"
            )

            return selected

        print()
        print(
            f"ERROR SOURCE: unit={unit_name!r}, "
            f"R={no_risiko}, event={event!r}"
        )
        print(
            "Exact candidate lebih dari satu dan histori MRR "
            "tidak menghasilkan satu canonical source:"
        )

        for candidate, count in usage:
            print(
                f"  RE={candidate.pk} | "
                f"no_item={candidate.no_item} | "
                f"R={candidate.no_risiko} | "
                f"MRR_USAGE={count} | "
                f"event={candidate.peristiwa_risiko!r}"
            )

        raise RuntimeError(
            "Terdapat lebih dari satu source risk exact dan "
            "canonical source tidak dapat ditentukan."
        )

    # --------------------------------------------------------
    # 2. Fallback: nomor risiko bisa berbeda antar snapshot DB.
    #    Cari event canonical pada unit yang sama.
    # --------------------------------------------------------
    event_candidates = [
        row for row in base_qs
        if normalized(row.peristiwa_risiko) == normalized(event)
    ]

    if len(event_candidates) == 1:
        selected = event_candidates[0]

        print()
        print(
            "CANONICAL FALLBACK: "
            f"unit={unit_name!r}, "
            f"mapping R={no_risiko}, "
            f"DB R={selected.no_risiko}, "
            f"RE={selected.pk}"
        )
        print(
            "  reason: event unik pada unit yang sama"
        )

        return selected

    # --------------------------------------------------------
    # 3. Event duplikat: histori MRR sebagai canonical signal.
    # --------------------------------------------------------
    if len(event_candidates) > 1:
        usage = []

        for candidate in event_candidates:
            count = (
                MonthlyRiskReportItem.objects
                .filter(risk_event_id=candidate.pk)
                .count()
            )

            usage.append(
                (candidate, count)
            )

        used = [
            (candidate, count)
            for candidate, count in usage
            if count > 0
        ]

        # Sangat konservatif:
        # hanya satu kandidat yang pernah digunakan MRR.
        if len(used) == 1:
            selected, count = used[0]

            print()
            print(
                "CANONICAL FALLBACK via Monthly Report history:"
            )
            print(
                f"  unit={unit_name!r} | "
                f"mapping R={no_risiko} | "
                f"DB R={selected.no_risiko} | "
                f"RE={selected.pk} | "
                f"usage={count}"
            )

            return selected

        print()
        print(
            f"ERROR SOURCE: unit={unit_name!r}, "
            f"R={no_risiko}, event={event!r}"
        )
        print(
            "Event ditemukan lebih dari satu dan tidak dapat "
            "ditentukan secara unik dari histori MRR:"
        )

        for candidate, count in usage:
            print(
                f"  RE={candidate.pk} | "
                f"no_item={candidate.no_item} | "
                f"R={candidate.no_risiko} | "
                f"MRR_USAGE={count} | "
                f"event={candidate.peristiwa_risiko!r}"
            )

        raise RuntimeError(
            "Source risk ambigu setelah audit histori MRR. "
            "Tidak aman untuk meneruskan sinkronisasi."
        )

    # --------------------------------------------------------
    # 4. Tidak ada event yang cocok sama sekali.
    # --------------------------------------------------------
    print()
    print(
        f"ERROR SOURCE: unit={unit_name!r}, "
        f"R={no_risiko}, event={event!r}"
    )
    print("Candidate event pada unit tersebut = 0")

    if numbered:
        print(
            f"Risiko dengan nomor R={no_risiko} yang tersedia:"
        )

        for row in numbered:
            print(
                f"  RE={row.pk} | "
                f"no_item={row.no_item} | "
                f"event={row.peristiwa_risiko!r}"
            )

    raise RuntimeError(
        "Source risk tidak ditemukan. "
        "Tidak aman untuk meneruskan sinkronisasi."
    )


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
