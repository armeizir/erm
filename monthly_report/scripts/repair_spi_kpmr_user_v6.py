"""Koreksi data eksposur SPI TW II sesuai KPMR asesmen user.

Sumber:
  KPMR Profil Risiko SPI PLN Batam 2026.xlsx

Dry run:
  python monthly_report/scripts/repair_spi_kpmr_user_v6.py

Apply:
  python monthly_report/scripts/repair_spi_kpmr_user_v6.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.dev")

import django
django.setup()

from django.conf import settings
from django.db import transaction

from monthly_report.models import MonthlyRiskReport, MonthlyRiskReportItem
from risk.models import ReAssessmentItem
from risk.services.kpmr_automation import _aggregate_exposure_for_i1

REFERENCE = '{\n  "metadata": {\n    "version": "V6-user-assessment",\n    "source": "KPMR Profil Risiko SPI PLN Batam 2026.xlsx",\n    "unit": "KSPI",\n    "year": 2026,\n    "quarter": 2,\n    "month": 6,\n    "method": "I1 compares aggregate Total Exposure Residual vs Total Exposure Target",\n    "expected_total_exposure_target": 4423810890,\n    "expected_total_exposure_residual": 3756065850,\n    "expected_i1": {\n      "answer": "a",\n      "raw": 90,\n      "weighted": 27\n    },\n    "expected_kpmr": {\n      "I1": 27,\n      "I2": 20,\n      "I3": 16,\n      "I4": 27,\n      "total": 90,\n      "rating": "SATISFACTORY"\n    },\n    "note": "Penilaian user: residual aggregate < target aggregate => a=90. KPMR sebelumnya 81/FAIR memakai perbandingan skor per item dan dikoreksi."\n  },\n  "risk_groups": [\n    {\n      "group": 1,\n      "reassessment_item_ids": [\n        183,\n        184,\n        185\n      ],\n      "exposure_target_q2": 183629886,\n      "exposure_residual_june": 517502406\n    },\n    {\n      "group": 2,\n      "reassessment_item_ids": [\n        187,\n        188\n      ],\n      "exposure_target_q2": 317178894,\n      "exposure_residual_june": 0\n    },\n    {\n      "group": 3,\n      "reassessment_item_ids": [\n        190\n      ],\n      "exposure_target_q2": 467421528,\n      "exposure_residual_june": 183629886\n    },\n    {\n      "group": 4,\n      "reassessment_item_ids": [\n        192\n      ],\n      "exposure_target_q2": 1018311186,\n      "exposure_residual_june": 417340650\n    },\n    {\n      "group": 5,\n      "reassessment_item_ids": [\n        194,\n        195\n      ],\n      "exposure_target_q2": 333872520,\n      "exposure_residual_june": 333872520\n    },\n    {\n      "group": 6,\n      "reassessment_item_ids": [\n        198,\n        199,\n        202,\n        203,\n        204,\n        208,\n        209\n      ],\n      "exposure_target_q2": 300485268,\n      "exposure_residual_june": 333872520\n    },\n    {\n      "group": 7,\n      "reassessment_item_ids": [\n        211,\n        212\n      ],\n      "exposure_target_q2": 250404390,\n      "exposure_residual_june": 300485268\n    },\n    {\n      "group": 8,\n      "reassessment_item_ids": [\n        214,\n        215\n      ],\n      "exposure_target_q2": 217017138,\n      "exposure_residual_june": 0\n    },\n    {\n      "group": 9,\n      "reassessment_item_ids": [\n        217,\n        218\n      ],\n      "exposure_target_q2": 1335490080,\n      "exposure_residual_june": 1669362600\n    }\n  ]\n}'


def load_ref():
    return json.loads(REFERENCE)


def get_report():
    candidates = list(
        MonthlyRiskReport.objects
        .select_related("reassessment", "reassessment__unit_bisnis", "periode")
        .filter(
            reassessment__tahun=2026,
            reassessment__unit_bisnis__name__icontains="SPI",
            periode__tanggal_mulai__year=2026,
            periode__tanggal_mulai__month=6,
        )
        .order_by("id")
    )
    if len(candidates) != 1:
        detail = "\n".join(
            f"- id={r.id} | profile={r.reassessment_id} | unit={r.reassessment.unit_bisnis} | {r}"
            for r in candidates
        )
        raise RuntimeError(f"SPI Juni 2026 harus tepat satu report. Ditemukan {len(candidates)}:\n{detail}")
    return candidates[0]


def backup_db():
    db = Path(str(settings.DATABASES["default"].get("NAME", ""))).resolve()
    if not db.exists():
        raise RuntimeError(f"DB tidak ditemukan: {db}")
    out = ROOT / "backups"
    out.mkdir(exist_ok=True)
    target = out / f"db_before_spi_kpmr_user_v6_{datetime.now():%Y%m%d_%H%M%S}.sqlite3"
    shutil.copy2(db, target)
    return target


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    ref = load_ref()
    report = get_report()
    groups = ref["risk_groups"]
    expected_ids = {rid for g in groups for rid in g["reassessment_item_ids"]}
    profile_ids = set(
        ReAssessmentItem.objects.filter(summary=report.reassessment)
        .values_list("id", flat=True)
    )

    missing_profile = sorted(expected_ids - profile_ids)
    if missing_profile:
        raise RuntimeError(f"RE-ID tidak ditemukan pada profile SPI: {missing_profile}")

    report_ids = set(report.items.values_list("risk_event_id", flat=True))
    missing_report = sorted(expected_ids - report_ids)
    extra_report = sorted(report_ids - expected_ids)
    if missing_report or extra_report:
        raise RuntimeError(
            f"Struktur report belum 22 item resmi. missing={missing_report}, extra={extra_report}"
        )

    print("=" * 118)
    print("KOREKSI I1 KPMR SPI - SESUAI ASESMEN USER")
    print("=" * 118)
    print(f"Report : {report.id} - {report}")
    print(f"Unit   : {report.reassessment.unit_bisnis}")
    print()
    print("GROUP | RE-IDs                         | TARGET USER       | RESIDUAL USER")
    print("-" * 118)
    for g in groups:
        print(
            f"{g['group']:>5} | "
            f"{','.join(str(x) for x in g['reassessment_item_ids']):<30} | "
            f"{g['exposure_target_q2']:>17,} | {g['exposure_residual_june']:>17,}"
        )

    target_total = sum(Decimal(str(g["exposure_target_q2"])) for g in groups)
    residual_total = sum(Decimal(str(g["exposure_residual_june"])) for g in groups)
    print("-" * 118)
    print(f"TOTAL TARGET USER   : {target_total:,.0f}")
    print(f"TOTAL RESIDUAL USER : {residual_total:,.0f}")
    print("FORMULA USER        : Residual < Target => a = 90 => skor I1 = 27")
    print("TARGET KPMR         : 90 / SATISFACTORY")

    if not args.apply:
        print("\nDRY RUN: tidak ada data yang diubah.")
        return

    backup = backup_db()
    print("\nBACKUP DB:", backup)

    with transaction.atomic():
        for g in groups:
            group_no = int(g["group"])
            target = Decimal(str(g["exposure_target_q2"]))
            residual = Decimal(str(g["exposure_residual_june"]))
            ids = list(g["reassessment_item_ids"])

            ReAssessmentItem.objects.filter(
                summary=report.reassessment,
                id__in=ids,
            ).update(
                no_item=group_no,
                eksposur_risiko_q2=target,
            )
            MonthlyRiskReportItem.objects.filter(
                report=report,
                risk_event_id__in=ids,
            ).update(
                realisasi_eksposur=residual,
            )

    report.refresh_from_db()
    items = list(report.items.select_related("risk_event").all())
    summary = _aggregate_exposure_for_i1(items, 2)

    errors = []
    if summary is None:
        errors.append("Aggregate exposure summary None")
    else:
        if summary["group_count"] != 9:
            errors.append(f"group_count={summary['group_count']} != 9")
        if summary["incomplete_group_count"] != 0:
            errors.append(f"incomplete_group_count={summary['incomplete_group_count']} != 0")
        if summary["conflicts"]:
            errors.append(f"conflicts={summary['conflicts']}")
        if summary["total_target"] != Decimal("4423810890"):
            errors.append(f"target={summary['total_target']} != 4423810890")
        if summary["total_residual"] != Decimal("3756065850"):
            errors.append(f"residual={summary['total_residual']} != 3756065850")

    if errors:
        raise RuntimeError("VALIDASI V6 GAGAL:\n- " + "\n- ".join(errors))

    print("\nVALIDASI DATA V6 BERHASIL")
    print("- Top-risk/group KPMR = 9")
    print("- Treatment-level MonthlyRiskReportItem = 22")
    print("- Total Exposure Target = 4,423,810,890")
    print("- Total Exposure Residual = 3,756,065,850")
    print("- Residual < Target => I1 jawaban a / hasil 90 / skor 27")


if __name__ == "__main__":
    main()
