"""Repair SPI Juni 2026 V4.

Key correction vs V3:
- fixes Target Residual Q2 on 22 ReAssessmentItem from official SPI profile;
- keeps 22 treatment-level items, including RE 217 + RE 218;
- creates the 7 missing MonthlyRiskReportItem records;
- aligns actual residual June and III.B treatment data;
- clears III.D changes and template III.E loss-event rows for this report.

DRY RUN:
  python monthly_report/scripts/repair_spi_june_2026_v4.py

APPLY:
  python monthly_report/scripts/repair_spi_june_2026_v4.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.dev")

import django
django.setup()

from django.conf import settings
from django.db import transaction

from monthly_report.models import (
    MonthlyRiskReport,
    MonthlyRiskReportChange,
    MonthlyRiskReportItem,
    MonthlyRiskReportLossEvent,
)
from monthly_report.services import refresh_monthly_report_summary
from risk.models import (
    MasterSkalaDampak,
    MasterSkalaProbabilitas,
    ReAssessmentItem,
)

REFERENCE = Path(__file__).with_name("spi_tw2_2026_reference_v4.json")


def norm(v):
    s = " ".join(str(v or "").replace("\n", " ").split()).casefold()
    return re.sub(r"[^a-z0-9]+", "", s)


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def load_ref():
    data = json.loads(REFERENCE.read_text(encoding="utf-8"))
    if len(data["snapshots"]) != 15 or len(data["items"]) != 22:
        raise RuntimeError("Reference V4 harus 15 snapshots dan 22 items.")
    return data


def get_report(ref):
    m = ref["metadata"]
    report = (
        MonthlyRiskReport.objects
        .select_related("reassessment", "reassessment__unit_bisnis", "periode")
        .get(pk=m["report_id"])
    )
    if report.reassessment_id != m["profile_id"]:
        raise RuntimeError(
            f"Report profile id={report.reassessment_id}, expected {m['profile_id']}"
        )
    if report.reassessment.tahun != 2026 or report.periode.tanggal_mulai.month != 6:
        raise RuntimeError("Report bukan SPI Juni 2026.")
    if "SPI" not in str(report.reassessment.unit_bisnis).upper():
        raise RuntimeError(f"Unit bukan SPI: {report.reassessment.unit_bisnis}")
    return report


def scale_maps():
    impacts = {x.urutan: x for x in MasterSkalaDampak.objects.filter(aktif=True)}
    probs = {x.urutan: x for x in MasterSkalaProbabilitas.objects.filter(aktif=True)}
    for i in range(1, 6):
        if i not in impacts or i not in probs:
            raise RuntimeError("Master skala dampak/probabilitas 1..5 tidak lengkap.")
    return impacts, probs


def backup_db():
    db = Path(str(settings.DATABASES["default"].get("NAME", ""))).resolve()
    if not db.exists():
        raise RuntimeError(f"DB tidak ditemukan: {db}")
    out = ROOT / "backups"
    out.mkdir(exist_ok=True)
    target = out / f"db_before_spi_tw2_v4_{datetime.now():%Y%m%d_%H%M%S}.sqlite3"
    shutil.copy2(db, target)
    return target


def validate_mapping(ref, report):
    current_ids = set(report.items.values_list("risk_event_id", flat=True))
    rows = []
    for item in ref["items"]:
        risk = ReAssessmentItem.objects.filter(
            pk=item["re_id"], summary_id=ref["metadata"]["profile_id"]
        ).first()
        if not risk:
            raise RuntimeError(f"RE id={item['re_id']} tidak ditemukan di profil SPI.")
        score = max(
            sim(item["plan"], risk.rencana_perlakuan_risiko),
            sim(item["actual_plan"], risk.rencana_perlakuan_risiko),
        )
        if score < 0.35:
            raise RuntimeError(
                f"Mapping tidak meyakinkan row={item['source_row']} -> RE={risk.id}: {score:.2f}"
            )
        rows.append((item, risk, score, risk.id in current_ids))

    if len({risk.id for _, risk, _, _ in rows}) != 22:
        raise RuntimeError("Mapping tidak unik 22/22.")

    extras = sorted(current_ids - {risk.id for _, risk, _, _ in rows})
    if extras:
        raise RuntimeError(f"Ada Monthly item ekstra di luar 22 mapping: {extras}")
    return rows


def audit(ref, report, rows):
    snaps = {x["risk_no"]: x for x in ref["snapshots"]}
    print("=" * 140)
    print("AUDIT SPI JUNI 2026 V4 - TARGET Q2 + ACTUAL JUNI")
    print("=" * 140)
    print(f"Report                : {report.id} - {report}")
    print(f"Monthly item saat ini : {report.items.count()} (target 22)")
    print(f"Mapped                : {len(rows)} / 22")
    print()
    print("ROW | RE-ID | RISK | IN REPORT | DB TARGET Q2 -> SOURCE TARGET Q2 | ACTUAL JUNI | MATCH | PLAN")
    print("-" * 140)
    for item, risk, score, in_report in rows:
        snap = snaps[item["risk_no"]]
        print(
            f"{item['source_row']:>3} | {risk.id:>5} | R{item['risk_no']:<2} | "
            f"{'YA' if in_report else 'BELUM':<8} | "
            f"{str(risk.skala_risiko_q2):>4} -> {snap['target_score']:<2} | "
            f"{snap['actual_score']:<2} | {score:>5.2f} | "
            f"{item['plan'][:54]}"
        )
    missing = [risk.id for _, risk, _, present in rows if not present]
    print()
    print("Missing monthly items:", missing or "-")
    print("Expected missing      : [209, 211, 212, 214, 215, 217, 218]")
    print()
    print("MANUAL I1 SOURCE: 15 logical risks = 1 below, 14 same, 0 above -> b / 60 / 18")
    print("I4.3 TARGET: a")
    print("DRY RUN: tidak ada data yang diubah.")


def apply_changes(ref, report, rows):
    impacts, probs = scale_maps()
    snaps = {x["risk_no"]: x for x in ref["snapshots"]}

    with transaction.atomic():
        for item, risk, _, _ in rows:
            snap = snaps[item["risk_no"]]

            # Correct profile target residual Q2. Do not alter identity/codes.
            ReAssessmentItem.objects.filter(pk=risk.id).update(
                biaya_perlakuan_risiko=Decimal("0"),
                skala_dampak_q2_id=impacts[int(snap["target_impact"])].id,
                skala_probabilitas_q2_id=probs[int(snap["target_probability"])].id,
                skala_risiko_q2=str(snap["target_score"]),
                level_nilai_risiko_q2=snap["target_level"],
            )

            monthly, _ = MonthlyRiskReportItem.objects.get_or_create(
                report=report, risk_event_id=risk.id
            )
            MonthlyRiskReportItem.objects.filter(pk=monthly.id).update(
                realisasi_nilai_dampak=Decimal(str(snap["actual_impact_value"])),
                realisasi_skala_dampak_id=impacts[int(snap["actual_impact"])].id,
                realisasi_nilai_probabilitas=Decimal(str(snap["actual_probability_percent"])),
                realisasi_skala_probabilitas_id=probs[int(snap["actual_probability"])].id,
                realisasi_eksposur=Decimal(str(snap["actual_exposure"])),
                realisasi_skor_risiko=int(snap["actual_score"]),
                realisasi_level_risiko=snap["actual_level"],
                realisasi_rencana_perlakuan=item["actual_plan"],
                realisasi_output_perlakuan=item["actual_output"],
                realisasi_biaya_perlakuan=Decimal("0"),
                persentase_serapan_biaya=Decimal("0"),
                realisasi_pic=item["pic"],
                status_rencana_perlakuan="continue",
                penjelasan_status_rencana=item["status_explanation"],
                progress_pelaksanaan_percent=Decimal("100"),
                realisasi_threshold_kri=item["threshold"],
                realisasi_threshold_kri_skor=Decimal(str(item["threshold_score"])),
            )

        # Official June workbook: III.D = Tidak ada perubahan.
        MonthlyRiskReportChange.objects.filter(report=report).delete()
        # III.E gas/kurs line is template/example; source also says Tidak terjadi loss event.
        MonthlyRiskReportLossEvent.objects.filter(report=report).delete()
        refresh_monthly_report_summary(report)


def validate_after(ref, report, rows):
    report.refresh_from_db()
    snaps = {x["risk_no"]: x for x in ref["snapshots"]}
    errors = []

    if report.items.count() != 22:
        errors.append(f"Monthly items={report.items.count()} != 22")

    mapped_ids = {risk.id for _, risk, _, _ in rows}
    report_ids = set(report.items.values_list("risk_event_id", flat=True))
    if report_ids != mapped_ids:
        errors.append(
            f"Item IDs beda. missing={sorted(mapped_ids-report_ids)} "
            f"extra={sorted(report_ids-mapped_ids)}"
        )

    for item, risk, _, _ in rows:
        risk.refresh_from_db()
        snap = snaps[item["risk_no"]]
        if str(risk.skala_risiko_q2) != str(snap["target_score"]):
            errors.append(
                f"RE {risk.id} target={risk.skala_risiko_q2} != {snap['target_score']}"
            )
        monthly = MonthlyRiskReportItem.objects.get(report=report, risk_event_id=risk.id)
        if int(monthly.realisasi_skor_risiko) != int(snap["actual_score"]):
            errors.append(
                f"RE {risk.id} actual={monthly.realisasi_skor_risiko} != {snap['actual_score']}"
            )
        if monthly.progress_pelaksanaan_percent != Decimal("100"):
            errors.append(f"RE {risk.id} progress != 100")
        if monthly.realisasi_biaya_perlakuan != Decimal("0"):
            errors.append(f"RE {risk.id} actual cost != 0")

    # Manual source-level I1 at 15 logical risk-event level.
    below = same = above = 0
    for snap in ref["snapshots"]:
        if snap["actual_score"] < snap["target_score"]:
            below += 1
        elif snap["actual_score"] == snap["target_score"]:
            same += 1
        else:
            above += 1
    if (below, same, above) != (1, 14, 0):
        errors.append(f"Manual I1={below}/{same}/{above} != 1/14/0")

    if MonthlyRiskReportChange.objects.filter(report=report).exists():
        errors.append("III.D masih memiliki change records")
    if MonthlyRiskReportLossEvent.objects.filter(report=report).exists():
        errors.append("III.E masih memiliki loss-event records")

    if errors:
        raise RuntimeError("VALIDASI V4 GAGAL:\n- " + "\n- ".join(errors))

    print("\nVALIDASI DATA V4 BERHASIL")
    print("- 15 logical risk events")
    print("- 22 treatment-level ReAssessmentItem")
    print("- 22 MonthlyRiskReportItem")
    print("- Target Residual Q2 dikoreksi dari profil resmi")
    print("- Actual residual Juni diselaraskan dengan III.A")
    print("- 22 treatment diselaraskan dengan III.B")
    print("- Progress Q2 = 100%")
    print("- Budget/realisasi treatment = no-cost / 0")
    print("- III.D = Tidak ada perubahan")
    print("- III.E = tidak ada loss event SPI")
    print("- Manual I1 = 1 below / 14 same / 0 above => b / 60 / 18")
    print("- I4.3 target kebijakan = a")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    ref = load_ref()
    report = get_report(ref)
    rows = validate_mapping(ref, report)

    if not args.apply:
        audit(ref, report, rows)
        return

    backup = backup_db()
    print("BACKUP DB:", backup)
    apply_changes(ref, report, rows)
    validate_after(ref, report, rows)


if __name__ == "__main__":
    main()
