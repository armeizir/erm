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
from masterdata.models import TahunBuku
from monthly_report.models import MonthlyRiskReport
from monthly_report.scripts.import_ops_manpro_keu_hcga_monthly_reports import (
    YEAR,
    build_maps,
    get_period,
    get_prepared_by,
    import_changes,
    import_loss_events,
    import_standard_iiia,
    import_standard_iiib,
    read_rows,
    resolve_default,
    row_value,
)
from risk.models import ReAssessmentSummary
from openpyxl import load_workbook


DEFAULT_SOURCE_FILE = "/Users/armeizir/Downloads/Laporan Manajemen Risiko UBKITRANS Juni 2026.xlsx"
UNIT_NAME = "UB KITRAN"
REPORT_CODE = "MRR-UBKITRANS-2026-06"
MONTH = 6


def source_file():
    return Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE_FILE)


def ubkitrans_reassessment():
    return (
        ReAssessmentSummary.objects.filter(
            tahun=YEAR,
            unit_bisnis__name=UNIT_NAME,
            judul__icontains="UBKITRANS",
        )
        .select_related("unit_bisnis")
        .order_by("id")
        .first()
    )


def unmatched_rows(workbook, maps, sheet_name):
    by_name, by_no_item, by_no_risiko = maps
    rows = []
    worksheet = workbook[sheet_name]
    for row_idx, row in read_rows(worksheet, 10):
        event_name = row_value(row, 3)
        if not event_name:
            continue
        risk_event = resolve_default(row, by_name, by_no_item, by_no_risiko)
        if not risk_event:
            rows.append((sheet_name, row_idx, row_value(row, 2), event_name))
    return rows


def run():
    path = source_file()
    if not path.exists():
        raise FileNotFoundError(path)

    reassessment = ubkitrans_reassessment()
    if not reassessment:
        raise RuntimeError(f"Profil Risiko UBKITRANS tahun {YEAR} tidak ditemukan.")

    prepared_by = get_prepared_by()
    if not prepared_by:
        raise RuntimeError("Tidak ada user untuk prepared_by.")

    workbook = load_workbook(path, data_only=True, read_only=True, keep_links=False)
    maps = build_maps(reassessment)
    unmatched = unmatched_rows(workbook, maps, "III.A") + unmatched_rows(workbook, maps, "III.B")

    with transaction.atomic():
        tahun_buku, _ = TahunBuku.objects.get_or_create(tahun=YEAR, defaults={"aktif": True})
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
        iiia = import_standard_iiia(workbook, report, maps, MONTH, skipped)
        iiib = import_standard_iiib(workbook, report, maps, MONTH, skipped)
        iiid = import_changes(workbook, report)
        iiie = import_loss_events(workbook, report)

        report.total_risiko = report.items.count()
        report.total_high = report.items.filter(realisasi_level_risiko__icontains="tinggi").count()
        report.total_mitigasi_terlambat = report.items.filter(mitigation_status="delayed").count()
        report.total_selesai = report.items.filter(status_rencana_perlakuan="discontinue").count()
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
    if not unmatched and not skipped:
        print("- Semua baris utama III.A dan III.B cocok dengan data profil risiko di database.")
    for item in unmatched:
        print(f"- Tidak cocok: sheet={item[0]}, row={item[1]}, no={item[2]}, risiko={item[3]}")
    for item in skipped:
        print(f"- Dilewati importer: {item}")


if __name__ == "__main__":
    run()
