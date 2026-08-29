#!/usr/bin/env python3
"""
IMPORT LAPORAN MANAJEMEN RISIKO UB KITRANS JUNI 2026 - V8

Source:
  Laporan Manajemen Risiko UBKITRANS Juni 2026.xlsx

Validated production baseline:
- ReAssessmentSummary id=14 : Profil Risiko UBKITRANS
- Unit                      : UB KITRAN
- KM id=10                  : SMUPKITRANS (2026)
- Existing MRR              : Feb, Mar, Apr 2026
- June 2026 MRR             : NONE
- July 2026 MRR             : NONE
- Active legacy profile rows: 107

Validated source:
- III.A = 19 risk-event rows.
- III.A Q2 actual residual fields are BLANK for all 19 events.
- III.B = 40 unique source-cause groups.
- III.B = exactly 106 treatment/activity rows (rows with Rencana Perlakuan in col H).
- III.D = no populated source change row.
- III.E = no populated source loss-event row.

Profile resolution from audits V2-V4:
- 37/40 current source causes map exactly to production.
- Source cause 02 maps to RE=275 by exact event + cause code "b".
  Its production cause text is placeholder "UB KITRANS--b" and has no historical MRR refs.
  V8 updates only its cause text to the current source.
- Source cause 35 maps to RE=390 by exact event + cause code "ak".
  It has no historical MRR refs.
  V8 updates only its cause text to the current source.
- Source cause 09 / code "i" does not exist anywhere in profile history.
  V8 creates one current-source ReAssessmentItem by cloning same-event structure,
  with a new technical no_risiko key. Historical MRR rows are never modified.

IMPORTANT MONTH DECISION:
The user explicitly requested JUNI 2026. The workbook nevertheless contains
substantive July-2026 narrative/timeline updates.

V8 behavior:
- report period is June 2026;
- source free-text is preserved verbatim, including text that says "Juli 2026";
- Q2 treatment progress (col AE) is used for June progress;
- Q2 III.A residual values remain NULL because source Q2 is blank;
- timeline is clipped to Jan-Jun for the June report:
    source Jul-Dec flags are NOT copied into the June MRR.
  This is an explicit period-consistency transformation, not a silent source edit.

Aggregation:
- One MonthlyRiskReportItem per unique source cause => 40 items.
- 106 detailed source treatment rows are consolidated into those 40 items.
- Planned/actual treatment narratives preserve each detailed source row.
- Numeric planned costs are summed per cause.
- Numeric actual costs are summed per cause.
- Non-numeric values found in numeric source cost columns are preserved in
  penjelasan_status_rencana instead of being forced into Decimal fields.
- Q2 progress is the arithmetic mean of the source Q2 progress values that are
  actually populated for that cause. Blank Q2 progress cells are not converted to 0.
- KRI current threshold/value come from AM/AN. Source KRI name and threshold
  bands are preserved in realisasi_kri_text.

V8 fix:
- V5 stopped safely on jenis_existing_control because it is a ForeignKey.
- V6 then stopped safely on pos_anggaran for the same underlying reason.
- V7 fixed those relation assignments, but MonthlyRiskReportItem.save() then
  stopped on KRI evaluation because some UB KITRANS risk events do not have
  kri_threshold_direction configured.
- V8 preserves the source KRI value in realisasi_kri_text whenever the profile
  has no KRI threshold direction, and leaves realisasi_nilai_kri=NULL so the
  application does not fabricate/evaluate a threshold direction that is absent.
- If a profile row DOES have kri_threshold_direction configured, V8 may store
  the numeric KRI normally.

Safety:
- Default is DRY-RUN.
- --apply is required to write.
- SQLite backup + integrity_check before apply.
- transaction.atomic().
- Duplicate June MRR guard.
- Exact source/production identity checks before writes.
- Postcheck validates 40 items, 19 distinct source events, Q2 residual NULL,
  III.E=0, source corrections, and DB integrity.
"""

from __future__ import annotations

import argparse
import calendar
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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

from masterdata.models import TahunBuku, PeriodeLaporan
from monthly_report.models import (
    MonthlyRiskReport,
    MonthlyRiskReportItem,
    MonthlyRiskReportLossEvent,
)
from risk.models import ReAssessmentSummary, ReAssessmentItem

PROFILE_ID = 14
KM_ID = 10
YEAR = 2026
MONTH = 6
PERIOD_CODE = "2026-06"
REPORT_CODE = "MRR-KITRANS-2026-06"
PREPARED_BY_ID = 176

