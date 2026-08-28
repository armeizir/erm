#!/usr/bin/env python3
"""
IMPORT MRR BID RENKIN JUNI + JULI 2026 - V1 SAFE

Source:
- Laporan MR BID RENKIN Juni 2026.xlsx
  SHA256 fb87b9c4647906169f5f2da792dea656c28f4cdb19ab53213bcde7b1b4501e6c
- Laporan MR BID RENKIN Juli 2026.xlsx
  SHA256 72787334d3f4e7789f8abdc0a8b4f51da12e6bc9a1276ac83757dfc37ebf06f5

Validated production baseline:
- ReAssessmentSummary id=10 : Profil Risiko RENKIN
- Unit business id=8         : BID RENKIN
- KontrakManajemen id=13     : VPREN, Final
- TahunBuku id=3             : 2026
- Periode id=90              : Jun 2026
- Periode id=91              : Jul 2026
- prepared_by id=176
- MRR March id=7 and April id=8 use 9 event-level representatives.
- No June/July MRR exists before import.

SOURCE DECISIONS
1. III.A has 9 RENKIN event-level rows. Rows below the RENKIN block belong to
   other units/corporate risks and are not imported.
2. III.B has 17 treatment/activity rows but 9 event groups.
3. Risk 6 has 9 treatment rows. Production also has 9 ReAssessmentItems for
   that same risk event/cause, but historical MRR March/April uses RE=173 as
   the event-level representative. To avoid duplicating III.A nine times,
   June/July keep the same 9-event MRR convention:
      1->165, 2->166, 3->168, 4->170, 5->174,
      6->173, 7->179, 8->180, 9->181.
   All nine risk-6 source treatments are preserved inside the representative
   MonthlyRiskReportItem as paired plan/realisasi narratives, summed costs,
   union timeline, detailed KRI text, and mean populated quarter progress.
4. June:
   - Q2 residual values from III.A are imported.
   - Q2 treatment progress is imported; risk 6 uses arithmetic mean of its
     nine populated source Q2 progress values.
   - Source timeline is clipped to Jan-Jun. Several June workbook rows already
     contain July flags; those July flags are not copied into June.
   - KRI June threshold is source text "3. Hijau"; KRI score is blank.
5. July:
   - Q3 residual fields are blank in source => remain NULL.
   - Q3 treatment progress is blank in source => remain NULL.
   - Timeline may include July exactly as source; Aug-Dec are zero.
   - KRI July threshold is source text "3. Hijau"; KRI score is blank.
   - Narrative text that still says June/May is preserved verbatim.
6. Source PIC column is blank, therefore realisasi_pic and organization FK
   remain NULL. Profile anomaly RE=177 PIC="400,000,000" is NOT propagated.
7. III.D has no source change row. III.E has no loss event.
8. Costs:
   - planned total per month = 64,113,157,687
   - actual total per month  = 47,107,320,892
   '-' in source actual cost is preserved as NULL rather than fabricated 0.

Safety:
- Default DRY-RUN; --apply required to commit.
- Exact source SHA256 guard.
- Exact production profile/KM/period/representative guards.
- Duplicate June/July MRR guard.
- SQLite backup + integrity/FK check before apply.
- transaction.atomic() for both months together.
- QuerySet.update() is used for monthly source fields to avoid model save
  recalculation silently replacing source-exact values.
- Post-check validates item counts, totals, residual/progress month logic,
  KRI, timeline clipping, III.D/III.E emptiness, and DB integrity.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path("/home/adminsvr/erm")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.prod")

import django
django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum

from masterdata.models import PeriodeLaporan, TahunBuku
from monthly_report.models import (
    MonthlyRiskReport,
    MonthlyRiskReportChange,
    MonthlyRiskReportItem,
    MonthlyRiskReportLossEvent,
)
from risk.models import (
    KontrakManajemen,
    MasterSkalaDampak,
    MasterSkalaProbabilitas,
    ReAssessmentItem,
    ReAssessmentSummary,
)

PROFILE_ID = 10
UNIT_GROUP_ID = 8
KM_ID = 13
YEAR_BOOK_ID = 3
PREPARED_BY_ID = 176

PERIODS = {
    6: {"id": 90, "code": "2026-06", "report_code": "MRR-RENKIN-2026-06"},
    7: {"id": 91, "code": "2026-07", "report_code": "MRR-RENKIN-2026-07"},
}

EXPECTED_HASHES = {
    6: "fb87b9c4647906169f5f2da792dea656c28f4cdb19ab53213bcde7b1b4501e6c",
    7: "72787334d3f4e7789f8abdc0a8b4f51da12e6bc9a1276ac83757dfc37ebf06f5",
}

REPRESENTATIVES = {
    1: 165,
    2: 166,
    3: 168,
    4: 170,
    5: 174,
    6: 173,
    7: 179,
    8: 180,
    9: 181,
}

EXPECTED_EVENTS = {
    1: "Pemilihan jasa konsultansi membutuhkan waktu lama",
    2: "Pencapaian output pelaksanaan kegiatan perlakuan Risiko rendah",
    3: "Pengadaan IPP membutuhkan waktu lama",
    4: "Penyelesaian pekerjaan dan penagihan terlambat",
    5: "Penyelesaian BID Doc dan HPE terlambat",
    6: "Pengadaan Proyek EPC & Non EPC membutuhkan waktu lama",
    7: "Keterlambatan penagihan oleh pihak ketiga",
    8: "Kurangnya kepedulian pegawai terhadap program HC",
    9: "Keterlambatan penyelesaian laporan",
}

SOURCE_IIIA = {6: {1: {'source_row': 11,
         'event': 'Pemilihan jasa konsultansi membutuhkan waktu lama',
         'jenis': 'Kualitatif',
         'assumption': 'Nilai dampak masih sama dengan posisi inhern dikarenakan mitigasi belum semuanya dilakukan',
         'nilai_dampak': None,
         'skala_dampak': 4,
         'nilai_probabilitas': 0.65,
         'skala_probabilitas': 4,
         'eksposur': 4340342760,
         'score': 19,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     2: {'source_row': 12,
         'event': 'Pencapaian output pelaksanaan kegiatan perlakuan Risiko rendah',
         'jenis': 'Kualitatif',
         'assumption': 'Nilai dampak masih sama karena laporan risiko dimulai april 2026',
         'nilai_dampak': None,
         'skala_dampak': 4,
         'nilai_probabilitas': 0.65,
         'skala_probabilitas': 4,
         'eksposur': 4340342760,
         'score': 19,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     3: {'source_row': 13,
         'event': 'Pengadaan IPP membutuhkan waktu lama',
         'jenis': 'Kualitatif',
         'assumption': 'Nilai dampak masih sama dengan posisi inhern dikarenakan mitigasi belum semuanya dilakukan',
         'nilai_dampak': None,
         'skala_dampak': 4,
         'nilai_probabilitas': 0.7,
         'skala_probabilitas': 4,
         'eksposur': 4674215280,
         'score': 19,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     4: {'source_row': 14,
         'event': 'Penyelesaian pekerjaan dan penagihan terlambat',
         'jenis': 'Kualitatif',
         'assumption': 'sd Juni 2026 Nilai dampak masih sama dikarenakan mitigasi belum semuanya dilakukan namun '
                       'realasasi on track terhadap target',
         'nilai_dampak': None,
         'skala_dampak': 4,
         'nilai_probabilitas': 0.75,
         'skala_probabilitas': 4,
         'eksposur': 5008087800,
         'score': 14,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     5: {'source_row': 15,
         'event': 'Penyelesaian BID Doc dan HPE terlambat',
         'jenis': 'Kualitatif',
         'assumption': 'sd Juni 2026 Nilai dampak masih sama dikarenakan mitigasi belum semuanya dilakukan namun '
                       'realasasi on track terhadap target',
         'nilai_dampak': None,
         'skala_dampak': 4,
         'nilai_probabilitas': 0.7,
         'skala_probabilitas': 4,
         'eksposur': 4674215280,
         'score': 19,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     6: {'source_row': 16,
         'event': 'Pengadaan Proyek EPC & Non EPC membutuhkan waktu lama',
         'jenis': 'Kualitatif',
         'assumption': 'sd Juni 2026 Nilai dampak masih sama dikarenakan mitigasi belum semuanya dilakukan namun '
                       'realasasi on track terhadap target',
         'nilai_dampak': None,
         'skala_dampak': 5,
         'nilai_probabilitas': 0.8,
         'skala_probabilitas': 4,
         'eksposur': 6677450400,
         'score': 24,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     7: {'source_row': 17,
         'event': 'Keterlambatan penagihan oleh pihak ketiga',
         'jenis': 'Kualitatif',
         'assumption': 'sd Juni 2026 Nilai dampak masih sama dikarenakan mitigasi belum semuanya dilakukan namun '
                       'realasasi on track terhadap target',
         'nilai_dampak': None,
         'skala_dampak': 4,
         'nilai_probabilitas': 0.8,
         'skala_probabilitas': 4,
         'eksposur': 5341960320,
         'score': 19,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     8: {'source_row': 18,
         'event': 'Kurangnya kepedulian pegawai terhadap program HC',
         'jenis': 'Kualitatif',
         'assumption': 'sd Juni 2026 Nilai dampak masih sama dikarenakan mitigasi belum semuanya dilakukan namun '
                       'realasasi on track terhadap target',
         'nilai_dampak': None,
         'skala_dampak': 4,
         'nilai_probabilitas': 0.7,
         'skala_probabilitas': 4,
         'eksposur': 4674215280,
         'score': 19,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     9: {'source_row': 19,
         'event': 'Keterlambatan penyelesaian laporan',
         'jenis': 'Kualitatif',
         'assumption': 'sd Juni 2026 Nilai dampak mengalami dikarenakan mitigasi belum semuanya dilakukan namun '
                       'realasasi on track terhadap target',
         'nilai_dampak': None,
         'skala_dampak': 4,
         'nilai_probabilitas': 0.7,
         'skala_probabilitas': 4,
         'eksposur': 4674215280,
         'score': 19,
         'level_bumn': None,
         'effectiveness': 'Efektif'}},
 7: {1: {'source_row': 11,
         'event': 'Pemilihan jasa konsultansi membutuhkan waktu lama',
         'jenis': 'Kualitatif',
         'assumption': 'Nilai dampak masih sama dengan posisi inhern dikarenakan mitigasi belum semuanya dilakukan',
         'nilai_dampak': None,
         'skala_dampak': None,
         'nilai_probabilitas': None,
         'skala_probabilitas': None,
         'eksposur': None,
         'score': None,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     2: {'source_row': 12,
         'event': 'Pencapaian output pelaksanaan kegiatan perlakuan Risiko rendah',
         'jenis': 'Kualitatif',
         'assumption': 'Nilai dampak masih sama karena laporan risiko dimulai april 2026',
         'nilai_dampak': None,
         'skala_dampak': None,
         'nilai_probabilitas': None,
         'skala_probabilitas': None,
         'eksposur': None,
         'score': None,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     3: {'source_row': 13,
         'event': 'Pengadaan IPP membutuhkan waktu lama',
         'jenis': 'Kualitatif',
         'assumption': 'Nilai dampak masih sama dengan posisi inhern dikarenakan mitigasi belum semuanya dilakukan',
         'nilai_dampak': None,
         'skala_dampak': None,
         'nilai_probabilitas': None,
         'skala_probabilitas': None,
         'eksposur': None,
         'score': None,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     4: {'source_row': 14,
         'event': 'Penyelesaian pekerjaan dan penagihan terlambat',
         'jenis': 'Kualitatif',
         'assumption': 'sd Juni 2026 Nilai dampak masih sama dikarenakan mitigasi belum semuanya dilakukan namun '
                       'realasasi on track terhadap target',
         'nilai_dampak': None,
         'skala_dampak': None,
         'nilai_probabilitas': None,
         'skala_probabilitas': None,
         'eksposur': None,
         'score': None,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     5: {'source_row': 15,
         'event': 'Penyelesaian BID Doc dan HPE terlambat',
         'jenis': 'Kualitatif',
         'assumption': 'sd Juni 2026 Nilai dampak masih sama dikarenakan mitigasi belum semuanya dilakukan namun '
                       'realasasi on track terhadap target',
         'nilai_dampak': None,
         'skala_dampak': None,
         'nilai_probabilitas': None,
         'skala_probabilitas': None,
         'eksposur': None,
         'score': None,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     6: {'source_row': 16,
         'event': 'Pengadaan Proyek EPC & Non EPC membutuhkan waktu lama',
         'jenis': 'Kualitatif',
         'assumption': 'sd Juni 2026 Nilai dampak masih sama dikarenakan mitigasi belum semuanya dilakukan namun '
                       'realasasi on track terhadap target',
         'nilai_dampak': None,
         'skala_dampak': None,
         'nilai_probabilitas': None,
         'skala_probabilitas': None,
         'eksposur': None,
         'score': None,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     7: {'source_row': 17,
         'event': 'Keterlambatan penagihan oleh pihak ketiga',
         'jenis': 'Kualitatif',
         'assumption': 'sd Juni 2026 Nilai dampak masih sama dikarenakan mitigasi belum semuanya dilakukan namun '
                       'realasasi on track terhadap target',
         'nilai_dampak': None,
         'skala_dampak': None,
         'nilai_probabilitas': None,
         'skala_probabilitas': None,
         'eksposur': None,
         'score': None,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     8: {'source_row': 18,
         'event': 'Kurangnya kepedulian pegawai terhadap program HC',
         'jenis': 'Kualitatif',
         'assumption': 'sd Juni 2026 Nilai dampak masih sama dikarenakan mitigasi belum semuanya dilakukan namun '
                       'realasasi on track terhadap target',
         'nilai_dampak': None,
         'skala_dampak': None,
         'nilai_probabilitas': None,
         'skala_probabilitas': None,
         'eksposur': None,
         'score': None,
         'level_bumn': None,
         'effectiveness': 'Efektif'},
     9: {'source_row': 19,
         'event': 'Keterlambatan penyelesaian laporan',
         'jenis': 'Kualitatif',
         'assumption': 'sd Juni 2026 Nilai dampak mengalami dikarenakan mitigasi belum semuanya dilakukan namun '
                       'realasasi on track terhadap target',
         'nilai_dampak': None,
         'skala_dampak': None,
         'nilai_probabilitas': None,
         'skala_probabilitas': None,
         'eksposur': None,
         'score': None,
         'level_bumn': None,
         'effectiveness': 'Efektif'}}}

SOURCE_IIIB = [{'source_row': 10,
  'risk_no': 1,
  'event': 'Pemilihan jasa konsultansi membutuhkan waktu lama',
  'treatment': 'Mempersiapkan dokumen TOR pengadaan sebaik mungkin dan koordinasi dengan BID STRADA',
  'planned_output': 'Dokumen Pengadaan',
  'planned_cost': 4654244565,
  'actual_treatment': 'Penyampaian Pengadaan Jasa Konsultansi FS  ',
  'actual_output': 'Dokumen FS',
  'actual_cost': 915950000,
  'source_serapan': 0.1967988547245583,
  'pic': None,
  'timeline': [None, None, 1, 1, 1, 1, None, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.2, 2: 0.4, 3: None, 4: None},
  'kri': 'Usulan pengadaan ',
  'unit': 'bulan',
  'threshold_aman': 'Mei',
  'threshold_hati_hati': '>Mei',
  'threshold_bahaya': '>Mei',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 11,
  'risk_no': 2,
  'event': 'Pencapaian output pelaksanaan kegiatan perlakuan Risiko rendah',
  'treatment': 'Memastikan seluruh mitigasi tereksekusi tepat waktu',
  'planned_output': 'Laporan bulanan',
  'planned_cost': 0,
  'actual_treatment': 'Laporan update mitigasi bulan Juni  2026',
  'actual_output': 'ND Laporan Bulanan',
  'actual_cost': 0,
  'source_serapan': '-',
  'pic': None,
  'timeline': [None, None, None, 1, 1, 1, None, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.25, 2: 0.45, 3: None, 4: None},
  'kri': 'Persentase penyelesaian mitigasi',
  'unit': 'Persen',
  'threshold_aman': 95,
  'threshold_hati_hati': 80,
  'threshold_bahaya': '<80',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 12,
  'risk_no': 3,
  'event': 'Pengadaan IPP membutuhkan waktu lama',
  'treatment': 'Koordinasi intens dengan BID STRADA\n',
  'planned_output': 'Dokumen pengadaan IPP',
  'planned_cost': 1055690000,
  'actual_treatment': '1. PLTS 100 MW: Pemasukan dokumen peserta tender\n'
                      '2. PLTGU Batam 3 dan 4 :Pengadaan baru dengan metode lelang terbuka\n'
                      '3. PLTU 2x65 MW : ',
  'actual_output': 'TOR dan RAB',
  'actual_cost': 91676000,
  'source_serapan': 0.08683988670916652,
  'pic': None,
  'timeline': [1, 1, 1, 1, 1, 1, None, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.3, 2: 0.33, 3: None, 4: None},
  'kri': 'Durasi pengadaan',
  'unit': 'Durasi (bulan)',
  'threshold_aman': 4,
  'threshold_hati_hati': 5,
  'threshold_bahaya': '>5',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 13,
  'risk_no': 4,
  'event': 'Penyelesaian pekerjaan dan penagihan terlambat',
  'treatment': 'Koordinasi intens dalam penyelesaian dan penagihan\n',
  'planned_output': 'Laporan SKAI dan SKAO',
  'planned_cost': 1973889500,
  'actual_treatment': 'Realisasi pembayaran s.d bulan Mei 2026',
  'actual_output': 'Laporan SKAI dan SKAO',
  'actual_cost': 1973889500,
  'source_serapan': 1,
  'pic': None,
  'timeline': [None, None, 1, 1, 1, 1, None, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.1, 2: 0.4, 3: None, 4: None},
  'kri': 'Persentase rupiah sinergi',
  'unit': 'persen',
  'threshold_aman': 100,
  'threshold_hati_hati': '<100',
  'threshold_bahaya': '<100',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 14,
  'risk_no': 5,
  'event': 'Penyelesaian BID Doc dan HPE terlambat',
  'treatment': 'Pengadaan kontrak BID Doc dan HPE serta koordinasi penyelesaian pekerjaan',
  'planned_output': 'Dokumen BID Doc dan HPE',
  'planned_cost': 15706948164,
  'actual_treatment': 'Penyampaian Pengadaan Bid Doc dan HPE ',
  'actual_output': 'TOR dan RAB',
  'actual_cost': 14097968464,
  'source_serapan': 0.8975625510952059,
  'pic': None,
  'timeline': [None, None, 1, 1, 1, 1, None, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.2, 2: 0.3, 3: None, 4: None},
  'kri': 'Penyelesaian pekerjaan',
  'unit': 'Durasi (bulan)',
  'threshold_aman': 6,
  'threshold_hati_hati': 7,
  'threshold_bahaya': '>7',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 15,
  'risk_no': 6,
  'event': 'Pengadaan Proyek EPC & Non EPC membutuhkan waktu lama',
  'treatment': 'Pembangunan Pembangkit PLTGU Batam#2 150 MW',
  'planned_output': 'Dokumen BID Doc dan HPE',
  'planned_cost': 2495479500,
  'actual_treatment': '-Dokumen FS  PLTGU Batam#2 150 MW sudah disampaikan PLN E per tanggal 4 Maret 2026\n'
                      '-Finalisasi Bid doc dengan PLN E\n',
  'actual_output': 'Dokumen BID Doc dan HPE',
  'actual_cost': 1693104500,
  'source_serapan': 0.67846860693506,
  'pic': None,
  'timeline': [None, None, 1, 1, 1, 1, None, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.2, 2: 0.33, 3: None, 4: None},
  'kri': 'BID Doc dan HPE',
  'unit': 'Durasi (bulan)',
  'threshold_aman': 4,
  'threshold_hati_hati': 5,
  'threshold_bahaya': '>5',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 16,
  'risk_no': 6,
  'event': 'Pengadaan Proyek EPC & Non EPC membutuhkan waktu lama',
  'treatment': 'Pembangunan Transmisi 150 KV Nongsa-NDP-Sri Rejeki-Kabil',
  'planned_output': 'TOR dan RAB',
  'planned_cost': 1948294565,
  'actual_treatment': 'Saat ini dalam tahap pengadaan FS di STRADA',
  'actual_output': 'TOR dan RAB',
  'actual_cost': None,
  'source_serapan': 0,
  'pic': None,
  'timeline': [None, None, 1, 1, 1, 1, 1, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.2, 2: 0.3, 3: None, 4: None},
  'kri': 'TOR dan RAB',
  'unit': 'Durasi (bulan)',
  'threshold_aman': 4,
  'threshold_hati_hati': 5,
  'threshold_bahaya': '>5',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 17,
  'risk_no': 6,
  'event': 'Pengadaan Proyek EPC & Non EPC membutuhkan waktu lama',
  'treatment': 'Pembangunan Pipa Gas Panaran-Kabil',
  'planned_output': 'Dokumen Feed dan HPE',
  'planned_cost': 4033023500,
  'actual_treatment': '-Dokumen FS Pipa Gas Panaran-Kabil sudah disampaikan PLN E per tanggal 11 Februari 2026\n'
                      '-Penyusuna Bid doc On Progress\n',
  'actual_output': 'Dokumen Feed dan HPE',
  'actual_cost': 3226418800,
  'source_serapan': 0.8,
  'pic': None,
  'timeline': [None, 1, 1, 1, 1, 1, 1, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.2, 2: 0.3, 3: None, 4: None},
  'kri': 'Dokumen Feed dan HPE',
  'unit': 'Durasi (bulan)',
  'threshold_aman': 4,
  'threshold_hati_hati': 5,
  'threshold_bahaya': '>5',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 18,
  'risk_no': 6,
  'event': 'Pengadaan Proyek EPC & Non EPC membutuhkan waktu lama',
  'treatment': 'Pengadaan Battery Energy Storage System (BESS) 15 MWh',
  'planned_output': 'Dokumen Kontrak',
  'planned_cost': 4200000000,
  'actual_treatment': '-Sudah menyurati PLN Litbang terkat penampatan lokasi BESS \n'
                      '-Kajian Grid Impact Study dengan PUSLITBANG ',
  'actual_output': 'Dokumen Kontrak',
  'actual_cost': 4200000000,
  'source_serapan': 1,
  'pic': None,
  'timeline': [None, None, None, 1, 1, 1, 1, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.2, 2: 0.25, 3: None, 4: None},
  'kri': 'Dokumen Kontrak',
  'unit': 'Durasi (bulan)',
  'threshold_aman': 4,
  'threshold_hati_hati': 5,
  'threshold_bahaya': '>5',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 19,
  'risk_no': 6,
  'event': 'Pengadaan Proyek EPC & Non EPC membutuhkan waktu lama',
  'treatment': 'Pengadaan Battery Energy Storage System (BESS) 100 MW/100 MWh',
  'planned_output': 'Dokumen FS',
  'planned_cost': 560000000,
  'actual_treatment': 'Menunggu lokasi PLTS 100Mwh',
  'actual_output': 'Dokumen FS',
  'actual_cost': 560000000,
  'source_serapan': 1,
  'pic': None,
  'timeline': [None, 1, 1, 1, 1, 1, 1, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.05, 2: 0.25, 3: None, 4: None},
  'kri': 'Kontrak FS',
  'unit': 'Durasi (bulan)',
  'threshold_aman': 4,
  'threshold_hati_hati': 5,
  'threshold_bahaya': '>5',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 20,
  'risk_no': 6,
  'event': 'Pengadaan Proyek EPC & Non EPC membutuhkan waktu lama',
  'treatment': 'Pembangunan Bay Trafo 7x60 MVA',
  'planned_output': 'Dokumen Penunjukan',
  'planned_cost': 4591095164,
  'actual_treatment': 'Penyusunan RKS pembangunan pondasi trafo dan bay trafo oleh BID STRADA\n',
  'actual_output': 'Dokumen Penunjukan',
  'actual_cost': 4591095164,
  'source_serapan': 1,
  'pic': None,
  'timeline': [1, 1, 1, 1, 1, 1, 1, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.2, 2: 0.3, 3: None, 4: None},
  'kri': 'Kontrak Pengadaan ',
  'unit': 'Durasi (bulan)',
  'threshold_aman': 4,
  'threshold_hati_hati': 5,
  'threshold_bahaya': '>5',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 21,
  'risk_no': 6,
  'event': 'Pengadaan Proyek EPC & Non EPC membutuhkan waktu lama',
  'treatment': 'Pembangunan Gardu Induk Nongsa Digital Park (NDP)',
  'planned_output': 'Dokumen Kontrak',
  'planned_cost': 1790000000,
  'actual_treatment': '-Saat ini dalam tahap pengadaan FS di STRADA\n'
                      '-Evaluasi dokumen kualifikasi untuk konsultan FS Bid Doc dan HPE',
  'actual_output': 'Dokumen Kontrak',
  'actual_cost': None,
  'source_serapan': 0,
  'pic': None,
  'timeline': [1, 1, 1, 1, 1, 1, 1, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.2, 2: 0.3, 3: None, 4: None},
  'kri': 'Dokumen Kontrak',
  'unit': 'Durasi (bulan)',
  'threshold_aman': 4,
  'threshold_hati_hati': 5,
  'threshold_bahaya': '>5',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 22,
  'risk_no': 6,
  'event': 'Pengadaan Proyek EPC & Non EPC membutuhkan waktu lama',
  'treatment': 'Pembangunan GI 150 kV Panaran Baru',
  'planned_output': 'Dokumen FS',
  'planned_cost': 355950000,
  'actual_treatment': 'Dokumen FS GI Panaran Baru sudah disampaikan PT SI per tanggal 26 Februari 2026',
  'actual_output': 'Dokumen FS',
  'actual_cost': 355950000,
  'source_serapan': 1,
  'pic': None,
  'timeline': [None, 1, 1, 1, 1, 1, 1, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.2, 2: 0.3, 3: None, 4: None},
  'kri': 'Kontrak FS',
  'unit': 'Durasi (bulan)',
  'threshold_aman': 4,
  'threshold_hati_hati': 5,
  'threshold_bahaya': '>5',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 23,
  'risk_no': 6,
  'event': 'Pengadaan Proyek EPC & Non EPC membutuhkan waktu lama',
  'treatment': 'Rekonduktoring Transmisi Batu Besar - Nongsa',
  'planned_output': 'Bid Doc dan HPE',
  'planned_cost': 387350000,
  'actual_treatment': 'Finalisasi BID Doc oleh STRADA',
  'actual_output': 'Bid Doc dan HPE',
  'actual_cost': 387350000,
  'source_serapan': 1,
  'pic': None,
  'timeline': [None, 1, 1, 1, 1, 1, 1, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.2, 2: 0.3, 3: None, 4: None},
  'kri': 'Bid Doc dan HPE',
  'unit': 'Durasi (bulan)',
  'threshold_aman': 4,
  'threshold_hati_hati': 5,
  'threshold_bahaya': '>5',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 24,
  'risk_no': 7,
  'event': 'Keterlambatan penagihan oleh pihak ketiga',
  'treatment': 'Koordinasi intens dengan pihak ketiga dalam penyelesaian pekerjaan\n',
  'planned_output': 'Surat Permohonan Pembayaran dari Vendor',
  'planned_cost': 20361192729,
  'actual_treatment': 'Koordinasi dengan pihak ketiga terkait pembayaran pekerjaan',
  'actual_output': 'Surat Permohonan Pembayaran dari Vendor',
  'actual_cost': 15013918464,
  'source_serapan': 0.737379124289512,
  'pic': None,
  'timeline': [1, 1, 1, 1, 1, 1, 1, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.2, 2: 0.3, 3: None, 4: None},
  'kri': 'Persentase penyerapan AKI',
  'unit': 'Persen',
  'threshold_aman': '95-100',
  'threshold_hati_hati': 95,
  'threshold_bahaya': '<95',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 25,
  'risk_no': 8,
  'event': 'Kurangnya kepedulian pegawai terhadap program HC',
  'treatment': 'Melakukan penarikan data berulang dihari pertama',
  'planned_output': 'Monitoring checkin komando',
  'planned_cost': 0,
  'actual_treatment': 'Checkin Komando dilakukan setiap senin',
  'actual_output': 'Monitoring Checkin Komando',
  'actual_cost': '-',
  'source_serapan': '-',
  'pic': None,
  'timeline': [1, 1, 1, 1, 1, 1, 1, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.2, 2: 0.45, 3: None, 4: None},
  'kri': 'Penyelesaian checkin komando 100%',
  'unit': 'Waktu (hari)',
  'threshold_aman': 2,
  'threshold_hati_hati': 4,
  'threshold_bahaya': 7,
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}},
 {'source_row': 26,
  'risk_no': 9,
  'event': 'Keterlambatan penyelesaian laporan',
  'treatment': 'Memastikan penyampaian laporan tepat waktu',
  'planned_output': 'Laporan bulanan',
  'planned_cost': 0,
  'actual_treatment': 'Laporan update mitigasi bulan Juni  2026',
  'actual_output': 'ND Laporan Bulanan',
  'actual_cost': '-',
  'source_serapan': '-',
  'pic': None,
  'timeline': [1, 1, 1, 1, 1, 1, 1, None, None, None, None, None],
  'status': '2. Continue',
  'status_explanation': 'Mitigasi akan berlanjut sampai sasaran pada KM tercapai',
  'progress': {1: 0.2, 2: 0.45, 3: None, 4: None},
  'kri': 'Penyelesaian laporan',
  'unit': 'Tanggal (bulan berjalan)',
  'threshold_aman': '1-6',
  'threshold_hati_hati': 7,
  'threshold_bahaya': '>7',
  'month_kri': {6: {'threshold': '3. Hijau', 'score': None}, 7: {'threshold': '3. Hijau', 'score': None}}}]


def D(value):
    if value in (None, ""):
        return None
    if isinstance(value, str) and value.strip() in {"-", "n/a", "N/A"}:
        return None
    return Decimal(str(value))


def pct_from_fraction(value):
    d = D(value)
    if d is None:
        return None
    if Decimal("-1") <= d <= Decimal("1"):
        d *= Decimal("100")
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_status(value):
    text = " ".join(str(value or "").lower().split())
    if "discontinue" in text:
        return "discontinue"
    if "revisi" in text or "revisi" in text:
        return "revisi"
    if "continue" in text:
        return "continue"
    return None


def normalize_effectiveness(value):
    text = " ".join(str(value or "").lower().split())
    if not text:
        return None
    if "tidak" in text and "efektif" in text:
        return "tidak_efektif"
    if "cukup" in text and "efektif" in text:
        return "cukup_efektif"
    if "efektif" in text:
        return "efektif"
    return None


def validate_source_files(june: Path, july: Path):
    for month, path in ((6, june), (7, july)):
        if not path.exists():
            raise FileNotFoundError(path)
        digest = sha256(path)
        expected = EXPECTED_HASHES[month]
        print(f"SOURCE {month:02d}: {path}")
        print(f"  SHA256: {digest}")
        if digest != expected:
            raise RuntimeError(
                f"SHA256 source month={month} tidak cocok. "
                f"expected={expected}, got={digest}"
            )


def sqlite_path() -> Path:
    engine = settings.DATABASES["default"]["ENGINE"]
    if "sqlite" not in engine:
        raise RuntimeError(
            f"Importer ini divalidasi untuk SQLite production; engine={engine}"
        )
    return Path(settings.DATABASES["default"]["NAME"]).resolve()


def db_integrity(label: str):
    db = sqlite_path()
    con = sqlite3.connect(str(db))
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        con.close()
    print(f"{label} integrity_check : {integrity}")
    print(f"{label} foreign_key_check: {len(fk)} error")
    if integrity != "ok" or fk:
        raise RuntimeError(f"Database integrity gagal pada {label}")


def backup_sqlite() -> Path:
    src = sqlite_path()
    backup_dir = Path("/home/adminsvr/backup")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = backup_dir / f"db_before_import_mrr_renkin_jun_jul_2026_{stamp}.sqlite3"
    shutil.copy2(src, dst)
    return dst


def get_scale_id(model, level):
    if level in (None, ""):
        return None
    obj = model.objects.filter(urutan=int(level)).first()
    if obj is None:
        raise RuntimeError(
            f"Master scale {model.__name__} urutan={level} tidak ditemukan."
        )
    return obj.pk


def validate_production_baseline():
    profile = ReAssessmentSummary.objects.select_related("unit_bisnis").get(pk=PROFILE_ID)
    if profile.judul != "Profil Risiko RENKIN":
        raise RuntimeError(f"Profile title berubah: {profile.judul!r}")
    if profile.tahun != 2026:
        raise RuntimeError(f"Profile year berubah: {profile.tahun!r}")
    if profile.unit_bisnis_id != UNIT_GROUP_ID:
        raise RuntimeError(
            f"Profile unit berubah: id={profile.unit_bisnis_id}, expected={UNIT_GROUP_ID}"
        )

    km = KontrakManajemen.objects.get(pk=KM_ID)
    if km.judul != "VPREN" or km.status != "Final":
        raise RuntimeError(
            f"KM guard gagal: id={km.pk} judul={km.judul!r} status={km.status!r}"
        )

    year = TahunBuku.objects.get(pk=YEAR_BOOK_ID)
    if year.tahun != 2026:
        raise RuntimeError(f"TahunBuku guard gagal: {year}")

    active_ids = set(
        ReAssessmentItem.objects.filter(summary_id=PROFILE_ID, is_active=True)
        .values_list("id", flat=True)
    )
    expected_active_ids = {
        165, 166, 167, 168, 169, 170, 171, 172, 173,
        174, 175, 176, 177, 178, 179, 180, 181,
    }
    if active_ids != expected_active_ids:
        raise RuntimeError(
            "Active RENKIN profile IDs berubah. "
            f"expected={sorted(expected_active_ids)} got={sorted(active_ids)}"
        )

    reps = {}
    for risk_no, re_id in REPRESENTATIVES.items():
        item = ReAssessmentItem.objects.get(
            pk=re_id, summary_id=PROFILE_ID, is_active=True
        )
        if item.peristiwa_risiko != EXPECTED_EVENTS[risk_no]:
            raise RuntimeError(
                f"Representative risk {risk_no} event berubah: "
                f"RE={re_id} {item.peristiwa_risiko!r}"
            )
        if item.no_item != risk_no:
            raise RuntimeError(
                f"Representative risk {risk_no} no_item={item.no_item!r}"
            )
        reps[risk_no] = item

    # Historical convention guard.
    expected_rep_ids = list(REPRESENTATIVES.values())
    for report_id, period_code in ((7, "2026-03"), (8, "2026-04")):
        r = MonthlyRiskReport.objects.get(pk=report_id, reassessment_id=PROFILE_ID)
        ids = list(
            MonthlyRiskReportItem.objects.filter(report_id=report_id)
            .order_by("id")
            .values_list("risk_event_id", flat=True)
        )
        if ids != expected_rep_ids:
            raise RuntimeError(
                f"Historical MRR {report_id} representative convention berubah: {ids}"
            )
        print(
            f"HISTORICAL MRR {report_id} | {period_code} | "
            f"9 representatives OK"
        )

    for month, spec in PERIODS.items():
        p = PeriodeLaporan.objects.get(pk=spec["id"])
        if p.kode_periode != spec["code"]:
            raise RuntimeError(
                f"Period guard month={month}: id={p.pk} code={p.kode_periode!r}"
            )
        existing = MonthlyRiskReport.objects.filter(
            reassessment_id=PROFILE_ID,
            tahun_buku_id=YEAR_BOOK_ID,
            periode_id=p.pk,
        )
        if existing.exists():
            raise RuntimeError(
                f"Target MRR month={month} sudah ada: "
                f"ids={list(existing.values_list('id', flat=True))}"
            )

    User = get_user_model()
    prepared = User.objects.get(pk=PREPARED_BY_ID)
    print(
        f"PROFILE: id={profile.pk} | {profile.judul} | "
        f"unit={profile.unit_bisnis} | active={len(active_ids)}"
    )
    print(f"KM: id={km.pk} | {km.judul} | {km.status}")
    print(f"PREPARED BY: id={prepared.pk} | {prepared.get_username()}")

    # Known anomaly must remain profile-only and must never be copied.
    anomalous = ReAssessmentItem.objects.get(pk=177)
    print(f"PROFILE NOTE: RE177 PIC={anomalous.pic!r} (will NOT be copied)")
    return profile, km, year, reps


def grouped_iiib():
    groups = defaultdict(list)
    for row in SOURCE_IIIB:
        groups[int(row["risk_no"])].append(row)
    if sorted(groups) != list(range(1, 10)):
        raise RuntimeError(f"Source III.B risk groups invalid: {sorted(groups)}")
    if len(SOURCE_IIIB) != 17 or len(groups[6]) != 9:
        raise RuntimeError(
            f"Source III.B structure changed: rows={len(SOURCE_IIIB)} "
            f"risk6={len(groups[6])}"
        )
    return groups


def pair_treatment_text(rows):
    blocks = []
    for idx, row in enumerate(rows, start=1):
        actual = row.get("actual_treatment")
        if actual in (None, ""):
            continue
        blocks.append(
            f"{idx:02d}. Rencana: {str(row.get('treatment') or '').strip()}\n"
            f"    Realisasi: {str(actual).strip()}"
        )
    return "\n\n".join(blocks) or None


def pair_output_text(rows):
    blocks = []
    for idx, row in enumerate(rows, start=1):
        actual = row.get("actual_output")
        if actual in (None, ""):
            continue
        blocks.append(
            f"{idx:02d}. Output rencana: {str(row.get('planned_output') or '').strip()}\n"
            f"    Realisasi output: {str(actual).strip()}"
        )
    return "\n\n".join(blocks) or None


def kri_detail_text(rows, month):
    blocks = []
    for idx, row in enumerate(rows, start=1):
        current = row["month_kri"][month]
        blocks.append(
            f"{idx:02d}. KRI: {str(row.get('kri') or '').strip()}"
            f" | Unit: {str(row.get('unit') or '').strip()}"
            f" | Aman: {row.get('threshold_aman')}"
            f" | Hati-hati: {row.get('threshold_hati_hati')}"
            f" | Bahaya: {row.get('threshold_bahaya')}"
            f" | Realisasi threshold: {current.get('threshold')}"
            f" | Skor: {current.get('score')}"
        )
    return "\n".join(blocks)


def aggregate_cost(rows, key):
    values = [D(r.get(key)) for r in rows]
    numeric = [v for v in values if v is not None]
    if not numeric:
        return None
    return sum(numeric, Decimal("0"))


def aggregate_progress(rows, quarter):
    values = [D(r["progress"].get(quarter)) for r in rows]
    values = [v for v in values if v is not None]
    if not values:
        return None
    avg = sum(values, Decimal("0")) / Decimal(len(values))
    return pct_from_fraction(avg)


def aggregate_timeline(rows, report_month):
    out = []
    for month_idx in range(1, 13):
        if month_idx > report_month:
            out.append(0)
            continue
        flag = any(bool(r["timeline"][month_idx - 1]) for r in rows)
        out.append(1 if flag else 0)
    return out


def common_status(rows):
    statuses = {normalize_status(r.get("status")) for r in rows}
    statuses.discard(None)
    if len(statuses) > 1:
        raise RuntimeError(f"Mixed source treatment statuses: {statuses}")
    return next(iter(statuses), None)


def common_explanation(rows):
    vals = []
    for r in rows:
        v = str(r.get("status_explanation") or "").strip()
        if v and v not in vals:
            vals.append(v)
    return "\n".join(vals) or None


def current_kri_threshold(rows, month):
    vals = []
    for row in rows:
        value = row["month_kri"][month].get("threshold")
        if value not in (None, ""):
            value = str(value).strip()
            if value not in vals:
                vals.append(value)
    if len(vals) > 1:
        # Preserve rather than inventing a single category.
        return " | ".join(vals)
    return vals[0] if vals else None


def create_report(month, year, km, reps, groups):
    spec = PERIODS[month]
    period = PeriodeLaporan.objects.get(pk=spec["id"])

    report = MonthlyRiskReport.objects.create(
        kode=spec["report_code"],
        tahun_buku=year,
        periode=period,
        unit=None,
        kontrak_manajemen=km,
        reassessment_id=PROFILE_ID,
        versi=1,
        status="draft",
        evidence_url="",
        prepared_by_id=PREPARED_BY_ID,
        total_risiko=9,
        total_high=0,
        total_mitigasi_terlambat=0,
        total_selesai=0,
    )

    quarter = 2 if month == 6 else 3

    print("\n" + "-" * 120)
    print(
        f"BUILD {spec['report_code']} | report_temp_id={report.pk} "
        f"| quarter=Q{quarter}"
    )

    for risk_no in range(1, 10):
        risk_event = reps[risk_no]
        residual = SOURCE_IIIA[month][risk_no]
        rows = groups[risk_no]

        if residual["event"] != EXPECTED_EVENTS[risk_no]:
            raise RuntimeError(
                f"III.A source event mismatch risk={risk_no}: {residual['event']!r}"
            )
        if any(r["event"] != EXPECTED_EVENTS[risk_no] for r in rows):
            raise RuntimeError(f"III.B source event mismatch risk={risk_no}")

        planned_cost = aggregate_cost(rows, "planned_cost")
        actual_cost = aggregate_cost(rows, "actual_cost")

        serapan = None
        if planned_cost is not None and planned_cost > 0 and actual_cost is not None:
            serapan = (
                actual_cost / planned_cost * Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        progress = aggregate_progress(rows, quarter)
        timeline = aggregate_timeline(rows, month)

        item = MonthlyRiskReportItem.objects.create(
            report=report,
            risk_event=risk_event,
            km_item_id=risk_event.km_item_id,
        )

        update = {
            "jenis_risiko": getattr(risk_event, "jenis_risiko", None),
            "realisasi_asumsi_dampak": residual["assumption"],
            "realisasi_nilai_dampak": D(residual["nilai_dampak"]),
            "realisasi_skala_dampak_id": get_scale_id(
                MasterSkalaDampak, residual["skala_dampak"]
            ),
            "realisasi_nilai_probabilitas": pct_from_fraction(
                residual["nilai_probabilitas"]
            ),
            "realisasi_skala_probabilitas_id": get_scale_id(
                MasterSkalaProbabilitas, residual["skala_probabilitas"]
            ),
            "realisasi_eksposur": D(residual["eksposur"]),
            "realisasi_skor_risiko": (
                int(residual["score"]) if residual["score"] not in (None, "") else None
            ),
            "realisasi_level_risiko": None,
            "realisasi_level_risiko_bumn": residual["level_bumn"],
            "efektivitas_perlakuan_risiko": normalize_effectiveness(
                residual["effectiveness"]
            ),
            "realisasi_rencana_perlakuan": pair_treatment_text(rows),
            "realisasi_output_perlakuan": pair_output_text(rows),
            "rencana_biaya_perlakuan": planned_cost,
            "realisasi_biaya_perlakuan": actual_cost,
            "persentase_serapan_biaya": serapan,
            "realisasi_pic": None,
            "realisasi_pic_organization_unit_id": None,
            "status_rencana_perlakuan": common_status(rows),
            "penjelasan_status_rencana": common_explanation(rows),
            "progress_pelaksanaan_percent": progress,
            "mitigation_progress_percent": progress,
            "realisasi_threshold_kri": current_kri_threshold(rows, month),
            "realisasi_nilai_kri": None,
            "realisasi_kri_text": kri_detail_text(rows, month),
            "realisasi_threshold_kri_skor": None,
        }
        for idx, flag in enumerate(timeline, start=1):
            update[f"realisasi_timeline_{idx}"] = flag

        MonthlyRiskReportItem.objects.filter(pk=item.pk).update(**update)

        print(
            f"R{risk_no} -> RE={risk_event.pk} | activities={len(rows)} "
            f"| planned={planned_cost} | actual={actual_cost} "
            f"| serapan={serapan} | progress={progress} "
            f"| KRI={update['realisasi_threshold_kri']!r} "
            f"| residual_score={update['realisasi_skor_risiko']}"
        )

    return report


def postcheck_report(report, month):
    items = list(
        MonthlyRiskReportItem.objects
        .filter(report=report)
        .select_related("risk_event")
        .order_by("id")
    )
    if len(items) != 9:
        raise RuntimeError(
            f"Postcheck month={month} items={len(items)}, expected 9."
        )

    ids = [x.risk_event_id for x in items]
    if ids != list(REPRESENTATIVES.values()):
        raise RuntimeError(
            f"Postcheck month={month} representative IDs mismatch: {ids}"
        )

    agg = MonthlyRiskReportItem.objects.filter(report=report).aggregate(
        planned=Sum("rencana_biaya_perlakuan"),
        actual=Sum("realisasi_biaya_perlakuan"),
    )
    expected_planned = Decimal("64113157687")
    expected_actual = Decimal("47107320892")
    if agg["planned"] != expected_planned:
        raise RuntimeError(
            f"Planned total month={month} {agg['planned']} != {expected_planned}"
        )
    if agg["actual"] != expected_actual:
        raise RuntimeError(
            f"Actual total month={month} {agg['actual']} != {expected_actual}"
        )

    qs = MonthlyRiskReportItem.objects.filter(report=report)
    kri_count = qs.filter(realisasi_threshold_kri="3. Hijau").count()
    if kri_count != 9:
        raise RuntimeError(
            f"KRI source threshold month={month} count={kri_count}, expected 9."
        )
    if qs.exclude(realisasi_nilai_kri__isnull=True).exists():
        raise RuntimeError("KRI numeric value should remain NULL; source score blank.")
    if qs.exclude(realisasi_pic__isnull=True).exists():
        raise RuntimeError("Source PIC is blank but non-null PIC was imported.")
    if qs.exclude(realisasi_pic_organization_unit__isnull=True).exists():
        raise RuntimeError("Source PIC org should remain NULL.")

    if month == 6:
        if qs.filter(realisasi_skala_dampak__isnull=False).count() != 9:
            raise RuntimeError("June Q2 residual scale impact not 9/9.")
        if qs.filter(realisasi_skala_probabilitas__isnull=False).count() != 9:
            raise RuntimeError("June Q2 residual probability scale not 9/9.")
        if qs.filter(realisasi_eksposur__isnull=False).count() != 9:
            raise RuntimeError("June Q2 exposure not 9/9.")
        if qs.filter(realisasi_skor_risiko__isnull=False).count() != 9:
            raise RuntimeError("June Q2 risk score not 9/9.")
        if qs.filter(progress_pelaksanaan_percent__isnull=False).count() != 9:
            raise RuntimeError("June Q2 progress not 9/9.")
    else:
        residual_nonnull = (
            qs.filter(realisasi_nilai_dampak__isnull=False).count()
            + qs.filter(realisasi_skala_dampak__isnull=False).count()
            + qs.filter(realisasi_nilai_probabilitas__isnull=False).count()
            + qs.filter(realisasi_skala_probabilitas__isnull=False).count()
            + qs.filter(realisasi_eksposur__isnull=False).count()
            + qs.filter(realisasi_skor_risiko__isnull=False).count()
        )
        if residual_nonnull != 0:
            raise RuntimeError(
                f"July Q3 residual source is blank but non-null count={residual_nonnull}."
            )
        if qs.filter(progress_pelaksanaan_percent__isnull=False).exists():
            raise RuntimeError("July Q3 source progress blank but value imported.")

    # No timeline beyond the report month.
    for item in items:
        for m in range(month + 1, 13):
            if getattr(item, f"realisasi_timeline_{m}"):
                raise RuntimeError(
                    f"Timeline month={month} item={item.pk} has future flag m={m}."
                )

    risk6 = qs.get(risk_event_id=REPRESENTATIVES[6])
    required_risk6_text = [
        "Pembangunan Pembangkit PLTGU Batam#2 150 MW",
        "Pembangunan Transmisi 150 KV Nongsa-NDP-Sri Rejeki-Kabil",
        "Pembangunan Pipa Gas Panaran-Kabil",
        "Pengadaan Battery Energy Storage System (BESS) 15 MWh",
        "Pengadaan Battery Energy Storage System (BESS) 100 MW/100 MWh",
        "Pembangunan Bay Trafo 7x60 MVA",
        "Pembangunan Gardu Induk Nongsa Digital Park (NDP)",
        "Pembangunan GI 150 kV Panaran Baru",
        "Rekonduktoring Transmisi Batu Besar - Nongsa",
    ]
    for text in required_risk6_text:
        if text not in (risk6.realisasi_rencana_perlakuan or ""):
            raise RuntimeError(f"Risk6 treatment missing from narrative: {text}")

    if MonthlyRiskReportChange.objects.filter(report=report).exists():
        raise RuntimeError("III.D should be empty.")
    if MonthlyRiskReportLossEvent.objects.filter(report=report).exists():
        raise RuntimeError("III.E should be empty.")

    print(
        f"POSTCHECK {report.kode} | id={report.pk} | items=9 "
        f"| planned={agg['planned']} | actual={agg['actual']} "
        f"| KRI=9 | III.D=0 | III.E=0"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--june", required=True, type=Path)
    parser.add_argument("--july", required=True, type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit June+July. Default is DRY-RUN rollback.",
    )
    args = parser.parse_args()

    june = args.june.expanduser().resolve()
    july = args.july.expanduser().resolve()
    mode = "APPLY" if args.apply else "DRY-RUN"

    print("=" * 120)
    print(f"IMPORT MRR BID RENKIN JUNI + JULI 2026 | MODE={mode}")
    print("=" * 120)

    validate_source_files(june, july)
    db_integrity("PRE")

    profile, km, year, reps = validate_production_baseline()
    groups = grouped_iiib()

    print("\nSOURCE STRUCTURE")
    print("III.A events per month : 9")
    print("III.B treatment rows    : 17")
    print("III.B risk6 activities  : 9")
    print("III.D rows              : 0")
    print("III.E rows              : 0")
    print("Expected planned/month  : 64113157687")
    print("Expected actual/month   : 47107320892")
    print("June Q2 residual        : populated scales/prob/exposure/score")
    print("July Q3 residual        : blank")
    print("June Q2 progress        : populated")
    print("July Q3 progress        : blank")

    if args.apply:
        backup = backup_sqlite()
        print("\nBACKUP DB:", backup)

    reports = []
    with transaction.atomic():
        # Lock critical production baseline only on APPLY.
        if args.apply:
            ReAssessmentSummary.objects.select_for_update().get(pk=PROFILE_ID)
            KontrakManajemen.objects.select_for_update().get(pk=KM_ID)

        for month in (6, 7):
            report = create_report(month, year, km, reps, groups)
            reports.append((month, report))
            postcheck_report(report, month)

        if not args.apply:
            transaction.set_rollback(True)
            print("\nDRY-RUN: transaction marked ROLLBACK.")

    if args.apply:
        db_integrity("POST")
        print("\n" + "=" * 120)
        print("APPLY BERHASIL")
        for month, report in reports:
            print(
                f"month={month:02d} | MRR ID={report.pk} | "
                f"code={report.kode} | status={report.status}"
            )
        print("=" * 120)
    else:
        # Verify rollback actually removed target reports.
        for month, spec in PERIODS.items():
            exists = MonthlyRiskReport.objects.filter(
                reassessment_id=PROFILE_ID,
                periode_id=spec["id"],
                tahun_buku_id=YEAR_BOOK_ID,
            ).exists()
            if exists:
                raise RuntimeError(
                    f"DRY-RUN rollback failed: target month={month} still exists."
                )
        db_integrity("POST-DRYRUN")
        print("\nDRY-RUN SELESAI - DATABASE TIDAK DIUBAH.")


if __name__ == "__main__":
    main()
