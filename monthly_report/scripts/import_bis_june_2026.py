from pathlib import Path
import os
import sys

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.dev")

import django

django.setup()

from django.db import transaction
from openpyxl import load_workbook

from masterdata.models import TahunBuku
from monthly_report.models import MonthlyRiskReport
from monthly_report.scripts.import_bis_monthly_reports import (
    MONTH_NAMES,
    build_event_map,
    get_period,
    get_prepared_by,
    import_sheet_iiia,
    import_sheet_iiib,
    import_sheet_iiid,
    import_sheet_iiie,
)
from risk.models import ReAssessmentSummary


DEFAULT_SOURCE_FILE = "/Users/armeizir/Downloads/Mitigasi Risiko dan KRI BIS Juni 2026.xlsx"
UNIT_NAME = "BID BIS"
REPORT_CODE = "MRR-BIS-2026-06"
MONTH = 6
YEAR = 2026


def source_file():
    return Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE_FILE)


def bis_reassessment():
    return (
        ReAssessmentSummary.objects.filter(
            tahun=YEAR,
            unit_bisnis__name=UNIT_NAME,
            judul__icontains="BIS",
        )
        .select_related("unit_bisnis")
        .order_by("id")
        .first()
    )


def run():
    path = source_file()
    if not path.exists():
        raise FileNotFoundError(path)

    reassessment = bis_reassessment()
    if not reassessment:
        raise RuntimeError(f"Profil Risiko {UNIT_NAME} tahun {YEAR} tidak ditemukan.")

    prepared_by = get_prepared_by()
    if not prepared_by:
        raise RuntimeError("Tidak ada user untuk prepared_by.")

    workbook = load_workbook(path, data_only=True, read_only=True, keep_links=False)
    event_map = build_event_map(reassessment)

    with transaction.atomic():
        tahun_buku, _ = TahunBuku.objects.get_or_create(
            tahun=YEAR,
            defaults={"aktif": True},
        )
        period = get_period(tahun_buku, MONTH)
        report, _ = MonthlyRiskReport.objects.update_or_create(
            reassessment=reassessment,
            periode=period,
            versi=1,
            defaults={
                "kode": REPORT_CODE,
                "tahun_buku": tahun_buku,
                "status": "draft",
                "prepared_by": prepared_by,
            },
        )

        skipped = []
        iiia = import_sheet_iiia(workbook, report, event_map, MONTH, skipped)
        iiib = import_sheet_iiib(workbook, report, event_map, MONTH, skipped)
        iiid = import_sheet_iiid(workbook, report)
        iiie = import_sheet_iiie(workbook, report, event_map, skipped)

        report.total_risiko = report.items.count()
        report.total_high = report.items.filter(
            realisasi_level_risiko__icontains="tinggi",
        ).count()
        report.total_mitigasi_terlambat = report.items.filter(
            mitigation_status="delayed",
        ).count()
        report.total_selesai = report.items.filter(
            status_rencana_perlakuan="discontinue",
        ).count()
        report.save(
            update_fields=[
                "total_risiko",
                "total_high",
                "total_mitigasi_terlambat",
                "total_selesai",
                "updated_at",
            ]
        )

    print("IMPORT SUMMARY")
    print(f"- Report: {report.id} {report.kode} / {report}")
    print(f"- Profil Risiko: {reassessment.id} {reassessment.judul}")
    print(f"- Items: {report.items.count()}")
    print(f"- III.A imported: {iiia}")
    print(f"- III.B imported: {iiib}")
    print(f"- III.D imported: {iiid}")
    print(f"- III.E imported: {iiie}")

    print("\nCATATAN DATA")
    if not skipped:
        print("- Semua baris utama III.A, III.B, dan III.E cocok dengan data profil risiko di database.")
    for item in skipped:
        label = f"{item.get('sheet')} row {item.get('row')}"
        if item.get("no") is not None:
            label += f" no={item.get('no')}"
        print(f"- {label}: {item.get('event')} -> {item.get('reason')}")


if __name__ == "__main__":
    run()