SOURCE_GROUPS = [{'source_risk_no': '1.0', 'event': 'Realisasi pengoperasian pembangkit pada sistem Batam-Bintan tidak berjalan sesuai dengan rencana', 'cause_no': 'a', 'cause_text': 'Penggunaan gas Surcharge akibat gangguan pembangkit non gas (PLTU) sehingga biaya gas tertimbang menjadi naik', 'rows': [{'source_row': 10, 'plan': 'Pengaturan nominasi dan pemakaian gas PGN, Petrochina dan Jadestone maksimal sebesar MDQ', 'planned_output': 'Nominasi Gas', 'planned_cost': '0.0', 'actual_plan': 'Pengaturan Nominasi Gas Jadestone (gas yang paling murah) pada MDQ', 'actual_output': 'tercapai', 'actual_cost': '0.0', 'source_absorption': '0.0', 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': 'Pemakaian gas Surcharge Harian', 'kri_unit': 'BBTUD', 'kri_safe': '0.0', 'kri_caution': '2.0', 'kri_danger': '5.0', 'kri_threshold_actual': 'Hijau', 'kri_value_actual': '0.0'}, {'source_row': 11, 'plan': 'Pengoptimalan line pack TGI atas gas Petrochina/Jadestone pada hari libur dan hari kerja', 'planned_output': 'Monitoring Line Pack', 'planned_cost': '0.0', 'actual_plan': 'Pengoptimalan line pack TGI atas gas Jadestone pada hari libur dan hari kerja', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': 'Hijau', 'kri_value_actual': None}, {'source_row': 12, 'plan': 'Mendorong Peningkatan Keandalan Pembangkit IPP dan Pengenaan Denda Daya Mampu/Outage', 'planned_output': 'BA Denda Daya Mampu', 'planned_cost': '0.0', 'actual_plan': 'Mendorong Peningkatan Keandalan Pembangkit IPP dan Pengenaan Denda Daya Mampu/Outage', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': 'Hijau', 'kri_value_actual': None}, {'source_row': 13, 'plan': 'Optimasi Pola pembebanan GT PLTGU Tanjung Uncang menyesuaikan kemampuan maksimum STG untuk memperoleh heatrate\xa0paling\xa0ideal.', 'planned_output': 'Realisasi pembebanan PLTGU Tanjung Uncang', 'planned_cost': '0.0', 'actual_plan': 'Optimasi Pola pembebanan GT PLTGU Tanjung Uncang menyesuaikan kemampuan maksimum STG untuk memperoleh heatrate paling ideal.', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': 'Hijau', 'kri_value_actual': None}]}, {'source_risk_no': '1.0', 'event': 'Realisasi pengoperasian pembangkit pada sistem Batam-Bintan tidak berjalan sesuai dengan rencana', 'cause_no': 'b', 'cause_text': 'Gangguan avaibility sumur gas Petrochina/Jadestone sehingga menggunakan gas interuptible PGN yang lebih  mahal', 'rows': [{'source_row': 14, 'plan': 'Melakukan Koordinasi lintas bidang dengan Divisi Perencanaan dan Divisi Operasi serta dengan pemasok gas', 'planned_output': 'Rakor Gas', 'planned_cost': '0.0', 'actual_plan': 'Melakukan Koordinasi lintas bidang dengan Divisi Perencanaan dan Divisi Operasi serta dengan pemasok gas', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': None, 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': 'Hijau', 'kri_value_actual': None}]}, {'source_risk_no': '1.0', 'event': 'Realisasi pengoperasian pembangkit pada sistem Batam-Bintan tidak berjalan sesuai dengan rencana', 'cause_no': 'c', 'cause_text': 'Pembatasan gas dari PGN sehingga harus mengoperasikan PLTD dengan biaya yang lebih mahal', 'rows': [{'source_row': 15, 'plan': 'Koordinasi dengan PGN untuk menaikkan alokasi gas sesuai PJBG', 'planned_output': 'Koordinasi', 'planned_cost': '0.0', 'actual_plan': 'Melakukan Koordinasi dengan PGN untuk menaikkan alokasi gas sesuai PJBG', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': 'Hijau', 'kri_value_actual': None}, {'source_row': 16, 'plan': 'Koordinasi dengan PT EPI untuk Swap gas PLN EPI dari Sumatera ke Batam', 'planned_output': 'Koordinasi', 'planned_cost': '0.0', 'actual_plan': 'Koordinasi dengan PT EPI untuk Swap gas PLN EPI dari Sumatera ke Batam', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': 'Hijau', 'kri_value_actual': None}]}, {'source_risk_no': '2.0', 'event': 'Penyerapan Biaya Operasi melebihi pagu yang ditetapkan', 'cause_no': 'd', 'cause_text': 'Kenaikan harga energi primer gas', 'rows': [{'source_row': 17, 'plan': 'Manajemen Penyerapan gas yaitu gas murah akan dimaksimalkan dan gas mahal di minimalkan penyerapannya', 'planned_output': 'Realisasi Penyerapan gas', 'planned_cost': '-', 'actual_plan': 'Melakukan manajemen penyerapan gas dengan memaksimalkan gas murah', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': 'Harga Gas tertimbang', 'kri_unit': 'USD/MMBTU', 'kri_safe': '6.3', 'kri_caution': '7.0', 'kri_danger': '7.5', 'kri_threshold_actual': 'Hijau', 'kri_value_actual': '7.32'}]}, {'source_risk_no': '3.0', 'event': 'Terjadinya pemadaman meluas dan atau blackout di sistem kelistrikan Batam - Bintan', 'cause_no': 'e', 'cause_text': 'Sistem proteksi yang tidak optimal (relay, telekomunikasi dan power supply) pada sistem ketenagalistrikan yang dapat berdampak gangguan blackout', 'rows': [{'source_row': 18, 'plan': 'Penggantian Rele Proteksi dan Meter 150 kV dan 20 kV', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '3.5E9', 'actual_plan': None, 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses Pekerjaan Penggantian dan Pemasangan', 'progress_q1': '0.35', 'progress_q2': '0.5', 'progress_q3': '0.6', 'progress_q4': None, 'kri': 'Unjuk Kerja Proteksi', 'kri_unit': '%', 'kri_safe': '1.0', 'kri_caution': '<90%', 'kri_danger': '≤ 75%', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '1.0'}]}, {'source_risk_no': '3.0', 'event': 'Terjadinya pemadaman meluas dan atau blackout di sistem kelistrikan Batam - Bintan', 'cause_no': 'f', 'cause_text': 'Keandalan pembangkitan PLN Batam dan Pembangkit IPP tidak optimal', 'rows': [{'source_row': 19, 'plan': 'Melanjutkan pemeliharaan Level C Inspection GT#1 PLTGU Tanjung Uncang ', 'planned_output': 'Laporan pemeliharaan', 'planned_cost': '1.28E11', 'actual_plan': 'Pemeliharaan Level C Inpection GT#1 PLTGU Tanjung Uncang in-progress', 'actual_output': 'mulai februari s.d maret 2026', 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['0.0', '0.0', '1.0', '0.0', '0.0', '0.0', '0.0', None, None, None, None, None], 'source_status': 'Pemeliharaan Level C Inpection GT#1 PLTGU Tanjung Uncang estimasi dilaksanakan ferbuari-maret 2026', 'source_status_explanation': 'Telah selesai dilaksanakan pada bulan Maret', 'progress_q1': '1.0', 'progress_q2': '0.0', 'progress_q3': None, 'progress_q4': None, 'kri': 'EFOR KIT', 'kri_unit': '%', 'kri_safe': '0.01', 'kri_caution': '0.012', 'kri_danger': '0.0146', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '0.0125'}, {'source_row': 20, 'plan': 'Melanjutkan Major Overhaul 50K STG PLTGU Tanjung Uncang  ', 'planned_output': 'Laporan pemeliharaan', 'planned_cost': '6.858829074E10', 'actual_plan': 'Pemeliharaan Major Overhaul 50K STG PLTGU Tanjung Uncang telah selesai juli 2026', 'actual_output': 'telah selesai dilaksanakan juli 2026', 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['0.0', '0.0', '0.0', '0.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Pemeliharaan Major Overhaul 50K STG PLTGU Tanjung Uncang rencana dilakukan tanggal 24 Mei sampai dengan 08 Juli 2026', 'source_status_explanation': 'selesai 7 juli 2026', 'progress_q1': '0.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 21, 'plan': 'Pemasangan Redundend GT blower Ventilation Fan (P1)', 'planned_output': 'Laporan pemeliharaan', 'planned_cost': '1.32363E9', 'actual_plan': 'Pemasangan Redundend GT blower Ventilation Fan in-progress', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['0.0', '0.0', '0.0', '1.0', '0.0', '0.0', '0.0', None, None, None, None, None], 'source_status': 'Pemeliharaan 60K Engine#1dilakasanakan pada Februari-April 2026', 'source_status_explanation': 'Done', 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 22, 'plan': 'Melakukan pemeliharaan korektif dan menjaga keandalan operasional pembangkit PLTGU Tanjung Uncang', 'planned_output': 'Melakukan pemeliharaan korektif dan operasional pembangkit PLTGU Tanjung Uncang', 'planned_cost': 'Laporan pemeliharaan', 'actual_plan': 'Melakukan pemeliharaan korektif dan operasional pembangkit PLTGU Tanjung Uncang', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Melakukan pemeliharaan korektif dan operasional pembangkit PLTGU Tanjung Uncang', 'source_status_explanation': 'Melakukan kalibrasi blade valve terkait gas fuel low alarm', 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 23, 'plan': 'Melakukan pemeliharaan korektif dan menjaga keandalan operasional pembangkit PLTMG Panaran', 'planned_output': 'Melakukan pemeliharaan korektif dan operasional pembangkit PLTMG Panaran', 'planned_cost': 'Laporan pemeliharaan', 'actual_plan': 'Pemeliharaan korektif dan operasional pembangkit PLTMG Panaran', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Melakukan maintenance outage ', 'source_status_explanation': 'Melakukan pengecekan dan perbaikan pada gangguan knocking alarm', 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 24, 'plan': 'Melakukan pemeliharaan korektif mekanikal dan sarana pembangkit PLTD', 'planned_output': 'Melakukan pemeliharaan korektif dan operasional pembangkit PLTD', 'planned_cost': 'Laporan pemeliharaan', 'actual_plan': 'Pemeliharaan korektif dan operasional pembangkit PLTD', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '0.0', '0.0', '0.0', '0.0', '0.0', None, None, None, None, None], 'source_status': 'Tidak ada pemeliharaan korektif pada PLTD pada bulan Juli 2026', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '3.0', 'event': 'Terjadinya pemadaman meluas dan atau blackout di sistem kelistrikan Batam - Bintan', 'cause_no': 'g', 'cause_text': 'Ketidaksiapan operasi pembangkit PLTU akibat kendala pada energy primer (pasokan batubara)', 'rows': [{'source_row': 25, 'plan': 'Mempertahankan “stock rata-rata harian” Batubara pada 8 s.d 12 hari operasi. ', 'planned_output': 'Monitoring harian pasokan batubara', 'planned_cost': '0.0', 'actual_plan': 'Realisasi stok rata-rata harian batubara bulan Juni adalah 8 HOP', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Realisasi stok rata-rata harian batubara bulan Juli 10,9 HOP dengan realisasi pemakaian 1.701 MT/hari.', 'source_status_explanation': 'HOP di atas 10 hari', 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': 'HOP BATUBARA', 'kri_unit': 'HARI OPERASI', 'kri_safe': '10.0', 'kri_caution': '9.0', 'kri_danger': '8.0', 'kri_threshold_actual': 'kuning', 'kri_value_actual': '10.0'}, {'source_row': 26, 'plan': 'Perluasan area stokpile batubara', 'planned_output': 'Meningkatkan HOP batubara', 'planned_cost': 'Realisasi HOP batubara bulanan', 'actual_plan': 'Melakukan perluasan dan perbaikan elevasi serta drainase stokpile untuk menjaga kulitas HOP dan kualitas batubara', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Melakukan kontrak kerjasama dengan PLN Batubara Niaga terkait pemenuhan stok batubara dan melakukan perluasan stokpile batubara PLTU Tanjung Kasam saat ini sudah dalam finishing untuk sistem drainase.', 'source_status_explanation': 'selesai pada bulan Mei 2026', 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 27, 'plan': 'Monitoring kualitas batubara yang dikirimkan melalui COA loading dan memastikan semua spesifikasi sesuai dengan kontrak sebelum dilakukan proses penyandaran dan pembongkaran.', 'planned_output': 'Monitoring harian pasokan batubara', 'planned_cost': '0.0', 'actual_plan': 'Telah dilakukan monitoring kualitas batubara setelah loading sebelum di lakukan pembongkaran batubara melalui COA loading batubara.', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Telah dilakukan monitoring kualitas batubara setelah loading sebelum di lakukan pembongkaran batubara melalui COA loading batubara.', 'source_status_explanation': 'Memperhatikan spesifikasi batubara pada pelabuhan muat melalui COA loading', 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 28, 'plan': 'Monitoring tahapan pengiriman Batubara dimana pemasok Batubara diwajibkan melaporkan update status atau progress dalam tahapan pengiriman Batubara, dimulai sejak tahapan Loading Batubara, transportasi, sampai unloading di Batam ', 'planned_output': 'Monitoring harian pasokan batubara', 'planned_cost': '0.0', 'actual_plan': 'Pemasok batubara telah menyampaikan update tahapan pengiriman batubara melalui email/WAG', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Pemasok batubara telah menyampaikan update tahapan pengiriman batubara melalui email/WAG.', 'source_status_explanation': 'Monitoring perjalanan kapal dari pelabuhan muat', 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 29, 'plan': 'Mengoptimal Kerja Sama Strategis (KJS) antara PT PLN Batam dan PT PLN BB dengan komunikasi intensif dan sedini mungkin untuk melakukan pengamanan stok batubara', 'planned_output': 'Dokumen kontrak', 'planned_cost': '0.0', 'actual_plan': 'Telah melakukan optimalisasi kerjasama dengan PLN BBN pada bulan Juni dengan adanya 2 pasokan batubara dari PLN BBN dengan sumber tambang dari Jambi (Sumatra).', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Telah melakukan optimalisasi kerjasama dengan PLN BBN pada bulan Juni dengan adanya 2 pasokan batubara dari PLN BBN dengan sumber tambang dari Jambi (Sumatra).', 'source_status_explanation': 'Meminta PLN BBN untuk memenuhi kewajiban shipment ke Batam sesuai dengan spesifikasi batubara PLTU Tanjung Kasam.', 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '3.0', 'event': 'Terjadinya pemadaman meluas dan atau blackout di sistem kelistrikan Batam - Bintan', 'cause_no': 'h', 'cause_text': 'Ketidaksiapan operasi pembangkit gas akibat pembatasan gas dari pemasok', 'rows': [{'source_row': 30, 'plan': 'Memastikan pressurer gas stabil dan pressure gas sesuai kebutuhan pembangkit PLTGU', 'planned_output': 'Monitoring harian pasokan Gas', 'planned_cost': '0.0', 'actual_plan': 'Memastikan pressurer gas stabil dan pressure gas sesuai kebutuhan pembangkit PLTGU', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 31, 'plan': 'Komunikasi rutin dengan pemasok Gas dan Transporter Gas ', 'planned_output': 'Monitoring harian pasokan Gas', 'planned_cost': '0.0', 'actual_plan': 'Komunikasi rutin dengan pemasok Gas dan Transporter Gas', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 32, 'plan': 'Memaksimalkan beban PLTU Tj Kasam ', 'planned_output': 'Monitoring harian pasokan Gas', 'planned_cost': None, 'actual_plan': 'Memaksimalkan beban PLTU Tj Kasam', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 33, 'plan': 'Mengatur jadwal-ulang pemeliharaan pembangkit berbahan bakar Non-Gas tidak bersamaan dengan periode pemeliharaan sumur Gas atau pipa Gas', 'planned_output': 'Monitoring harian pasokan Gas', 'planned_cost': None, 'actual_plan': 'Mengatur jadwal-ulang pemeliharaan pembangkit berbahan bakar Non-Gas tidak bersamaan dengan periode pemeliharaan sumur Gas atau pipa Gas', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Belum ada Penyesuaian jadwal pemeliharaan pembangkit non gas karena BIdang OPSIS sejak awal telah melakukan penyesuaian jadwal PLTU dengan memperhatikan jadwal pemeliharaan sumur gas', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '3.0', 'event': 'Terjadinya pemadaman meluas dan atau blackout di sistem kelistrikan Batam - Bintan', 'cause_no': 'i', 'cause_text': 'Ketidaksiapan operasi peralatan Transmisi 150 kV akibat gangguan cuaca, kerusakan peralatan utama, \nsambaran petir, kondisi cuaca, pencurian peralatan dan Kesalahan operasi dan pemeliharaan peralatan transmisi.', 'rows': [{'source_row': 34, 'plan': 'Pengadaan Isolator AntiFOG 120 dan 210 kN Tower Transmisi 150 kV', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '1.4316E9', 'actual_plan': 'Pengadaan Isolator AntiFOG 120 dan 210 kN Tower Transmisi 150 kV', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Selesai', 'source_status_explanation': 'Selesai', 'progress_q1': '0.2', 'progress_q2': '0.4', 'progress_q3': '1.0', 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': '<6 Kali/100 kms/Tahun', 'kri_caution': '6-7 Kali/100 kms/Tahun', 'kri_danger': '>7 Kali/100 kms/Tahun', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '0.497743142995891'}, {'source_row': 35, 'plan': 'Penguatan Dan Pengamanan Tapak Tower / Reroute Transmisi 150 kV', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '6.0E9', 'actual_plan': 'Penguatan Dan Pengamanan Tapak Tower / Reroute Transmisi 150 kV', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', '1.0', None, None, None, None, None, None, None, None, None, None], 'source_status': 'Selesai', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': '<6 Kali/100 kms/Tahun', 'kri_caution': '6-7 Kali/100 kms/Tahun', 'kri_danger': '>7 Kali/100 kms/Tahun', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '0.497743142995891'}, {'source_row': 36, 'plan': 'Pengadaan dan Pemasangan OPGW 24 core', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '4.935028784E9', 'actual_plan': 'Pengadaan dan Pemasangan OPGW 24 core (Nomor: 0019.Pj/DAN.01.03/PLNBATAM030300/2025)', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Selesai', 'source_status_explanation': 'Selesai', 'progress_q1': '0.3', 'progress_q2': '0.5', 'progress_q3': '1.0', 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': '<6 Kali/100 kms/Tahun', 'kri_caution': '6-7 Kali/100 kms/Tahun', 'kri_danger': '>7 Kali/100 kms/Tahun', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '0.497743142995891'}, {'source_row': 37, 'plan': 'Pengadaan dan Pemasangan EGLA Titik Kritikal Transmisi 150 kV', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '3.50512E9', 'actual_plan': 'Pengadaan dan Pemasangan EGLA Titik Kritikal Transmisi 150 kV', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses kerja', 'progress_q1': '0.2', 'progress_q2': '0.2', 'progress_q3': '0.2', 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': '<6 Kali/100 kms/Tahun', 'kri_caution': '6-7 Kali/100 kms/Tahun', 'kri_danger': '>7 Kali/100 kms/Tahun', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '0.497743142995891'}, {'source_row': 38, 'plan': 'Pengadaan dan Pemasangan OPGW 24 core', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '5.0955E9', 'actual_plan': 'Pengadaan dan Pemasangan OPGW 24 core (Nomor: 0019.Pj/DAN.01.03/PLNBATAM030300/2025)', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses kerja', 'progress_q1': '0.0', 'progress_q2': '0.0', 'progress_q3': '0.2', 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': '<6 Kali/100 kms/Tahun', 'kri_caution': '6-7 Kali/100 kms/Tahun', 'kri_danger': '>7 Kali/100 kms/Tahun', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '0.497743142995891'}, {'source_row': 39, 'plan': 'Penguatan atau pengamanan tapak tower dan Reroute tower transmisi 150 kV', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '4.3355E10', 'actual_plan': 'Penguatan atau pengamanan tapak tower dan Reroute tower transmisi 150 kV', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses kerja', 'progress_q1': '0.2', 'progress_q2': '0.2', 'progress_q3': '0.2', 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': '<6 Kali/100 kms/Tahun', 'kri_caution': '6-7 Kali/100 kms/Tahun', 'kri_danger': '>7 Kali/100 kms/Tahun', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '0.497743142995891'}, {'source_row': 40, 'plan': 'Memperkuat pengamanan terhadap pencurian part tower dengan memaksimalkan fungsi inspector transmission line sesuai dengan Kepdir & IK Pemeliharaan SUTT 150 kV', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '28912851833', 'actual_plan': 'Memperkuat pengamanan terhadap pencurian part tower dengan memaksimalkan fungsi inspector transmission line sesuai dengan Kepdir & IK Pemeliharaan SUTT 150 kV', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses kerja', 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': '1.0', 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': '<6 Kali/100 kms/Tahun', 'kri_caution': '6-7 Kali/100 kms/Tahun', 'kri_danger': '>7 Kali/100 kms/Tahun', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '0.497743142995891'}, {'source_row': 41, 'plan': 'Melakukan Pengadaan & Pemasangan Kubikel 20 kV GI Tersebar.', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '4.636641E9', 'actual_plan': 'Melakukan Pengadaan & Pemasangan Kubikel 20 kV GI Tersebar.', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Pengadaan Barang', 'progress_q1': '0.0', 'progress_q2': '0.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '3.0', 'event': 'Terjadinya pemadaman meluas dan atau blackout di sistem kelistrikan Batam - Bintan', 'cause_no': 'j', 'cause_text': 'Ketidaksiapan operasi peralatan Gardu Induk 150/20 kV akibat kerusakan peralatan, Kesalahan operasi dan pemeliharaan peralatan transmisi. ', 'rows': [{'source_row': 42, 'plan': 'Melakukan Pengadaan dan Pemasangan Power Supply GI Kritikal', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '2.590916E9', 'actual_plan': 'Melakukan Pengadaan dan Pemasangan Power Supply GI Kritikal', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses kontrak di lakdan', 'progress_q1': '0.0', 'progress_q2': '0.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 43, 'plan': 'Melakukan Pengadaan dan Penggantian Material Transmisi Utama 150 kV', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '9.975537E9', 'actual_plan': 'Melakukan Pengadaan dan Penggantian Material Transmisi Utama 150 kV', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses kerja', 'progress_q1': '0.0', 'progress_q2': '0.35', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 44, 'plan': 'Mengoptimalkan pemeliharaan dan pengujian Trafo dan Material Transmisi Utama sesuai IK Pemeliharaan Trafo Daya dan OLTC.', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '1.4638441706E10', 'actual_plan': 'Mengoptimalkan pemeliharaan dan pengujian Trafo dan Material Transmisi Utama sesuai IK Pemeliharaan Trafo Daya dan OLTC.', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses kerja', 'progress_q1': '0.19', 'progress_q2': '0.53', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 45, 'plan': 'Melakukan pembangunan Bay Trafo 2 GI Panaran, Relokasi Trafo dan MTU Dari GI Sengkuang Ke GI Panaran', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '7970766350', 'actual_plan': 'Melakukan pembangunan Bay Trafo 2 GI Panaran, Relokasi Trafo dan MTU Dari GI Sengkuang Ke GI Panaran', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses kerja', 'progress_q1': '0.8', 'progress_q2': '0.8', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 46, 'plan': 'Digitalisasi dan Integrasi Gardu Induk Tersebar', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '3.5144725E10', 'actual_plan': 'Digitalisasi dan Integrasi Gardu Induk Tersebar', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses kontrak di lakdan', 'progress_q1': '0.0', 'progress_q2': '0.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 47, 'plan': 'Pengadaaan Peralatan Inspeksi GIS (Gas Insulated Switchgear) ', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '2.107879E9', 'actual_plan': 'Pengadaaan Peralatan Inspeksi GIS (Gas Insulated Switchgear) ', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses kontrak di lakdan', 'progress_q1': '0.0', 'progress_q2': '0.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 48, 'plan': 'Mengajukan pelatihan/pembekalan kepada operator dan tim har pembangkitan dan transmisi', 'planned_output': 'ND Usulan Pelatihan/pelaksanaan pembekalan', 'planned_cost': '0.0', 'actual_plan': 'Mengajukan pelatihan/pembekalan kepada operator dan tim har pembangkitan dan transmisi', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': [None, None, None, None, None, None, None, None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': None, 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '3.0', 'event': 'Terjadinya pemadaman meluas dan atau blackout di sistem kelistrikan Batam - Bintan', 'cause_no': 'k', 'cause_text': 'Kesalahan operasi peralatan pembangkit atau transmisi atau gardu induk', 'rows': [{'source_row': 50, 'plan': 'Mengajukan pelatihan/pembekalan kepada operator dan tim har pembangkitan dan transmisi', 'planned_output': None, 'planned_cost': None, 'actual_plan': 'Mengajukan pelatihan/pembekalan kepada operator dan tim har pembangkitan dan transmisi', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': None, 'timeline': [None, None, None, None, None, None, None, None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': None, 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '3.0', 'event': 'Terjadinya pemadaman meluas dan atau blackout di sistem kelistrikan Batam - Bintan', 'cause_no': 'l', 'cause_text': 'Terjadinya gangguan kerusakan pada perangkat SCADA dan telekomunikasi (Master Station, Remote Station, Telekomunikasi dan peripheral SCADA)', 'rows': [{'source_row': 51, 'plan': 'Integrasi AGC, Penggantian Remote Station Pembangkit dan Redesign BCC', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '8.0E9', 'actual_plan': None, 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA\nMAN OSIS', 'timeline': [None, None, None, None, None, None, None, None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': None, 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 52, 'plan': 'Pembangunan Gedung Control Centre Batam Bintan (P2B)  dan Data Centre SCADA', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': None, 'actual_plan': 'Pembangunan Gedung Control Centre Batam Bintan (P2B)  dan Data Centre SCADA', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA\nMAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', None, None, None, None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': '0.25', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 53, 'plan': 'Penggantian Master Station berbasis EMS, DMS dan DTS (Dispatcher Training Simulator)', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '23750000000', 'actual_plan': 'Penggantian Master Station berbasis EMS, DMS dan DTS (Dispatcher Training Simulator)', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses Revisi Dokumen Pengadaan Penggantian Master Station', 'progress_q1': '0.15', 'progress_q2': '0.15', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 54, 'plan': 'Pengadaan Genset 250 kVA dan UPS 50 kVA sebagai Back Up Supplay gedung Control Centre', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '3.0E9', 'actual_plan': None, 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA\nMAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', None, None, None, None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': None, 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 55, 'plan': 'Pengembangan Monitoring Gardu Induk ', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '2.5E9', 'actual_plan': 'Pengadaan dan Pemasangan Kamera Thermovisi pada Switchyard 150 kV', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses Pekerjaan', 'progress_q1': '0.1', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 56, 'plan': 'Aplikasi manajemen energi untuk optimasi BPP', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '4.0E9', 'actual_plan': None, 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': '1.0', 'kri_caution': '99,99%', 'kri_danger': '< 99.985%', 'kri_threshold_actual': None, 'kri_value_actual': '0.99987'}]}, {'source_risk_no': '3.0', 'event': 'Terjadinya pemadaman meluas dan atau blackout di sistem kelistrikan Batam - Bintan', 'cause_no': 'm', 'cause_text': 'Adanya Kesalahan Setting dan koordinasi Proteksi', 'rows': [{'source_row': 57, 'plan': 'Pemasangan BusPro pada GI Tersebar dan Redundancy Relay Proteksi Utama pada Transmisi dan Gardu Induk', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': None, 'actual_plan': None, 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Rencana Pekerjaan di Bulan September 2026', 'progress_q1': '0.4', 'progress_q2': '0.5', 'progress_q3': '0.55', 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 58, 'plan': 'Optimalisasi Adaptive Defense Scheme', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '1.5E9', 'actual_plan': 'Optimalisasi Adaptive Defense Scheme', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses di Bagian Rendan', 'progress_q1': '0.2', 'progress_q2': '0.25', 'progress_q3': '0.3', 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 59, 'plan': 'Pemasangan DFR pada TRAFO GI Baloi, GI Sagulung, GI Tg Kasam dan GI Muka Kuning', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '2.01E9', 'actual_plan': None, 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses di Bagian Lakdan', 'progress_q1': '0.3', 'progress_q2': '0.4', 'progress_q3': '0.45', 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 60, 'plan': 'Material Operasi dan Maintenance Proteksi', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '6.8757212048832E9', 'actual_plan': '- Pengadaan Material Pemeliharaan, Pengujian dan Consumable Proteksi', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': '0.55', 'progress_q2': '1.0', 'progress_q3': '1.0', 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 61, 'plan': 'Jasa Operasi dan Maintenance Proteksi', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '3.8220219076608E9', 'actual_plan': None, 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': '0.25', 'progress_q2': '0.5', 'progress_q3': '0.55', 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '3.0', 'event': 'Terjadinya pemadaman meluas dan atau blackout di sistem kelistrikan Batam - Bintan', 'cause_no': 'n', 'cause_text': 'Pembebanan Trafo overload', 'rows': [{'source_row': 62, 'plan': 'Monitoring Beban trafo secara realtime', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '0.0', 'actual_plan': 'Monitoring Beban trafo secara realtime', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', None, None, None, None, None, None, None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 63, 'plan': 'Manuver beban trafo', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '0.0', 'actual_plan': 'Manuver beban di Trafo Baloi saat terjadi gangguan trafo', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', None, None, None, None, None, None, None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 64, 'plan': 'Membuat laporan pembebanan trafo dan usulan penambahan trafo', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '0.0', 'actual_plan': None, 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', None, None, None, None, None, None, None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': None, 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '4.0', 'event': 'Terjadi Defisit Daya Pada Sistem Batam-Bintan', 'cause_no': 'o', 'cause_text': 'Pelaksanaan Pemeliharaan Pembangkit Melebihi jadwal yang ditetapkan', 'rows': [{'source_row': 65, 'plan': 'Monitoring pelaksanaan pemeliharaan secara ketat', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '0.0', 'actual_plan': 'Monitoring pelaksanaan pemeliharaan secara ketat', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': 'Durasi Pemeliharaan', 'kri_unit': '%', 'kri_safe': '1.0', 'kri_caution': '1.1', 'kri_danger': '1.2', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '1.0'}, {'source_row': 66, 'plan': 'Pengaturan jadwal pemeliharaan tidak bersamaan', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '0.0', 'actual_plan': 'Pengaturan jadwal pemeliharaan tidak bersamaan', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 67, 'plan': 'Reschedule pemeliharaan untuk menghindari defisit', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': None, 'actual_plan': 'Reschedule pemeliharaan untuk menghindari defisit', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '4.0', 'event': 'Terjadi Defisit Daya Pada Sistem Batam-Bintan', 'cause_no': 'p', 'cause_text': 'Keterlambatan COD pembangkit baru', 'rows': [{'source_row': 68, 'plan': 'Melakukakan koordinasi Rutin dengan Divisi Project ', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': None, 'actual_plan': 'Melakukakan koordinasi Rutin dengan Divisi Project', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 69, 'plan': 'Mengupayakan kesiapan sistem untuk mengijinkan uji komisioning pembangkit baru', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': None, 'actual_plan': 'Mengupayakan kesiapan sistem untuk mengijinkan uji komisioning pembangkit baru', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '4.0', 'event': 'Terjadi Defisit Daya Pada Sistem Batam-Bintan', 'cause_no': 'q', 'cause_text': 'Pembangkit PLN Batam mengalami outage/trip diluar jadwal yang sudah disepakati', 'rows': [{'source_row': 70, 'plan': 'Memaksimalkan jadwal pemeliharaan pembangkit  PLN Batam sesuai dengan rencana yang sudah disepakati dalam ROT atau ROB dengan cara meningkatkan keandalan pembangkit', 'planned_output': 'ROB', 'planned_cost': None, 'actual_plan': 'Pelaksanaan Pemeliharaan sesuai ROB', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '4.0', 'event': 'Terjadi Defisit Daya Pada Sistem Batam-Bintan', 'cause_no': 'r', 'cause_text': 'Pembangkit IPP mengalami Force Outage atau outage diluar jadwal yang sudah disepakati', 'rows': [{'source_row': 71, 'plan': 'Memaksimalkan jadwal pemeliharaan pembangkit  PLN IPP sesuai dengan rencana yang sudah disepakati dalam ROT atau ROB dengan cara meningkatkan keandalan pembangkit', 'planned_output': 'ROB', 'planned_cost': None, 'actual_plan': 'Pelaksanaan Pemeliharaan sesuai ROB', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '4.0', 'event': 'Terjadi Defisit Daya Pada Sistem Batam-Bintan', 'cause_no': 's', 'cause_text': 'Penurunan Pressure gas yang tidak stabil atau dibawah kebutuhan pressure pembangkit dapat beroperasi pada beban optimal', 'rows': [{'source_row': 72, 'plan': 'Memastikan pressurer gas stabil dan pressure gas sesuai kebutuhan pembangkit PLTGU/PLTMG', 'planned_output': 'Monitoring harian pasokan Gas', 'planned_cost': None, 'actual_plan': 'Memastikan pressurer gas stabil dan pressure gas sesuai kebutuhan pembangkit PLTGU/PLTMG', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '4.0', 'event': 'Terjadi Defisit Daya Pada Sistem Batam-Bintan', 'cause_no': 't', 'cause_text': 'Ketidaksiapan operasi pembangkit gas akibat pembatasan gas dari pemasok', 'rows': [{'source_row': 73, 'plan': 'Memastikan pressurer gas stabil dan pressure gas sesuai kebutuhan pembangkit PLTGU', 'planned_output': 'Monitoring harian pasokan Gas', 'planned_cost': None, 'actual_plan': 'Memastikan pressurer gas stabil dan pressure gas sesuai kebutuhan pembangkit PLTGU', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 74, 'plan': 'Komunikasi rutin dengan pemasok Gas dan Transporter Gas ', 'planned_output': 'Monitoring harian pasokan Gas', 'planned_cost': None, 'actual_plan': 'Komunikasi rutin dengan pemasok Gas dan Transporter Gas', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 75, 'plan': 'Memaksimalkan beban PLTU Tj Kasam ', 'planned_output': 'Monitoring harian pasokan Gas', 'planned_cost': None, 'actual_plan': 'Memaksimalkan beban PLTU Tj Kasam', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 76, 'plan': 'Mengatur jadwal-ulang pemeliharaan pembangkit berbahan bakar Non-Gas tidak bersamaan dengan periode pemeliharaan sumur Gas atau pipa Gas', 'planned_output': 'Monitoring harian pasokan Gas', 'planned_cost': None, 'actual_plan': 'Mengatur jadwal-ulang pemeliharaan pembangkit berbahan bakar Non-Gas tidak bersamaan dengan periode pemeliharaan sumur Gas atau pipa Gas', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '4.0', 'event': 'Terjadi Defisit Daya Pada Sistem Batam-Bintan', 'cause_no': 'u', 'cause_text': 'Ketidaksiapan operasi pembangkit akibat kendala pada energy primer (pasokan batubara)', 'rows': [{'source_row': 77, 'plan': 'Mempertahankan “stock rata-rata harian” Batubara pada 8 s.d 12 hari operasi. ', 'planned_output': 'Monitoring harian pasokan batubara', 'planned_cost': None, 'actual_plan': 'Realisasi stok rata-rata harian batubara bulan Juni adalah 8 HOP', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': 'HOP BATUBARA', 'kri_unit': 'HOP', 'kri_safe': '10.0', 'kri_caution': '9.0', 'kri_danger': '8.0', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '10.0'}, {'source_row': 78, 'plan': 'Meningkatkan pengamanan pasokan Batubara dengan menambah jumlah pemasok Batubara untuk menambah alternatif pemasok jika terjadi kendala pasokan dari salah satu pemasok Batubara.', 'planned_output': 'Dokumen Kontrak', 'planned_cost': None, 'actual_plan': 'Melakukan kontrak kerjasama dengan PLN Batubara Niaga terkait pemenuhan stok batubara dan melakukan perluasan stokpile batubara PLTU Tanjung Kasam saat ini sudah selesai tinggal menunggu persetujuan TJK untuk bisa digunakan.', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 79, 'plan': 'Monitoring kualitas batubara yang dikirimkan melalui COA loading dan memastikan semua spesifikasi sesuai dengan kontrak sebelum dilakukan proses penyandaran dan pembongkaran.', 'planned_output': 'Monitoring harian pasokan batubara', 'planned_cost': None, 'actual_plan': 'Telah dilakukan monitoring kualitas batubara setelah loading sebelum di lakukan pembongkaran batubara melalui COA loading batubara.', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 80, 'plan': 'Monitoring tahapan pengiriman Batubara dimana pemasok Batubara diwajibkan melaporkan update status atau progress dalam tahapan pengiriman Batubara, dimulai sejak tahapan Loading Batubara, transportasi, sampai unloading di Batam ', 'planned_output': 'Monitoring harian pasokan batubara', 'planned_cost': None, 'actual_plan': 'Pemasok batubara telah menyampaikan update tahapan pengiriman batubara melalui email/WAG', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 81, 'plan': 'Mengoptimal Kerja Sama Strategis (KJS) antara PT PLN Batam dan PT PLN BB dengan komunikasi intensif dan sedini mungkin untuk melakukan pengamanan stok batubara', 'planned_output': 'Dokumen kontrak', 'planned_cost': None, 'actual_plan': 'Telah melakukan optimalisasi kerjasama dengan PLN BBN pada bulan Juni dengan adanya 2 pasokan batubara dari PLN BBN dengan sumber tambang dari Jambi (Sumatra).', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '4.0', 'event': 'Terjadi Defisit Daya Pada Sistem Batam-Bintan', 'cause_no': 'v', 'cause_text': 'Kenaikan beban di atas Daya Mampu Pasok (DMP) ', 'rows': [{'source_row': 82, 'plan': 'Melakukan brownout pada saat Beban Puncak untuk mengurangi dampak pemadaman', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '0.0', 'actual_plan': 'Melakukan brownout pada saat Beban Puncak untuk mengurangi dampak pemadaman', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['0.0', '0.0', '0.0', '0.0', '0.0', '0.0', '0.0', None, None, None, None, None], 'source_status': 'Tidak dilakukan selama tahun 2026 dengan memperhatikan kondisi sistem', 'source_status_explanation': None, 'progress_q1': '0.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 83, 'plan': 'Mengoperasikan PLTD', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '0.0', 'actual_plan': 'Mengoperasikan PLTD', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS\nMANDALKIT', 'timeline': ['0.0', '0.0', '0.0', '0.0', '0.0', '0.0', '0.0', None, None, None, None, None], 'source_status': 'Tidak dilakukan pada Januari 2026 dengan memperhatikan kondisi sistem', 'source_status_explanation': None, 'progress_q1': '0.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '4.0', 'event': 'Terjadi Defisit Daya Pada Sistem Batam-Bintan', 'cause_no': 'w', 'cause_text': 'Kenaikan suhu ambient yang menyebabkan pembangkit derating', 'rows': [{'source_row': 84, 'plan': 'Optimalisasi Pembebanan untuk menghindari gangguan pembangkit', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '0.0', 'actual_plan': 'Optimalisasi Pembebanan untuk menghindari gangguan pembangkit', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Tidak dilakukan pada Mei 2026 dengan memperhatikan kondisi sistem', 'source_status_explanation': None, 'progress_q1': '0.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 85, 'plan': 'Menaikkan beban pembangkit lain ', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '0.0', 'actual_plan': 'Menaikkan beban pembangkit lain', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Tidak dilakukan pada Mei 2026 dengan memperhatikan kondisi sistem', 'source_status_explanation': None, 'progress_q1': '0.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '5.0', 'event': 'Pembangkit IPP dan PLN Batam mengalami derating atau gangguan ', 'cause_no': 'x', 'cause_text': 'Kerusakan pada komponen pembangkit', 'rows': [{'source_row': 86, 'plan': 'Melaksanakan Pemeliharaan pada Pembangkit Sendiri', 'planned_output': 'Realisasi Pemeliharaan', 'planned_cost': None, 'actual_plan': 'Melaksanakan Pemeliharaan pada Pembangkit Sendiri', 'actual_output': 'Melakasanakan pemeliharaan pembangkit PLTMG panaran dan PLTGU Tanjung Uncang.', 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': 'EFOR', 'kri_unit': '%', 'kri_safe': '1.39', 'kri_caution': '1.46', 'kri_danger': '1.53', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '1.25'}, {'source_row': 87, 'plan': 'Memastikan Keandalan pembangkit IPP', 'planned_output': 'EAF Pembangkit IPP', 'planned_cost': None, 'actual_plan': 'Memastikan Keandalan pembangkit IPP', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '6.0', 'event': 'Penyerapan gas dalam BTU/kWh oleh pembangkit sendiri dan sewa melebihi asumsi yang ditetapkan', 'cause_no': 'y', 'cause_text': 'Pembangkit sendiri mengalami force derating', 'rows': [{'source_row': 88, 'plan': 'Melaksanakan Pemeliharaan pada Pembangkit Sendiri', 'planned_output': 'Realisasi Pemeliharaan', 'planned_cost': '0.0', 'actual_plan': 'Melaksanakan Pemeliharaan pada Pembangkit Sendiri', 'actual_output': 'Pelaksanaan pemeliharan berkala dan korektif pada pembangkit sendiri', 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': 'Persentase pembebanan STG ', 'kri_unit': '%', 'kri_safe': '0.95', 'kri_caution': '0.9', 'kri_danger': '0.85', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': None}]}, {'source_risk_no': '6.0', 'event': 'Penyerapan gas dalam BTU/kWh oleh pembangkit sendiri dan sewa melebihi asumsi yang ditetapkan', 'cause_no': 'z', 'cause_text': 'Pembangkit IPP mengalami Force Derating', 'rows': [{'source_row': 89, 'plan': 'Pengoperasian pembangkit sesuai merit order pada beban optimal', 'planned_output': 'Merit Order', 'planned_cost': '0.0', 'actual_plan': 'Pengoperasian pembangkit sesuai merit order pada beban optimal', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 90, 'plan': 'Pengenaan Denda Heatrate bagi pembangkit sewa yang melebihi batas heatrate jaminan', 'planned_output': 'BA Denda Heatrate', 'planned_cost': '0.0', 'actual_plan': 'Pengenaan Denda Heatrate bagi pembangkit sewa yang melebihi batas heatrate jaminan', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 91, 'plan': 'Mendorong pembangkit sewa untuk dapat melakukan inovasi efisiensi pemakaian gas', 'planned_output': 'BA Perhitungan Heatrate', 'planned_cost': '0.0', 'actual_plan': None, 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': None, 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '6.0', 'event': 'Penyerapan gas dalam BTU/kWh oleh pembangkit sendiri dan sewa melebihi asumsi yang ditetapkan', 'cause_no': 'aa', 'cause_text': 'Flowmeter Gas Pembangkit Sendiri dan Sewa tidak akurat karena tidak dikalibrasi sesuai jadwal', 'rows': [{'source_row': 92, 'plan': 'Melakukan Monitoring pelaksanaan Kalibarasi flowmeter gas pembangkit sendiri dan sewa', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '0.0', 'actual_plan': 'Melakukan Monitoring pelaksanaan Kalibarasi flowmeter gas pembangkit sendiri dan sewa', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '7.0', 'event': 'Realisasi pelaksanaan pekerjaan tidak tepat waktu', 'cause_no': 'ab', 'cause_text': 'Spesifikasi teknis peralatan tidak sesuai kontrak', 'rows': [{'source_row': 93, 'plan': 'Mengoptimalkan pemeriksaan barang oleh tim pemeriksa barang', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '0.0', 'actual_plan': 'Mengoptimalkan pemeriksaan barang oleh tim pemeriksa barang', 'actual_output': 'Penerimaan Pelumas Shell Mysela', 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN ADMKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': 'Persentase realisasi penyelesaian pekerjaan sesuai kontrak', 'kri_unit': '%', 'kri_safe': '1.0', 'kri_caution': '<90%', 'kri_danger': '<80%', 'kri_threshold_actual': None, 'kri_value_actual': '1.0'}, {'source_row': 94, 'plan': 'Mengoptimalkan pengawasan/monitoring progres pekerjaan', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '0.0', 'actual_plan': 'Mengoptimalkan pengawasan/monitoring progres pekerjaan', 'actual_output': 'Pengawasan / monitoring pekerjaan sesuai lingkup bidang ADM', 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN ADMKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': None}, {'source_row': 95, 'plan': 'Mengoptimalkan penggunaan anggran operasi umum', 'planned_output': 'Penyerapan anggaran operasi umum', 'planned_cost': '4.51630145E8', 'actual_plan': 'Mengoptimalkan penggunaan anggran operasi umum', 'actual_output': 'Pengendalian Anggaran Operasi s.d bln Juli 2026', 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN ADMKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 96, 'plan': 'Mengoptimalkan penggunaan anggaran untuk sewa kendaraan dan BBM Operasional', 'planned_output': 'Penyerapan anggaran operasi umum', 'planned_cost': '-', 'actual_plan': 'Mengoptimalkan penggunaan anggaran untuk sewa kendaraan dan BBM Operasional', 'actual_output': 'Tidak ada sewa kendaraan tahun 2026', 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN ADMKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '8.0', 'event': 'Terjadi panas berlebih pada sambungan konduktor Transmisi', 'cause_no': 'ac', 'cause_text': 'Pemeliharaan preventif yang belum optimal', 'rows': [{'source_row': 97, 'plan': 'Memaksimalkan fungsi inspector transmission line sesuai dengan Kepdir & IK Pemeliharaan SUTT 150 kV', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '6.345934478E9', 'actual_plan': 'Memaksimalkan fungsi inspector transmission line sesuai dengan Kepdir & IK Pemeliharaan SUTT 150 kV', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', None, None, None, None, None, None, None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': 'Thermovisi Transmisi', 'kri_unit': '%', 'kri_safe': '∆t < 5℃', 'kri_caution': ' 5℃ < ∆t < 30℃', 'kri_danger': '∆t > 30℃', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': None}]}, {'source_risk_no': '9.0', 'event': 'Pengadaan gagal', 'cause_no': 'ad', 'cause_text': 'Jumlah peserta lelang tidak  sesuai persyaratan ', 'rows': [{'source_row': 98, 'plan': 'Memperluas pengumuman lelang ', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': None, 'actual_plan': 'Memperluas pengumuman lelang', 'actual_output': 'Pengumuman lelang Pekerjaan:\nPengadaan dan Pemasangan Relay Line Current Differential (LCD) serta Disturbance Fault Recorder (DFR) Sistem 20 kV (30 Juli 2026)\nPengadaan dan Pemasangan Power Supply GI Kritikal (24 Juli 2026)\nJasa Penyusunan Dokumen Adendum AMDAL Kegiatan Reroute Tower Transmisi 150 kV Sagulung - Panaran (9 Juli 2026)', 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN ADMKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': 'Persentase peserta lelang', 'kri_unit': '%', 'kri_safe': '1.0', 'kri_caution': '95-100%', 'kri_danger': '<100%', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '1.0'}]}, {'source_risk_no': '10.0', 'event': 'Tagihan tidak bisa terbayar tepat waktu', 'cause_no': 'ae', 'cause_text': 'Kelengkapan dokumen pembayaran tidak lengkap', 'rows': [{'source_row': 99, 'plan': 'Koordinasi Syarat bayar dokumen pembayaran ', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': None, 'actual_plan': 'Koordinasi Syarat bayar dokumen pembayaran', 'actual_output': 'Koordinasi rutin dokumen tagihan sepanjang bulan Juni 2026', 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN ADMKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': 'Kelengkapan dokumen pembayaran', 'kri_unit': '%', 'kri_safe': '1.0', 'kri_caution': '0.95', 'kri_danger': '0.9', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '1.0'}]}, {'source_risk_no': '11.0', 'event': 'Keandalan Pembangkit PLN Batam tidak optimal', 'cause_no': 'af', 'cause_text': 'Pembangkit PLN Batam mengalami force outage dan force derating', 'rows': [{'source_row': 100, 'plan': 'Melakukan pemeliharaan korektif dan menjaga keandalan operasional pembangkit PLTGU Tanjung Uncang', 'planned_output': 'Laporan pemeliharaan', 'planned_cost': '6.476603258627E10', 'actual_plan': 'Melakukan pemeliharaan korektif pembangkit PLTGU Tanjung Uncang', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '0.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': 'EFOR', 'kri_unit': '%', 'kri_safe': '0.04', 'kri_caution': '0.035', 'kri_danger': '0.03', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '0.0125'}, {'source_row': 101, 'plan': 'Melakukan pemeliharaan korektif dan menjaga keandalan operasional pembangkit PLTMG Panaran', 'planned_output': 'Laporan pemeliharaan', 'planned_cost': '1.53080558E10', 'actual_plan': 'Monitoring realisasi pemeliharan pembangkit', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 102, 'plan': 'Melakukan pemeliharaan korektif mekanikal dan sarana pembangkit PLTD', 'planned_output': 'Laporan pemeliharaan', 'planned_cost': '5.1195545E9', 'actual_plan': 'Monitoring realisasi pemeliharan pembangkit', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '0.0', '0.0', '0.0', '0.0', '0.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 103, 'plan': 'Melakukan operasi dan pemeliharaan pembangkit PLTS', 'planned_output': 'Laporan pemeliharaan', 'planned_cost': '2.566917274E9', 'actual_plan': 'Monitoring realisasi pemeliharan pembangkit', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '12.0', 'event': 'Minimnya Awareness pegawai terhadap program Budaya perusahaan ( COC)', 'cause_no': 'ah', 'cause_text': 'Kurangnya minat pegawai mengikuti coc ', 'rows': [{'source_row': 105, 'plan': 'Melakukan Reminder ke pegawai untuk informasi mengikuti  CoC', 'planned_output': 'Realisasi pelaksanaan CoC', 'planned_cost': '0.0', 'actual_plan': 'Melakukan Reminder ke pegawai untuk informasi mengikuti CoC', 'actual_output': 'Penyampaian informasi COC di grup internal UB KITRANS bulan Juli 2026', 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN ADMKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': 'Rasio Kehadiran COC', 'kri_unit': '%', 'kri_safe': '1.0', 'kri_caution': '80-100%', 'kri_danger': '<80%', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '90%%'}]}, {'source_risk_no': '13.0', 'event': 'Minimnya Awareness pegawai terhadap Program Anti Black Out', 'cause_no': 'aj', 'cause_text': 'Program Anti Black Out dipandang sebagai pekerjaan tambahan sehingga tidak menjadi prioritas dan hanya menjadi tanggung jawab PIC tertentu', 'rows': [{'source_row': 107, 'plan': 'Rutin melaksanakan monitoring program Anti Black Out setiap bulan', 'planned_output': 'Monitoring program Anti Black Out', 'planned_cost': '0.0', 'actual_plan': 'Melaksanakan monitoring program Anti Black Out setiap bulan', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN OSIS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': 'Rapat Monitoring Program Anti Black Out setiap bulan', 'kri_unit': '%', 'kri_safe': '1.0', 'kri_caution': '0.9', 'kri_danger': '<85%', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': None}]}, {'source_risk_no': '14.0', 'event': 'Pengadaan tidak terkontrak tepat waktu', 'cause_no': 'ak', 'cause_text': 'Dokumen penawaran yang disampaikan tidak lengkap', 'rows': [{'source_row': 108, 'plan': 'Memastikan calon penyedia memahami dokumen yang menjadi persyaratan pengadaan ', 'planned_output': 'Realisasi Terkontrak', 'planned_cost': '0.0', 'actual_plan': 'Memastikan calon penyedia memahami dokumen yang menjadi persyaratan pengadaan ', 'actual_output': 'Realisasi Terkontrak', 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN ADMKIT', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': 'Dilaksanakan secara rutin', 'source_status_explanation': None, 'progress_q1': '1.0', 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': 'Lead Time Pengadaan (Lelang)', 'kri_unit': '%', 'kri_safe': '<2 Bulan', 'kri_caution': '2-3 Bulan', 'kri_danger': '> 3 Bulan', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '<2 Bulan'}]}, {'source_risk_no': '15.0', 'event': 'Kesiapan perangkat SCADA dan telekomunikasi (Master Station, Remote Station, Telekomunikasi dan peripheral SCADA)', 'cause_no': None, 'cause_text': 'Faktor usia peralatan\nHuman error O&M Peralatan\nGangguan jaringan komunikasi,\nSerangan siber', 'rows': [{'source_row': 109, 'plan': 'Pengembangan Remote Station Gardu Distribusi', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '1.0E10', 'actual_plan': 'Pekerjaan Pengembangan Remote Station Gardu Distribusi 2026-2027 Tahap 1', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': 'Proses Pekerjaan Tahap 1', 'progress_q1': '0.0', 'progress_q2': '0.0', 'progress_q3': None, 'progress_q4': None, 'kri': 'Availaibility Teleinformasi Data', 'kri_unit': '%', 'kri_safe': '1.0', 'kri_caution': '90,00%', 'kri_danger': '< 90.00 %', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '0.9815'}, {'source_row': 110, 'plan': 'Pengadaan Radio komunikasi digital', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '2.0E9', 'actual_plan': None, 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': None, 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 111, 'plan': 'Penggantian perangkat BCU pada bay line EPC GI Tg. Kasam', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '3.45E9', 'actual_plan': None, 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': None, 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 112, 'plan': 'Peremajaan RTU di Pembangkit dan Gardu Tersebar ', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '2.1688938799E9', 'actual_plan': None, 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': None, 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '16.0', 'event': 'Sistem SCADA tidak dapat bekerja secara optimal', 'cause_no': None, 'cause_text': 'Faktor usia peralatan\nHuman error O&M Peralatan\nGangguan jaringan komunikasi,\nSerangan siber', 'rows': [{'source_row': 113, 'plan': 'Material Operasi dan Maintenance SCADA', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '6.8757212048832E9', 'actual_plan': '- Pengadaan Material TID SCADA\n- Integrasi Kubikel 20 kV GI Sagulung\n- Pengadaan dan Pemasangan Standalone Fiber Optic Multiplexer\n- Pengadaan & Pemasangan Perangkat Teleproteksi \n- Pengadaan dan Peremajaan Frekuensi Recorder Gardu Induk\n- Penggantian Server Database Offline SCADA\n- Pengembangan Remote Station Kubikel 20 kV Gardu Induk Tg Sengkuang\n- Pengadaan Radio Komunikasi pada Gardu Induk\n- Pengadaan PC Monitoring & Radio Komunikasi pada Gardu Induk', 'actual_output': None, 'actual_cost': '822700000', 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': None, 'source_status_explanation': 'Proses Pengadaan', 'progress_q1': '0.0', 'progress_q2': '0.1196529027', 'progress_q3': None, 'progress_q4': None, 'kri': 'Rasio Keberhasilan Remote Control (RC) SCADA', 'kri_unit': '%', 'kri_safe': '1.0', 'kri_caution': '90,00%', 'kri_danger': '< 90.00 %', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '1.0'}, {'source_row': 114, 'plan': 'Jasa Operasi dan Maintenance SCADA', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '3.8220219076608E9', 'actual_plan': '- Integrasi Kubikel 20 kV GI Sagulung\n- Pengadaan dan Pemasangan Standalone Fiber Optic Multiplexer\n- Pengadaan & Pemasangan Perangkat Teleproteksi \n- Pengadaan dan Peremajaan Frekuensi Recorder Gardu Induk\n- Pengembangan Remote Station Kubikel 20 kV Gardu Induk Tg Sengkuang\n- Pemasangan Remote I/O Feeder 20 kV Gardu Induk\n- Pengadaan Repeater Link Gardu Induk', 'actual_output': None, 'actual_cost': '117300000', 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses Persiapan Pekerjaan', 'progress_q1': '0.0', 'progress_q2': '0.03069056192', 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}, {'source_row': 115, 'plan': 'TMC Remote Station Gardu Distribusi & CCTV GI Tersebar', 'planned_output': 'Realisasi Pekerjaan', 'planned_cost': '1.59567117816297E9', 'actual_plan': '- Pengadaan Mobile Maintenance SCADA & Telekomunikasi PT PLN Batam\n- Pengadaan Preventive Maintenance & Recovery SCADA Gardu Distribusi, CCTV & Telekomunikasi PT PLN Batam', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN SCADA', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': 'Proses Pekerjaan', 'progress_q1': None, 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': None, 'kri_unit': None, 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '17.0', 'event': 'Implementasi set up EAM di pembangkit PLN Batam tidak optimal', 'cause_no': None, 'cause_text': 'Kurang nya pemahaman terhadap EAM', 'rows': [{'source_row': 116, 'plan': 'Mengikuti pelatihan untuk implementasi EAM unit pembangkit', 'planned_output': 'Monitoring progress set up implemnatasi EAM', 'planned_cost': None, 'actual_plan': None, 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MAN TRANS', 'timeline': ['1.0', None, None, None, None, None, None, None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': None, 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': 'Pencapaian Maturity level', 'kri_unit': '%', 'kri_safe': None, 'kri_caution': None, 'kri_danger': None, 'kri_threshold_actual': None, 'kri_value_actual': None}]}, {'source_risk_no': '18.0', 'event': 'Belum tercapainya target Kinerja & Kepatuhan K3L maupun Citra Perusahaan terhadap implementasi/pengelolaan K3L level beyond (di atas rata-rata/standard)', 'cause_no': None, 'cause_text': 'Tidak memanfaatkan anggaran dan sumber daya secara efektif untuk melakukan inovasi pada aspek K3L', 'rows': [{'source_row': 119, 'plan': 'Melakukan inovasi K3L dari pengefektifan penggunaan anggaran melalui Program-program Breakthorugh ataupun beyond compliance baik dari sisi sistem manajemen maupun best practice ', 'planned_output': 'Set up Sistem Manajemen K2 (SMK2) pada aspek pembangkitan dan Transmisi, PROPER Hijau pada aspek pembangkit, Digitalisasi K3 (inspeksi dan work permit), Modifikasi Sarana Peralatan K3L, Modifikasi Bangunan bekas menjadi TPS LB3 lingkup GI, Video Safety Induction, dll', 'planned_cost': '3594285600', 'actual_plan': 'Perbaikan Tambahan Sistem Hydran PLTD dan GI Tersebar', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'SM UBKITRANS', 'timeline': [None, None, None, None, None, None, None, None, None, None, None, None], 'source_status': 'Selesai', 'source_status_explanation': None, 'progress_q1': None, 'progress_q2': '1.0', 'progress_q3': None, 'progress_q4': None, 'kri': 'Pencapaian kinerja improvement K3L', 'kri_unit': '%', 'kri_safe': '100.0', 'kri_caution': '85 - 90', 'kri_danger': '< 85', 'kri_threshold_actual': '3. Hijau', 'kri_value_actual': '100.0'}]}, {'source_risk_no': '19.0', 'event': 'Terjadinya Kecelakaan Kerja', 'cause_no': None, 'cause_text': 'Gagalnya pengendalian dampak dari faktor unsafe action dan unsafe condition', 'rows': [{'source_row': 129, 'plan': 'Melakukan program-program yang mendukung visi zero accident baik berdasarkan regulasi maupun kebijakan internal perusahaan', 'planned_output': 'Sertifikasi Kompetensi K3, Sertifikasi K3 Peralatan,  Pengadaan Alat Pelindung Diri (APD) yang sesuai, Pengukuran K3 Lingkungan Kerja, dll.', 'planned_cost': '3.675651287E9', 'actual_plan': 'Pekerjaan KHS Pengangkutan Sampah Domestik UBKITRANS', 'actual_output': None, 'actual_cost': None, 'source_absorption': None, 'pic': 'MANDALKIT, MANTRANS', 'timeline': ['1.0', '1.0', '1.0', '1.0', '1.0', '1.0', '1.0', None, None, None, None, None], 'source_status': '2. Continue', 'source_status_explanation': None, 'progress_q1': None, 'progress_q2': None, 'progress_q3': None, 'progress_q4': None, 'kri': 'Jumlah/angka Kecelakaan Kerja', 'kri_unit': 'Kali', 'kri_safe': '0.0', 'kri_caution': '1.0', 'kri_danger': '> 1', 'kri_threshold_actual': '3. Bahaya', 'kri_value_actual': '0.0'}]}]
SOURCE_IIIA = [{'source_row': 11, 'source_code': '1-A-UBKITRANS-01', 'event': 'Realisasi pengoperasian pembangkit pada sistem Batam-Bintan tidak berjalan sesuai dengan rencana', 'jenis': 'Kuantitatif', 'assumption': 'Realisasi operasi sistem yang tidak sesuai rencana akan mengakibatkan kenaikan BPP sehingga PLN Batam akan mengeluarkan biaya produksi yang lebih tinggi dan PLN Batam akan mengalami kerugian.\n  Sampai dengan periode Juli 2026, BPP sebesar Rp 1.693,73\n/ kWh, dengan target BPP Rp 1.537,90/kWh dengan kWh produksi sd Juli 2026 sebesar 3.070.684,069 MWh.', 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': 'Efektif'}, {'source_row': 12, 'source_code': '3-D-UBKITRANS-02', 'event': 'Penyerapan Biaya Operasi melebihi pagu yang ditetapkan', 'jenis': 'Kualitatif', 'assumption': "Asumsi Perhitungan dampak dihitung sebagai dampak kualitatif dengan kategori kegagalan pencapaian program strategis '' Minimal 1 parameter tujuan strategis yang harus selesai pada tahun ini tertunda antara 2 - 3 bulan '' atau skala 2", 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': 'Efektif'}, {'source_row': 13, 'source_code': '3-E-UBKITRANS-03', 'event': 'Terjadinya pemadaman meluas dan atau blackout di sistem kelistrikan Batam - Bintan', 'jenis': 'Kualitatif', 'assumption': 'Apabila terjadi pemadaman meluas akan berdampak pada Citra Perusahaan Menurun. Dampak dihitung kualitatif dengan realisasi dampak kualitatif pada November pada skala 3\n "Publikasi negatif skala nasional yang tersebar di media konvensional"', 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': 'Efektif'}, {'source_row': 14, 'source_code': '4-O-UBKITRANS-04', 'event': 'Terjadi Defisit Daya Pada Sistem Batam-Bintan', 'jenis': 'Kuantitatif', 'assumption': 'Defisit daya akan menimbulkan energy not served (ENS) yang menjadi potensi kerugian bagi PLN Batam. Sampai dengan Periode November, terjadi trip hilang supply gangguan Master Trip Relay GIS Kabil dengan besar ENS 18.938 kWh', 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': 'Efektif'}, {'source_row': 15, 'source_code': '5-X-UBKITRANS-05', 'event': 'Pembangkit IPP dan PLN Batam mengalami derating atau gangguan', 'jenis': 'Kualitatif', 'assumption': "Asumsi Perhitungan dampak dihitung sebagai dampak kualitatif dengan kategori kegagalan pencapaian program strategis '' Minimal 1 parameter tujuan strategis yang harus selesai pada tahun ini tertunda antara 2 - 3 bulan '' atau skala 2", 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': 'Efektif'}, {'source_row': 16, 'source_code': '6-Y-UBKITRANS-06', 'event': 'Penyerapan gas dalam BTU/kWh oleh pembangkit sendiri dan sewa melebihi asumsi yang ditetapkan', 'jenis': 'Kuantitatif', 'assumption': None, 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': None}, {'source_row': 17, 'source_code': '7.0', 'event': 'Realisasi pelaksanaan pekerjaan tidak tepat waktu', 'jenis': 'Kualitatif', 'assumption': None, 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': None}, {'source_row': 18, 'source_code': '8.0', 'event': 'Terjadi panas berlebih pada sambungan konduktor Transmisi', 'jenis': 'Kuantitatif', 'assumption': 'Dalam menghitung dampak, dilakukan pendekatan dengan selisih persentase susut (0.187% - 0.185%) dikali dengan produksi tahun 2025', 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': 'Efektif'}, {'source_row': 19, 'source_code': '9.0', 'event': 'Pengadaan gagal', 'jenis': 'Kualitatif', 'assumption': "Asumsi Perhitungan dampak dihitung sebagai dampak kualitatif dengan kategori kegagalan pencapaian program strategis '' Minimal 1 parameter tujuan strategis yang harus selesai pada tahun ini tertunda antara 2 - 3 bulan '' atau skala 2", 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': None}, {'source_row': 20, 'source_code': '10.0', 'event': 'Tagihan tidak bisa terbayar tepat waktu', 'jenis': 'Kualitatif', 'assumption': "Asumsi Perhitungan dampak dihitung sebagai dampak kualitatif dengan kategori kegagalan pencapaian program strategis '' Minimal 1 parameter target strategis yang harus selesai pada tahun ini tertunda kurang dari 2-3 bulan '' atau skala 1", 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': None}, {'source_row': 21, 'source_code': '11.0', 'event': 'Keandalan Pembangkit PLN Batam tidak optimal', 'jenis': 'Kuantitatif', 'assumption': 'Keandalan pembangkit mempengaruhi jumlah kwh jual jika terjadi penurunan keandalan akan menurunkan produksi dan berdampak ke pendapatan PLN Batam. Asumsi perhitungan berdasarkan data realisasi tahun 2019 s.d 2023 dengan probabilitas 20 % dan penurunan EAF sebesar 4 %.', 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': 'nilai eksposur risiko masih tinggi karena belum dilakukan nya pemeliharaan pembangkit'}, {'source_row': 23, 'source_code': '12.0', 'event': 'Minimnya Awareness pegawai terhadap program Budaya perusahaan ( COC)', 'jenis': 'Kualitatif', 'assumption': "Asumsi Perhitungan dampak dihitung sebagai target HCR OCR ( COC ) pencapaian program strategis '' Minimal 1 parameter target strategis yang harus selesai pada tahun ini tertunda kurang dari 1 bulan'' atau skala 1", 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': None}, {'source_row': 24, 'source_code': '13.0', 'event': 'Minimnya Awareness pegawai terhadap Program Anti Black Out', 'jenis': 'Kualitatif', 'assumption': None, 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': None}, {'source_row': 25, 'source_code': '14.0', 'event': 'Pengadaan tidak terkontrak tepat waktu', 'jenis': None, 'assumption': None, 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': None}, {'source_row': 26, 'source_code': '15.0', 'event': 'Kesiapan perangkat SCADA dan telekomunikasi (Master Station, Remote Station, Telekomunikasi dan peripheral SCADA)', 'jenis': 'Kuantitatif', 'assumption': 'Asumsi perhitungan dampak dihitung sebagai target Availability Teleinformasi Data adalah dampak kualitatif dengan skala 2 "Minimal 1 parameter tujuan strategis yang harus selesai pada tahun ini tertunda antara 2 - 3 bulan "', 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': None}, {'source_row': 27, 'source_code': '16.0', 'event': 'Sistem SCADA tidak dapat bekerja secara optimal', 'jenis': 'Kualitatif', 'assumption': 'Asumsi Perhitungan dampak dihitung sebagai target Rasio Keberhasilan Remote Control (RC) SCADA skala 1 "Minimal 1 parameter target strategis yang harus selesai pada tahun ini tertunda kurang dari 1 bulan "', 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': None}, {'source_row': 28, 'source_code': '17.0', 'event': '\nImplementasi set up EAM di pembangkit PLN Batam tidak optimal', 'jenis': 'Kualitatif', 'assumption': None, 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': None}, {'source_row': 29, 'source_code': '18.0', 'event': 'Belum tercapainya target Kinerja & Kepatuhan K3L maupun Citra Perusahaan terhadap implementasi/pengelolaan K3L level beyond (di atas rata-rata/standard)', 'jenis': 'Kualitatif', 'assumption': 'Asumsi perhitungan dampak dihitung sebagai target Pencapaian kinerja improvement K3L adalah dampak kualitatif dengan skala 1 "Minimal 1 parameter target strategis yang harus selesai pada tahun ini tertunda kurang dari 1 bulan"', 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': None}, {'source_row': 30, 'source_code': '19.0', 'event': 'Terjadinya Kecelakaan Kerja', 'jenis': 'Kualitatif', 'assumption': 'Asumsi perhitungan dampak dihitung sebagai target jumlah terjadinya Kecelakaan Kerja adalah dampak kualitatif dengan skala 2 "Kasus Perawatan Medis "', 'q2': {'impact_value': None, 'impact_scale': None, 'probability_value': None, 'probability_scale': None, 'exposure': None, 'score': None, 'level': None}, 'effectiveness': None}]
REPRESENTATIVE_IDS = {1: 267, 2: 275, 3: 276, 4: 278, 5: 282, 6: 283, 7: 297, 8: 302, 9: None, 10: 325, 11: 333, 12: 334, 13: 340, 14: 345, 15: 348, 16: 351, 17: 353, 18: 354, 19: 355, 20: 356, 21: 360, 22: 364, 23: 366, 24: 368, 25: 370, 26: 371, 27: 374, 28: 375, 29: 379, 30: 380, 31: 381, 32: 382, 33: 387, 34: 389, 35: 390, 36: 391, 37: 395, 38: 398, 39: 399, 40: 400}

SRC02_TEXT = "Gangguan avaibility sumur gas Petrochina/Jadestone sehingga menggunakan gas interuptible PGN yang lebih  mahal"
SRC09_TEXT = (
    "Ketidaksiapan operasi peralatan Transmisi 150 kV akibat gangguan cuaca, kerusakan peralatan utama,\n"
    "sambaran petir, kondisi cuaca, pencurian peralatan dan Kesalahan operasi dan pemeliharaan peralatan transmisi."
)
SRC35_TEXT = "Dokumen penawaran yang disampaikan tidak lengkap"


def norm(v):
    s = str(v or "").casefold().replace("–", "-").replace("—", "-")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def D(v):
    if v in (None, "", "-"):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def money(v):
    d = D(v)
    if d is None:
        return None
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def percent_ratio(v):
    d = D(v)
    if d is None:
        return None
    return (d * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def field(model, name):
    return model._meta.get_field(name)


def empty_for(model, name):
    f = field(model, name)
    return None if getattr(f, "null", False) else ""


def first_unique(rows, key):
    out = []
    for r in rows:
        v = r.get(key)
        if v not in (None, "") and v not in out:
            out.append(v)
    return out


def numeric_values(rows, key):
    out = []
    for r in rows:
        d = D(r.get(key))
        if d is not None:
            out.append(d)
    return out


def nonnumeric_values(rows, key):
    out = []
    for r in rows:
        v = r.get(key)
        if v in (None, ""):
            continue
        if D(v) is None:
            out.append(str(v))
    return out


def event_source(event_text):
    matches = [x for x in SOURCE_IIIA if norm(x["event"]) == norm(event_text)]
    if len(matches) != 1:
        raise RuntimeError(
            f"STOP: source III.A event match count={len(matches)} for {event_text!r}"
        )
    return matches[0]


def aggregate_group(src):
    rows = src["rows"]

    treatment_lines = []
    output_lines = []
    status_lines = []

    for idx, row in enumerate(rows, start=1):
        p = str(row.get("plan") or "").strip()
        a = str(row.get("actual_plan") or "").strip()
        po = str(row.get("planned_output") or "").strip()
        ao = str(row.get("actual_output") or "").strip()

        t = f"{idx}. Rencana: {p}"
        if a:
            t += f"\n   Realisasi: {a}"
        treatment_lines.append(t)

        o = f"{idx}. Output rencana: {po}" if po else f"{idx}. Output rencana: -"
        if ao:
            o += f"\n   Realisasi output: {ao}"
        output_lines.append(o)

        st = str(row.get("source_status") or "").strip()
        ex = str(row.get("source_status_explanation") or "").strip()
        if st or ex:
            line = f"{idx}. Status sumber: {st or '-'}"
            if ex:
                line += f" | Penjelasan: {ex}"
            status_lines.append(line)

    plan_nums = numeric_values(rows, "planned_cost")
    actual_nums = numeric_values(rows, "actual_cost")
    plan_non = nonnumeric_values(rows, "planned_cost")
    actual_non = nonnumeric_values(rows, "actual_cost")

    planned_cost = sum(plan_nums, Decimal("0")) if plan_nums else None
    actual_cost = sum(actual_nums, Decimal("0")) if actual_nums else None

    # Explicit zero cells are legitimate numeric source values.
    planned_cost = money(planned_cost) if planned_cost is not None else None
    actual_cost = money(actual_cost) if actual_cost is not None else None

    q2 = numeric_values(rows, "progress_q2")
    progress = None
    if q2:
        progress = (
            sum(q2, Decimal("0")) / Decimal(len(q2)) * Decimal("100")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    source_statuses = first_unique(rows, "source_status")
    status_text = " | ".join(source_statuses)

    status_choice = None
    low = status_text.casefold()
    if "discontinue" in low:
        status_choice = "discontinue"
    elif "continue" in low:
        status_choice = "continue"

    # Mitigation status is a separate application status. Do not invent
    # progress values; only derive coarse status from explicit source text/activity.
    all_source_statuses = [str(x or "").casefold() for x in source_statuses]
    if all_source_statuses and all("selesai" in x for x in all_source_statuses):
        mitigation_status = "done"
    elif (
        any(str(r.get("actual_plan") or "").strip() for r in rows)
        or any(x > 0 for x in q2)
        or source_statuses
    ):
        mitigation_status = "on_progress"
    else:
        mitigation_status = "not_started"

    # June report: copy only Jan-Jun. Jul-Dec source flags are deliberately excluded.
    timeline = []
    for month_idx in range(12):
        if month_idx >= 6:
            timeline.append(0)
            continue
        vals = []
        for r in rows:
            raw = r.get("timeline", [None] * 12)[month_idx]
            d = D(raw)
            vals.append(int(d or 0))
        timeline.append(1 if any(vals) else 0)

    source_had_july = any(
        (D(r.get("timeline", [None] * 12)[6]) or Decimal("0")) > 0
        for r in rows
    )

    absorption = None
    if planned_cost is not None and actual_cost is not None:
        if planned_cost > 0:
            absorption = (
                actual_cost / planned_cost * Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif planned_cost == 0 and actual_cost == 0:
            absorption = Decimal("0.00")

    pics = first_unique(rows, "pic")
    pic_text = "\n".join(pics) if pics else None

    kri = first_unique(rows, "kri")
    kri_unit = first_unique(rows, "kri_unit")
    safe = first_unique(rows, "kri_safe")
    caution = first_unique(rows, "kri_caution")
    danger = first_unique(rows, "kri_danger")
    kri_threshold = first_unique(rows, "kri_threshold_actual")
    kri_actual = first_unique(rows, "kri_value_actual")

    kri_text_parts = []
    if kri:
        kri_text_parts.append("KRI sumber: " + " | ".join(kri))
    if kri_unit:
        kri_text_parts.append("Satuan: " + " | ".join(kri_unit))
    if safe:
        kri_text_parts.append("Aman: " + " | ".join(safe))
    if caution:
        kri_text_parts.append("Hati-hati: " + " | ".join(caution))
    if danger:
        kri_text_parts.append("Bahaya: " + " | ".join(danger))

    kri_numeric = None
    kri_actual_text = []
    for v in kri_actual:
        d = D(v)
        if d is not None and kri_numeric is None:
            kri_numeric = d
        elif d is None:
            kri_actual_text.append(str(v))
    if kri_actual_text:
        kri_text_parts.append("Nilai KRI sumber: " + " | ".join(kri_actual_text))

    if plan_non:
        status_lines.append(
            "Catatan nilai non-numerik pada kolom rencana biaya sumber: "
            + " | ".join(plan_non)
        )
    if actual_non:
        status_lines.append(
            "Catatan nilai non-numerik pada kolom realisasi biaya sumber: "
            + " | ".join(actual_non)
        )

    evt = event_source(src["event"])
    eff = str(evt.get("effectiveness") or "").strip()
    effectiveness_choice = None
    if norm(eff) == "efektif":
        effectiveness_choice = "efektif"
    elif norm(eff) == "tidak efektif":
        effectiveness_choice = "tidak_efektif"
    elif eff:
        status_lines.append("Efektivitas sumber: " + eff)

    return {
        "treatment_text": "\n".join(treatment_lines),
        "output_text": "\n".join(output_lines),
        "planned_cost": planned_cost,
        "actual_cost": actual_cost,
        "absorption": absorption,
        "progress": progress,
        "pic": pic_text,
        "timeline": timeline,
        "source_had_july": source_had_july,
        "status_choice": status_choice,
        "mitigation_status": mitigation_status,
        "status_explanation": "\n".join(status_lines) if status_lines else None,
        "kri_threshold": kri_threshold[0] if kri_threshold else None,
        "kri_numeric": kri_numeric,
        "kri_text": "\n".join(kri_text_parts) if kri_text_parts else None,
        "jenis_source": evt.get("jenis"),
        "assumption": evt.get("assumption"),
        "effectiveness_choice": effectiveness_choice,
    }


def expected_metrics():
    aggs = [aggregate_group(x) for x in SOURCE_GROUPS]
    total_plan = sum(
        (a["planned_cost"] or Decimal("0")) for a in aggs
    )
    total_actual = sum(
        (a["actual_cost"] or Decimal("0")) for a in aggs
    )
    q2_groups = sum(1 for a in aggs if a["progress"] is not None)
    july_groups = sum(1 for a in aggs if a["source_had_july"])
    return total_plan, total_actual, q2_groups, july_groups


def resolve_baseline():
    profile = (
        ReAssessmentSummary.objects
        .select_related("unit_bisnis", "kontrak_manajemen")
        .get(pk=PROFILE_ID)
    )
    if str(profile) != "Profil Risiko UBKITRANS":
        raise RuntimeError(f"STOP: unexpected profile {profile!r}")
    if profile.kontrak_manajemen_id != KM_ID:
        raise RuntimeError(
            f"STOP: KM id={profile.kontrak_manajemen_id}, expected={KM_ID}"
        )
    if str(profile.unit_bisnis) != "UB KITRAN":
        raise RuntimeError(f"STOP: unexpected unit={profile.unit_bisnis!r}")

    tahun = TahunBuku.objects.filter(tahun=YEAR).first()
    period = None
    if tahun:
        period = PeriodeLaporan.objects.filter(
            tahun_buku=tahun,
            kode_periode=PERIOD_CODE,
        ).first()

    user = get_user_model().objects.filter(
        pk=PREPARED_BY_ID,
        is_active=True,
    ).first()
    if not user:
        raise RuntimeError(
            f"STOP: prepared_by user id={PREPARED_BY_ID} not found/active."
        )

    return profile, tahun, period, user


def existing_june(profile):
    return (
        MonthlyRiskReport.objects
        .filter(
            reassessment=profile,
            tahun_buku__tahun=YEAR,
            periode__kode_periode=PERIOD_CODE,
        )
        .order_by("id")
        .first()
    )


def validate_representatives(profile):
    resolved = {}

    # Current 39 pre-existing representatives except source 09.
    for idx, expected_id in REPRESENTATIVE_IDS.items():
        if expected_id is None:
            continue
        try:
            item = ReAssessmentItem.objects.get(
                pk=expected_id,
                summary=profile,
                is_active=True,
            )
        except ReAssessmentItem.DoesNotExist:
            raise RuntimeError(
                f"STOP: representative SRC {idx:02d} expected RE={expected_id} not active."
            )

        src = SOURCE_GROUPS[idx - 1]
        if norm(item.peristiwa_risiko) != norm(src["event"]):
            raise RuntimeError(
                f"STOP: SRC {idx:02d} RE={item.id} event mismatch."
            )

        if idx not in (2, 35):
            if norm(item.penyebab_risiko) != norm(src["cause_text"]):
                raise RuntimeError(
                    f"STOP: SRC {idx:02d} RE={item.id} cause mismatch."
                )
        else:
            # V4 validated identity by event + cause code.
            if norm(item.no_penyebab_risiko) != norm(src["cause_no"]):
                raise RuntimeError(
                    f"STOP: SRC {idx:02d} RE={item.id} cause-code mismatch."
                )
            if MonthlyRiskReportItem.objects.filter(risk_event=item).exists():
                raise RuntimeError(
                    f"STOP: SRC {idx:02d} RE={item.id} unexpectedly has historical MRR refs."
                )

        resolved[idx] = item

    return resolved


def backup_sqlite():
    cfg = settings.DATABASES["default"]
    if "sqlite" not in cfg.get("ENGINE", ""):
        print("BACKUP: skipped; DB is not SQLite.")
        return None

    src = Path(cfg["NAME"]).resolve()
    dst_dir = Path("/home/adminsvr/backup")
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / (
        f"db_before_import_mrr_ubkitrans_jun_2026_"
        f"{datetime.now():%Y%m%d_%H%M%S}.sqlite3"
    )

    with sqlite3.connect(src) as s:
        with sqlite3.connect(dst) as t:
            s.backup(t)

    with sqlite3.connect(dst) as con:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]

    print("BACKUP    :", dst)
    print("INTEGRITY :", integrity)

    if integrity != "ok":
        raise RuntimeError("STOP: backup SQLite integrity_check failed.")

    return dst


def technical_new_risk_no(profile, no_item):
    vals = list(
        ReAssessmentItem.objects
        .filter(summary=profile, is_active=True, no_item=no_item)
        .values_list("no_risiko", flat=True)
    )
    vals = [int(x) for x in vals if x is not None]
    return max(vals or [0]) + 1


def create_source_cause_i(profile):
    existing = (
        ReAssessmentItem.objects
        .filter(
            summary=profile,
            is_active=True,
            no_item=3,
            no_penyebab_risiko__iexact="i",
        )
        .first()
    )
    if existing:
        if norm(existing.peristiwa_risiko) != norm(SOURCE_GROUPS[8]["event"]):
            raise RuntimeError("STOP: existing cause-i event mismatch.")
        return existing, False

    # Clone same-event structural row only as a schema-safe base.
    base = ReAssessmentItem.objects.get(pk=325, summary=profile, is_active=True)

    kwargs = {}
    for f in ReAssessmentItem._meta.concrete_fields:
        if f.primary_key:
            continue
        if f.is_relation and getattr(f, "many_to_one", False):
            kwargs[f.attname] = getattr(base, f.attname)
        else:
            kwargs[f.name] = getattr(base, f.name)

    src = SOURCE_GROUPS[8]
    agg = aggregate_group(src)

    kwargs.update(
        no_item=3,
        no_risiko=technical_new_risk_no(profile, 3),
        no_penyebab_risiko="i",
        peristiwa_risiko=src["event"],
        penyebab_risiko=SRC09_TEXT,
        key_risk_indicators="",
        unit_satuan_kri="",
        threshold_aman=(
            first_unique(src["rows"], "kri_safe")[0]
            if first_unique(src["rows"], "kri_safe")
            else ""
        ),
        threshold_hati_hati=(
            first_unique(src["rows"], "kri_caution")[0]
            if first_unique(src["rows"], "kri_caution")
            else ""
        ),
        threshold_bahaya=(
            first_unique(src["rows"], "kri_danger")[0]
            if first_unique(src["rows"], "kri_danger")
            else ""
        ),
        rencana_perlakuan_risiko="",
        output_perlakuan_risiko="",
        biaya_perlakuan_risiko=None,
        pos_anggaran="",
        prk="",
        jenis_program_dalam_rkap="",
        pic="",
    )

    # Do not inherit cause-j controls/treatment schedule into the new cause-i row.
    #
    # Some production fields (e.g. jenis_existing_control) are ForeignKeys.
    # Setting "" on a relation causes:
    #   ValueError: must be a Master... instance
    # Therefore clear relation fields through their attname (*_id) with None;
    # clear normal text fields with "".
    for name in (
        "jenis_existing_control",
        "existing_control",
    ):
        try:
            f = ReAssessmentItem._meta.get_field(name)
        except Exception:
            continue

        if getattr(f, "is_relation", False):
            kwargs.pop(name, None)
            kwargs[f.attname] = None
        else:
            kwargs[name] = ""

    if "penilaian_efektivitas_kontrol_id" in kwargs:
        kwargs["penilaian_efektivitas_kontrol_id"] = None
    if "opsi_perlakuan_risiko_id" in kwargs:
        kwargs["opsi_perlakuan_risiko_id"] = None
    if "pic_organization_unit_id" in kwargs:
        kwargs["pic_organization_unit_id"] = None
    if "pic_user_assignment_id" in kwargs:
        kwargs["pic_user_assignment_id"] = None

    for m in range(1, 13):
        kwargs[f"timeline_{m}"] = 0

    # Generic relation sanitizer.
    #
    # Several production fields that look like plain business-code/text fields
    # are actually ForeignKeys (for example pos_anggaran, and potentially
    # other master-data fields). V6 correctly fixed jenis_existing_control but
    # then stopped on pos_anggaran=''.
    #
    # For every concrete relation field:
    # - if a relation object/name key was accidentally assigned a string,
    #   remove that key and clear the FK through its attname (*_id)=None;
    # - preserve already-valid *_id values copied from the structural base.
    for f in ReAssessmentItem._meta.concrete_fields:
        if not getattr(f, "is_relation", False):
            continue

        if f.name in kwargs and isinstance(kwargs[f.name], str):
            kwargs.pop(f.name, None)
            kwargs[f.attname] = None

        # Defensive stop: an FK attname must never contain a string.
        if f.attname in kwargs and isinstance(kwargs[f.attname], str):
            raise RuntimeError(
                f"STOP: invalid relation id assignment before create: "
                f"{f.attname}={kwargs[f.attname]!r}"
            )

    obj = ReAssessmentItem.objects.create(**kwargs)
    return obj, True


def ensure_period(tahun, period):
    if tahun is None:
        tahun = TahunBuku.objects.create(tahun=YEAR, aktif=True)

    if period is None:
        last_day = calendar.monthrange(YEAR, MONTH)[1]
        period = PeriodeLaporan.objects.create(
            tahun_buku=tahun,
            kode_periode=PERIOD_CODE,
            nama_periode=f"Juni {YEAR}",
            jenis_periode="bulanan",
            tanggal_mulai=f"{YEAR}-06-01",
            tanggal_selesai=f"{YEAR}-06-{last_day:02d}",
            is_locked=False,
        )
    return tahun, period


def set_nullable(obj, name, value):
    f = field(obj.__class__, name)
    if value is None:
        setattr(obj, name, None if getattr(f, "null", False) else "")
    else:
        setattr(obj, name, value)


def make_monthly_item(report, risk_event, src):
    agg = aggregate_group(src)
    evt = event_source(src["event"])

    obj = MonthlyRiskReportItem(
        report=report,
        risk_event=risk_event,
        km_item=risk_event.km_item,
    )

    jenis = norm(evt.get("jenis"))
    if jenis == "kuantitatif":
        set_nullable(obj, "jenis_risiko", "kuantitatif")
    elif jenis == "kualitatif":
        set_nullable(obj, "jenis_risiko", "kualitatif")
    else:
        set_nullable(obj, "jenis_risiko", None)

    set_nullable(obj, "realisasi_asumsi_dampak", evt.get("assumption"))

    # Source Q2 III.A is blank. Do not infer from Q1/profile.
    obj.realisasi_nilai_dampak = None
    obj.realisasi_skala_dampak = None
    obj.realisasi_nilai_probabilitas = None
    obj.realisasi_skala_probabilitas = None
    obj.realisasi_eksposur = None
    obj.realisasi_skor_risiko = None
    set_nullable(obj, "realisasi_level_risiko", None)

    if "realisasi_skala_dampak_kbumn" in {f.name for f in obj._meta.fields}:
        obj.realisasi_skala_dampak_kbumn = None
    if "realisasi_skala_probabilitas_kbumn" in {f.name for f in obj._meta.fields}:
        obj.realisasi_skala_probabilitas_kbumn = None
    if "realisasi_skala_nilai_risiko_kbumn" in {f.name for f in obj._meta.fields}:
        obj.realisasi_skala_nilai_risiko_kbumn = None
    if "realisasi_level_risiko_bumn" in {f.name for f in obj._meta.fields}:
        set_nullable(obj, "realisasi_level_risiko_bumn", None)
    if "realisasi_level_risiko_kbumn" in {f.name for f in obj._meta.fields}:
        set_nullable(obj, "realisasi_level_risiko_kbumn", None)

    set_nullable(
        obj,
        "efektivitas_perlakuan_risiko",
        agg["effectiveness_choice"],
    )

    obj.realisasi_rencana_perlakuan = agg["treatment_text"]
    obj.realisasi_output_perlakuan = agg["output_text"]
    obj.realisasi_biaya_perlakuan = agg["actual_cost"]
    if "rencana_biaya_perlakuan" in {f.name for f in obj._meta.fields}:
        obj.rencana_biaya_perlakuan = agg["planned_cost"]
    obj.persentase_serapan_biaya = agg["absorption"]

    set_nullable(obj, "realisasi_pic", agg["pic"])
    obj.realisasi_pic_organization_unit = None

    set_nullable(
        obj,
        "status_rencana_perlakuan",
        agg["status_choice"],
    )
    set_nullable(
        obj,
        "penjelasan_status_rencana",
        agg["status_explanation"],
    )

    obj.progress_pelaksanaan_percent = agg["progress"]
    obj.mitigation_progress_percent = agg["progress"]
    obj.mitigation_status = agg["mitigation_status"]

    for m, value in enumerate(agg["timeline"], start=1):
        setattr(obj, f"realisasi_timeline_{m}", int(value))

    set_nullable(obj, "realisasi_threshold_kri", agg["kri_threshold"])

    # KRI safety rule:
    # MonthlyRiskReportItem.save() evaluates numeric KRI against the profile's
    # kri_threshold_direction. Several legacy UB KITRANS profile rows do not
    # have that direction configured. Source values must still be preserved,
    # but we must not invent a threshold direction.
    #
    # Therefore:
    # - with configured direction: store numeric KRI normally;
    # - without configured direction: keep numeric field NULL and append the
    #   source numeric value to realisasi_kri_text.
    kri_text = agg["kri_text"]
    direction = getattr(risk_event, "kri_threshold_direction", None)

    if agg["kri_numeric"] is not None and direction not in (None, ""):
        obj.realisasi_nilai_kri = agg["kri_numeric"]
    else:
        obj.realisasi_nilai_kri = None
        if agg["kri_numeric"] is not None:
            extra = f"Nilai KRI sumber (numeric): {agg['kri_numeric']}"
            kri_text = f"{kri_text}\n{extra}" if kri_text else extra

    set_nullable(obj, "realisasi_kri_text", kri_text)
    obj.realisasi_threshold_kri_skor = None

    obj.trend = None
    obj.issue_summary = None
    obj.next_action = None
    obj.escalation_note = None
    obj.save()

    return obj


def preview(profile, tahun, period, user, reps):
    total_plan, total_actual, q2_groups, july_groups = expected_metrics()

    print("=" * 180)
    print("IMPORT PREVIEW - MRR UB KITRANS JUNI 2026 V8")
    print("=" * 180)
    print("Profile                    :", profile.id, profile)
    print("Unit                       :", profile.unit_bisnis)
    print("KM                         :", profile.kontrak_manajemen_id, profile.kontrak_manajemen)
    print("TahunBuku                  :", getattr(tahun, "id", None), tahun)
    print("Periode                    :", getattr(period, "id", None), period)
    print("Prepared by                :", user.id, user)
    print("Existing June MRR          :", existing_june(profile))
    print("Source events III.A        :", len(SOURCE_IIIA))
    print("Source unique causes III.B :", len(SOURCE_GROUPS))
    print("Source treatment rows      :", sum(len(x["rows"]) for x in SOURCE_GROUPS))
    print("Q2 residual source         : BLANK 19/19")
    print("Q2 progress populated      :", q2_groups, "/ 40 cause groups")
    print("Source July timeline flags :", july_groups, "/ 40 cause groups")
    print("June timeline policy       : month 7-12 EXCLUDED from MRR June")
    print("III.D                      : 0 source rows")
    print("III.E                      : 0 source rows")

    kri_numeric_groups = 0
    kri_direction_ready = 0
    kri_text_fallback = 0
    for idx in range(1, 41):
        agg = aggregate_group(SOURCE_GROUPS[idx - 1])
        if agg["kri_numeric"] is None:
            continue
        kri_numeric_groups += 1
        item = reps.get(idx)
        if item is not None and getattr(item, "kri_threshold_direction", None) not in (None, ""):
            kri_direction_ready += 1
        else:
            kri_text_fallback += 1

    print("KRI numeric source groups  :", kri_numeric_groups)
    print("KRI direction configured   :", kri_direction_ready)
    print("KRI numeric text fallback  :", kri_text_fallback)
    print("Expected planned cost sum  :", total_plan)
    print("Expected actual cost sum   :", total_actual)
    print()
    print("PROFILE SOURCE ALIGNMENT:")
    print("  RE275 cause text :", repr(reps[2].penyebab_risiko), "->", repr(SRC02_TEXT))
    print("  SRC09 cause i    : CREATE (no active/history row exists)")
    print("  RE390 cause text :", repr(reps[35].penyebab_risiko), "->", repr(SRC35_TEXT))
    print()
    print("REPRESENTATIVE MAPPING:")
    for idx in range(1, 41):
        src = SOURCE_GROUPS[idx - 1]
        re_id = reps[idx].id if idx in reps else "CREATE-i"
        agg = aggregate_group(src)
        print(
            f"SRC {idx:02d} -> RE={re_id!s:<8} | "
            f"activities={len(src['rows']):<2} | "
            f"Q2_progress={str(agg['progress']):<8} | "
            f"plan_cost={str(agg['planned_cost']):<16} | "
            f"actual_cost={str(agg['actual_cost']):<16} | "
            f"event={src['event'][:68]!r}"
        )

    print()
    print("Database : BELUM DIUBAH")


def postcheck(profile, report, reps, cause_i):
    items = list(
        MonthlyRiskReportItem.objects
        .filter(report=report)
        .select_related("risk_event")
        .order_by("id")
    )

    if len(items) != 40:
        raise RuntimeError(
            f"STOP postcheck: monthly items={len(items)}, expected=40."
        )

    if len({x.risk_event_id for x in items}) != 40:
        raise RuntimeError("STOP postcheck: duplicate risk_event in June MRR.")

    distinct_events = {
        norm(x.risk_event.peristiwa_risiko)
        for x in items
    }
    if len(distinct_events) != 19:
        raise RuntimeError(
            f"STOP postcheck: distinct source events={len(distinct_events)}, expected=19."
        )

    source_events = {norm(x["event"]) for x in SOURCE_IIIA}
    if distinct_events != source_events:
        raise RuntimeError("STOP postcheck: monthly event set != source 19 event set.")

    if MonthlyRiskReportLossEvent.objects.filter(report=report).exists():
        raise RuntimeError("STOP postcheck: III.E should be empty.")

    # Source Q2 residual is blank; every monthly item must remain blank.
    for x in items:
        fields = [
            x.realisasi_nilai_dampak,
            x.realisasi_skala_dampak_id,
            x.realisasi_nilai_probabilitas,
            x.realisasi_skala_probabilitas_id,
            x.realisasi_eksposur,
            x.realisasi_skor_risiko,
            x.realisasi_level_risiko,
        ]
        if any(v not in (None, "") for v in fields):
            raise RuntimeError(
                f"STOP postcheck: MRI={x.id} has invented Q2 residual values."
            )

        # KRI direction safety: if direction is absent, numeric KRI must remain
        # NULL. Source numeric value, when any, is preserved in KRI text.
        if getattr(x.risk_event, "kri_threshold_direction", None) in (None, ""):
            if x.realisasi_nilai_kri is not None:
                raise RuntimeError(
                    f"STOP postcheck: MRI={x.id} has numeric KRI without "
                    "kri_threshold_direction."
                )

        # June clipping.
        for m in range(7, 13):
            if getattr(x, f"realisasi_timeline_{m}") != 0:
                raise RuntimeError(
                    f"STOP postcheck: MRI={x.id} month {m} timeline not clipped."
                )

    # Profile source corrections.
    p275 = ReAssessmentItem.objects.get(pk=275)
    p390 = ReAssessmentItem.objects.get(pk=390)
    if norm(p275.penyebab_risiko) != norm(SRC02_TEXT):
        raise RuntimeError("STOP postcheck: RE275 source cause not aligned.")
    if norm(p390.penyebab_risiko) != norm(SRC35_TEXT):
        raise RuntimeError("STOP postcheck: RE390 source cause not aligned.")
    cause_i.refresh_from_db()
    if not cause_i.is_active:
        raise RuntimeError("STOP postcheck: source cause i is not active.")
    if cause_i.no_item != 3 or norm(cause_i.no_penyebab_risiko) != "i":
        raise RuntimeError("STOP postcheck: source cause i identity mismatch.")
    if norm(cause_i.penyebab_risiko) != norm(SRC09_TEXT):
        raise RuntimeError("STOP postcheck: source cause i text mismatch.")

    # Two legacy events absent from source must not be inserted.
    if MonthlyRiskReportItem.objects.filter(
        report=report,
        risk_event_id__in=[386, 388],
    ).exists():
        raise RuntimeError("STOP postcheck: legacy non-source events were imported.")

    total_plan, total_actual, _, _ = expected_metrics()
    db_plan = sum(
        (x.rencana_biaya_perlakuan or Decimal("0"))
        for x in items
    )
    db_actual = sum(
        (x.realisasi_biaya_perlakuan or Decimal("0"))
        for x in items
    )
    if db_plan != total_plan:
        raise RuntimeError(
            f"STOP postcheck: planned total={db_plan}, expected={total_plan}"
        )
    if db_actual != total_actual:
        raise RuntimeError(
            f"STOP postcheck: actual total={db_actual}, expected={total_actual}"
        )

    return items


def apply_import(profile, tahun, period, user, reps):
    if existing_june(profile):
        raise RuntimeError("STOP: June MRR already exists.")

    backup_sqlite()

    with transaction.atomic():
        # Lock baseline identity rows.
        profile = ReAssessmentSummary.objects.select_for_update().get(pk=PROFILE_ID)
        locked_275 = ReAssessmentItem.objects.select_for_update().get(pk=275)
        locked_390 = ReAssessmentItem.objects.select_for_update().get(pk=390)

        if MonthlyRiskReportItem.objects.filter(
            risk_event_id__in=[275, 390]
        ).exists():
            raise RuntimeError(
                "STOP: RE275/RE390 acquired historical MRR refs; rollback."
            )

        # Source-exact corrections. QuerySet.update avoids unrelated model save
        # side effects/recalculations.
        ReAssessmentItem.objects.filter(pk=275).update(
            penyebab_risiko=SRC02_TEXT
        )
        ReAssessmentItem.objects.filter(pk=390).update(
            penyebab_risiko=SRC35_TEXT
        )

        cause_i, created_i = create_source_cause_i(profile)
        if not created_i:
            raise RuntimeError(
                f"STOP: source cause-i unexpectedly existed as RE={cause_i.id}; "
                "V8 apply requires audited pre-import baseline."
            )

        reps = dict(reps)
        reps[2] = ReAssessmentItem.objects.get(pk=275)
        reps[9] = cause_i
        reps[35] = ReAssessmentItem.objects.get(pk=390)

        tahun, period = ensure_period(tahun, period)

        if existing_june(profile):
            raise RuntimeError("STOP: June MRR appeared during apply.")

        report = MonthlyRiskReport.objects.create(
            kode=REPORT_CODE,
            tahun_buku=tahun,
            periode=period,
            unit=None,
            kontrak_manajemen=profile.kontrak_manajemen,
            reassessment=profile,
            versi=1,
            status="draft",
            prepared_by=user,
        )

        created = []
        for idx in range(1, 41):
            created.append(
                make_monthly_item(
                    report,
                    reps[idx],
                    SOURCE_GROUPS[idx - 1],
                )
            )

        report.total_risiko = 19
        report.total_high = 0
        report.total_mitigasi_terlambat = 0
        report.total_selesai = 0
        report.save(update_fields=[
            "total_risiko",
            "total_high",
            "total_mitigasi_terlambat",
            "total_selesai",
            "updated_at",
        ])

        checked = postcheck(profile, report, reps, cause_i)

    # DB health after transaction commit.
    cfg = settings.DATABASES["default"]
    integrity = None
    fk_errors = None
    if "sqlite" in cfg.get("ENGINE", ""):
        with sqlite3.connect(cfg["NAME"]) as con:
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk_errors:
            raise RuntimeError(
                f"POST-COMMIT DB HEALTH FAILED: integrity={integrity}, fk={fk_errors}"
            )

    total_plan, total_actual, q2_groups, july_groups = expected_metrics()

    print()
    print("=" * 180)
    print("APPLY BERHASIL - MRR UB KITRANS JUNI 2026")
    print("=" * 180)
    print("Profile ID                  :", profile.id)
    print("MRR ID                      :", report.id)
    print("MRR code                    :", report.kode)
    print("Period                      :", report.periode)
    print("Status                      :", report.status)
    print("Prepared by                 :", report.prepared_by)
    print("Source risk events          :", 19)
    print("Monthly cause items         :", len(checked))
    print("Source treatment rows       :", 106)
    print("New source cause-i RE       :", cause_i.id)
    print("RE275 source correction     : OK")
    print("RE390 source correction     : OK")
    print("Q2 residual imported        : 0/40 (source blank)")
    print("Q2 progress populated       :", q2_groups, "/ 40")
    print("July timeline groups clipped:", july_groups, "/ 40")
    print("III.E loss events           :", 0)
    print("Planned cost total          :", total_plan)
    print("Actual cost total           :", total_actual)
    print("integrity_check             :", integrity)
    print("foreign_key_check           :", len(fk_errors or []), "error")
    print("=" * 180)

    for x in checked:
        print(
            f"MRI={x.id:<5} | RE={x.risk_event_id:<4} | "
            f"no_item={x.risk_event.no_item!s:<3} | "
            f"cause={x.risk_event.no_penyebab_risiko!s:<4} | "
            f"progress={x.progress_pelaksanaan_percent!s:<8} | "
            f"plan_cost={x.rencana_biaya_perlakuan!s:<16} | "
            f"actual_cost={x.realisasi_biaya_perlakuan!s:<16} | "
            f"event={x.risk_event.peristiwa_risiko[:70]!r}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit June 2026 import.",
    )
    args = parser.parse_args()

    profile, tahun, period, user = resolve_baseline()

    if existing_june(profile):
        raise RuntimeError(
            f"STOP: June MRR already exists: {existing_june(profile)}"
        )

    reps = validate_representatives(profile)
    preview(profile, tahun, period, user, reps)

    if not args.apply:
        print()
        print("DRY-RUN V8 OK. Database belum diubah.")
        print("Jika preview sesuai, jalankan ulang dengan --apply.")
        return

    apply_import(profile, tahun, period, user, reps)


if __name__ == "__main__":
    main()
