#!/usr/bin/env python3
"""
Safe importer Laporan Profil Risiko SM UBDISYAN — Mei, Juni, Juli 2026.

Sumber resmi:
- Laporan Risiko Bulan Mei(1).xlsx
- Laporan Risiko Bulan Juni(1).xlsx
- Laporan Risiko Bulan Juli(1).xlsx

Prinsip:
- Default AUDIT SAJA; --apply untuk commit.
- Profil/master risiko/KM TIDAK diubah oleh importer ini.
- Sumber memiliki 18 nomor risiko, tetapi no. 8 dan 9 identik pada KPI,
  peristiwa dan KRI (Penyelesaian Program Improvement K3L / kecelakaan kerja /
  Zero Accident). Keduanya dikonsolidasikan menjadi satu MonthlyRiskReportItem,
  sehingga canonical monthly risk = 17 item.
- Mapping source -> ReAssessmentItem memakai event + KRI, dengan representative
  dari laporan existing terakhir bila source mempunyai duplicate causes.
- Mei/Juni memakai snapshot residual Q2; Juli memakai Q3. TANPA fallback ke Q1.
  Jika Q2/Q3 kosong pada workbook, nilai residual bulanan tetap kosong.
- Untuk risiko kualitatif, nilai dampak numerik tidak dipaksakan.
- III.B diaggregasi per risiko: treatment/output digabung, actual cost dijumlahkan,
  source absorption dihitung dari total actual / total planned source.
- Source tidak menyediakan KRI actual/status/progress pada kolom bulanan yang
  relevan; nilai tersebut dibiarkan kosong, bukan dibuat-buat.
- Workbook ini tidak menyediakan sheet III.D/III.E terpisah; importer tidak
  mengubah change/loss-event existing.
- --apply membuat backup SQLite dan semua bulan diproses transaction.atomic().
"""
from __future__ import annotations

import argparse
import calendar
import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.prod")

import django
django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction

from masterdata.models import PeriodeLaporan, TahunBuku
from monthly_report.models import MonthlyRiskReport, MonthlyRiskReportItem
from risk.models import MasterSkalaDampak, MasterSkalaProbabilitas, ReAssessmentItem, ReAssessmentSummary

YEAR = 2026
PROFILE_TITLE = "Profil Risiko UBDISYAN"
UNIT_NAME = "UB DISYAN"
EXPECTED_CANONICAL = 17
ALLOWED_STATUSES = {"draft", "revision"}
SOURCE_HASHES = {5: '346b4e4bd3901a2953512380c6bdd80890a27a687e7295d56591eff2cf77838f',
 6: '99dedf6e18c4cf8cf1e452f2fdd3b53ecf437cc616e590995276552a4d6b9660',
 7: 'f1391f5deec3531630c88aa90828b04baf2548276502b8dc6bb527aaff338baa'}
SOURCE = {5: {'month': 5,
     'month_name': 'Mei',
     'residual_snapshot': 'Q2',
     'items': {1: {'source_no': 1,
                   'indicator': 'Growth Penjualan Tenaga Listrik TUL 309 Batam sebesar 5.015,01 GWh',
                   'event': 'Penjualan Ekstensifikasi tidak sesuai dengan perencanaan',
                   'description': 'Potensi - potensi pasar yang menjadi dasar perencanaan 2026 tidak sesuai perencaan',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-1-a',
                   'cause': 'Potensi - potensi pasar yang menjadi dasar perencanaan 2026 realisasi tidak sesuai',
                   'kri': 'Penambahan Pelanggan TM (Additional Demand)',
                   'kri_unit': 'MVA',
                   'kri_safe': 60,
                   'kri_caution': '> 50 - < 60',
                   'kri_danger': 50,
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Realisasi daya tersambung layanan khusus pelanggan TM 2025',
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Melakukan komunikasi intensif dengan pelanggan yang termasuk dalam potensi pasar serta melakukan probing untuk '
                                       'mengidentifikasi calon pelanggan di luar potensi yang terdata\n'
                                       '---\n'
                                       'Melakukan percepatan penyambungan pelanggan\n'
                                       '---\n'
                                       'Peningkatan rasio elektrisifikasi dengan program listrik desa\n'
                                       '---\n'
                                       'Mengadakan promosi produk layanan misalnya gratis naik daya',
                   'actual_output': None,
                   'planned_cost_source': 96466576981.79527,
                   'actual_cost': 38917951254.0,
                   'absorption_source': 0.40343456222505353,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [10, 11, 12, 13]},
               2: {'source_no': 2,
                   'indicator': 'Percepatan Sambungan Pelanggan (tanpa perluasan jaringan): 1hari untuk 1 phasa, 3 hari untuk 3 phasa TR, dan 5 hari untuk TM',
                   'event': 'Tidak tersedianya material penyambungan',
                   'description': 'Terlambatnya penyambungan pelanggan akibat tidak tersedianya material',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-2-a',
                   'cause': 'Keterlambatan kedatangan material di gudang',
                   'kri': 'Stock minimum material',
                   'kri_unit': '%',
                   'kri_safe': '≥ 100%',
                   'kri_caution': '≥95 - <100%',
                   'kri_danger': '<95',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': '- History TMP Material kosong 2022 - 2025\n- Hasil evaluasi SDS 2025',
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Monitoring kecukupan material (Material Distribusi Utama dan Material Pendukung) berdasarkan stok minimum material',
                   'actual_output': None,
                   'planned_cost_source': None,
                   'actual_cost': 0.0,
                   'absorption_source': None,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [14]},
               3: {'source_no': 3,
                   'indicator': 'Penambahan Pelanggan Layanan Khusus sebesar 147,89 MVA',
                   'event': 'Tidak terpenuhi target jumlah pelanggan produk layanan khusus',
                   'description': 'Kurangnya minat pelanggan atas produk layanan khusus di tahun 2026',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-3-a',
                   'cause': 'Kurangnya strategi marketing untuk produk layanan khusus',
                   'kri': 'HJR LAYANAN KHUSUS',
                   'kri_unit': 'Rupiah/kWh',
                   'kri_safe': '>Rp 1.500',
                   'kri_caution': 'RP 1.400 - Rp 1.500',
                   'kri_danger': '< Rp 1.400',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Realisasi daya tersambung layanan khusus pelanggan TM 2022 - 2025',
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Pasang Baru pelanggan TM, diberikan dengan taif layanan khusus',
                   'actual_output': None,
                   'planned_cost_source': 293694476034.675,
                   'actual_cost': 11899261436.0,
                   'absorption_source': 0.040515782239619366,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [15]},
               4: {'source_no': 4,
                   'indicator': 'System Average Interruption Duration Index  (SAIDI) Distribusi 31,52 Menit/Plg',
                   'event': 'Waktu penanganan gangguan terlalu lama',
                   'description': 'Lamanya waktu penanganan gangguan mengakibatkan tingginya  nilai ENS',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-4-a',
                   'cause': 'pencarian titik gangguan yang lama',
                   'kri': 'Recovery Time',
                   'kri_unit': 'Menit',
                   'kri_safe': '≥ 120',
                   'kri_caution': '≥100 - <120',
                   'kri_danger': '< 100',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Nilai ENS akibat gangguan jaringan distribusi',
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Pemasangan Recloser untuk percepatan pemulihan gangguan\n'
                                       '---\n'
                                       'Upgrade Kubikel LBS menjadi CB di GT Existing (ZDT)\n'
                                       '---\n'
                                       'Pemasangan GD Kios untuk percepatan pemulihan sistem',
                   'actual_output': None,
                   'planned_cost_source': 16427421000.0,
                   'actual_cost': 0.0,
                   'absorption_source': 0.0,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [16, 17, 18]},
               5: {'source_no': 5,
                   'indicator': 'System Average Interruption Frequency Index  (SAIFI) Distribusi 0,3 Kali/Plg',
                   'event': 'Terjadi gangguan penyulang',
                   'description': 'seringga terjadi gangguan mengakibatkan tingginya  nilai ENS',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-5-a',
                   'cause': 'Kurangnya pengawasan pekerjaan utilitas',
                   'kri': 'Jumlah gangguan penyulang karena pekerjaan utilitas',
                   'kri_unit': 'Kali',
                   'kri_safe': '<10',
                   'kri_caution': '≥ 10-<12',
                   'kri_danger': '≥ 12',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Nilai ENS akibat utilitas',
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Melakukan ground patrol dan pengawasan secara langsung di laapangan dengan terjadwal\n'
                                       '---\n'
                                       'Upgrade Kubikel Air Insulated (Plg TM) / VM6-MG & Siemens RMU\n'
                                       '---\n'
                                       'Upgrade  Arester & FCO/Arester dan Pemasangan grounding pentanahan pada Gardu Portal\n'
                                       '---\n'
                                       'peningkatan kehandalan dengan melkukan Upgrade SUTM Menjadi SKTM\n'
                                       '---\n'
                                       'Peningkatan kehandalan dengan Upgrade Jaringan Distribusi  (rekonduktor tegangan drop, pecah beban jurusan, upgrade '
                                       'JTR dan SR Berderet)\n'
                                       '---\n'
                                       'Melaksanakan kepatuhan terhadap peraturan perundang-undangan yang mengatur operasi Sistem Distribusi.\n'
                                       '---\n'
                                       'Upaya percepatan pengadaan material dan peralatan pemeliharaan\n'
                                       '---\n'
                                       'Melaksanakan pekerjaan pemeliharaan Distribusi',
                   'actual_output': None,
                   'planned_cost_source': 36055097939.4439,
                   'actual_cost': 4762956295.0,
                   'absorption_source': 0.13210215939503456,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [19, 20, 21, 22, 23, 24, 25, 26]},
               6: {'source_no': 6,
                   'indicator': 'Susut Jaringan Distribusi 3,3%',
                   'event': 'Penyalahgunaan penggunaan tenaga listrik',
                   'description': 'Adanya penggunaan tegangan listrik secara illegal',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-6-a',
                   'cause': 'Perilaku pelanggan yang cenderung ingin melakukan penghematan',
                   'kri': 'Pelaksanaan P2TL Gabungan',
                   'kri_unit': 'MWh',
                   'kri_safe': '≥ 13000',
                   'kri_caution': '≥10000 - <13000',
                   'kri_danger': '<10000',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Realisasi P2TL 2022 - 2025',
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'P2TL Gabungan\n'
                                       '---\n'
                                       'Melakukan Upgrade kWh Tua\n'
                                       '---\n'
                                       'Mnjaga kelancaran kualitas komunikasi modem AMR\n'
                                       '---\n'
                                       'menjadikan koreksi rekening sebagai SLA petugas baca meter pda kontrak kerjasama manbill\n'
                                       '---\n'
                                       'Pembuatan Gardu Sisip',
                   'actual_output': None,
                   'planned_cost_source': 17931639178.561966,
                   'actual_cost': 711038819.0,
                   'absorption_source': 0.03965275075633225,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [27, 28, 29, 30, 31]},
               7: {'source_no': 7,
                   'indicator': 'Pemenuhan Kualitas Penerapan Manajemen Risiko 100%',
                   'event': 'Tidak terpenuhinya parameter kualitas manajemen risiko',
                   'description': 'Tidak Comply terhadap PER-2 KBUMN Tahun 2023',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-7-a',
                   'cause': 'Budaya sadar risiko, kapabilitas dan tata kelola belum terimplementasi secara efektif, efisien dan menyeluruh',
                   'kri': 'Jumlah Program Pemenuhan',
                   'kri_unit': '%',
                   'kri_safe': 1,
                   'kri_caution': 'N/A',
                   'kri_danger': 'N/A',
                   'risk_type': 'Kualitatif',
                   'impact_assumption': None,
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Monitoring  berkala (bulanan)',
                   'actual_output': None,
                   'planned_cost_source': None,
                   'actual_cost': 0.0,
                   'absorption_source': None,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [32]},
               8: {'source_no': '8+9',
                   'indicator': 'Penyelesaian Program Improvement K3L 100%',
                   'event': 'Terjadinya kecelakan kerja',
                   'description': 'Terjadi kecelakaan pada saat bekerja',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-8-a',
                   'cause': 'Kurangnya awareness terhadap peratran - peraturan yang telah ditetapkan',
                   'kri': 'Zero Accident',
                   'kri_unit': 'kali',
                   'kri_safe': 1,
                   'kri_caution': 1,
                   'kri_danger': 0,
                   'risk_type': 'Kualitatif',
                   'impact_assumption': 'Kejadian kecelakaan kerja 2023',
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Implementasi Aplikasi Inspekta\n'
                                       '---\n'
                                       'Inspeksi HSSE SM/MU/MUP3\n'
                                       '---\n'
                                       'Inspeksi Perlengkapan K3 (APD, Alat Pemadam)\n'
                                       '---\n'
                                       'Simulasi Tanggap Darurat\n'
                                       '---\n'
                                       'Laporan Kesiapan SISPROK (Sistem Proteksi Kebakaran)\n'
                                       '---\n'
                                       'Penerapan SMK2\n'
                                       '---\n'
                                       'Rapat P2K3 (Panitia Pembina Keselamatan Dan Kesehatan Kerja)\n'
                                       '---\n'
                                       'Sertifikat Laik Operasi\n'
                                       '---\n'
                                       'Implementasi 5R/5S',
                   'actual_output': None,
                   'planned_cost_source': 76500000.0,
                   'actual_cost': 12165000.0,
                   'absorption_source': 0.15901960784313726,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [33, 34, 35, 36, 37, 38, 39, 40, 41],
                   'source_numbers': [8, 9]},
               10: {'source_no': 10,
                    'indicator': 'Maturity Level Sustainability 100%',
                    'event': 'Lambatnya respon dalam pemenuhan data penilaian / assesment',
                    'description': 'Lambatnya respon dalam pemenuhan data penilaian / assesment',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-10-a',
                    'cause': 'ketidak tersediaan data untuk pemenuhan kriteria penilian',
                    'kri': 'Maturity level',
                    'kri_unit': '%',
                    'kri_safe': 1,
                    'kri_caution': '85% - 99%',
                    'kri_danger': '< 85%',
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Pemenuhan dokumen/data dukung penilaian maturity level korporat',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [42]},
               11: {'source_no': 11,
                    'indicator': 'Pendapatan dari luar PLN Group (exclude PTL) sebesar Rp 1 M',
                    'event': 'Pelanggan tidak mengetahui layanan beyond kwh yang tersdia di PLN Batam',
                    'description': 'Tidak tercapainya kinerja beyond kwh korporat',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-11-a',
                    'cause': 'Belum banyak pelanggan yang mengetahui layanan beyond kWh PLN Batam',
                    'kri': 'Pendapatan beyond kWh',
                    'kri_unit': 'Rp Milyar',
                    'kri_safe': '>= 2',
                    'kri_caution': '<2-1.8',
                    'kri_danger': '<1.8',
                    'risk_type': 'Kuantitatif',
                    'impact_assumption': 'realisasi penerimaan beyon dkWh 2022 - 2025',
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Promosi layanan beyond kWh kepada pelanggan',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [43]},
               12: {'source_no': 12,
                    'indicator': 'Penyerapan Investasi (AI)',
                    'event': 'Pengadaan gagal',
                    'description': 'Program investasi terkontrak melalui proses pengadaan.Proses pengadaan bisa gagal akibat hal teknis dan administrasi',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-12-a',
                    'cause': 'Jumlah peserta lelang tidak sesuai persyaratan',
                    'kri': 'Persentase peserta lelang',
                    'kri_unit': '%',
                    'kri_safe': '>100%',
                    'kri_caution': 1,
                    'kri_danger': '<100%',
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Percepatan pelaksana pengadaan dan pembayaran',
                    'actual_output': None,
                    'planned_cost_source': 144000000.0,
                    'actual_cost': 34465835.6,
                    'absorption_source': 0.23934608055555556,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [44]},
               13: {'source_no': 13,
                    'indicator': 'Pengendalian penggunaan Anggaran Kas Investasi sesuai RKAP 2026 95-100%',
                    'event': 'Tagihan tidak bisa terbayar tepat waktu',
                    'description': 'Pembayaran tagihan akan mempengaruhi penyerapan AKI',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-13-a',
                    'cause': 'adanya pekerjaan tambah kurang pada pekerjaan proyek investasi',
                    'kri': 'Kelengkapan dokumen pembayaran',
                    'kri_unit': '%',
                    'kri_safe': 1,
                    'kri_caution': 0.95,
                    'kri_danger': 0.9,
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Percepatan pelaksana pengadaan dan pembayaran',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [45]},
               14: {'source_no': 14,
                    'indicator': 'Ketepatan Waktu Pengadaaan Investasi sesuai dengan Dokumen  Rencana Pengadaan (DRP) 90%',
                    'event': 'Pengadaan gagal',
                    'description': 'Program investasi terkontrak melalui proses pengadaan.Proses pengadaan bisa gagal akibat hal teknis dan administrasi',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-14-a',
                    'cause': 'Jumlah peserta lelang tidak  sesuai persyaratan',
                    'kri': 'Persentase peserta lelang',
                    'kri_unit': '%',
                    'kri_safe': '>100%',
                    'kri_caution': 1,
                    'kri_danger': '<100%',
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Percepatan pelaksana pengadaan',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [46]},
               15: {'source_no': 15,
                    'indicator': 'Implementasi Peningkatan Penggunaan Produk Dalam Negeri (P3DN) Dalam Proses Pengadaan Barang dan Jasa 25%',
                    'event': 'Spek teknis yang dibutuhkan bernilai TKDN rendah',
                    'description': 'Spek teknis peralatan/jasa sangan mempengaruhi nilai TKDN',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-15-a',
                    'cause': 'Barang/jasa tidak tersedia di dalam negeri',
                    'kri': 'Form Penilaian TKDN',
                    'kri_unit': '%',
                    'kri_safe': 0.5,
                    'kri_caution': '< 25%',
                    'kri_danger': '< 50 - >25',
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Percepatan pelaksana pengadaan berdasarkan persyaratan pemenuhan TKDN',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [47]},
               16: {'source_no': 16,
                    'indicator': 'Human Capital Readiness (HCR) & Organizational Capital Readiness (OCR) dan Produktivitas Pegawai 100%',
                    'event': 'Minimnya Awareness pegawai terhadap program Budaya perusahaan ( COC)',
                    'description': 'Nilai HCR OCR dipengaruhi oleh tingkat kehadiran pegawai dalam program COC',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-16-a',
                    'cause': 'Kurangnya minat pegawai mengikuti coc',
                    'kri': 'Rasio Kehadiran COC',
                    'kri_unit': '%',
                    'kri_safe': 1,
                    'kri_caution': 0.95,
                    'kri_danger': 0.9,
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Monitoring peningkatan awareness pegawai terkait program HCR OCR melalui WA Grup',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [48]},
               17: {'source_no': 17,
                    'indicator': 'Nihil Kecelakaan',
                    'event': 'Terjadinya kecelakan kerja',
                    'description': 'Terjadi kecelakaan pada saat bekerja',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-17-a',
                    'cause': 'Kurangnya awareness terhadap peratran - peraturan yang telah ditetapkan',
                    'kri': 'Zero Accident',
                    'kri_unit': 'kali',
                    'kri_safe': 1,
                    'kri_caution': 1,
                    'kri_danger': 0,
                    'risk_type': 'Kualitatif',
                    'impact_assumption': 'Kejadian kecelakaan kerja 2023',
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Pemenuhan program aspek K3 2025',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [49]},
               18: {'source_no': 18,
                    'indicator': 'Compliance (GCG, Kepatuhan HSSE, Auditor, Reporting, Busdev Alignment, PACA, Critical Events, ICOFR & SPIN)',
                    'event': 'Terjadi pengurangan poin penilaian kineja',
                    'description': 'akibat tidak terpenuhinya kriteria kepatuhan, maka dilakukan pengurangan penilaian',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-18-a',
                    'cause': 'Lambatnya respon dalam pemenuhan data penilaian / assesment',
                    'kri': 'Tidak ada pengurangan nilai',
                    'kri_unit': 'skor',
                    'kri_safe': 0,
                    'kri_caution': -1,
                    'kri_danger': -0.5,
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Meningkatkan koordinasi kepada bidang terkait',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [50]}}},
 6: {'month': 6,
     'month_name': 'Juni',
     'residual_snapshot': 'Q2',
     'items': {1: {'source_no': 1,
                   'indicator': 'Growth Penjualan Tenaga Listrik TUL 309 Batam sebesar 5.015,01 GWh',
                   'event': 'Penjualan Ekstensifikasi tidak sesuai dengan perencanaan',
                   'description': 'Potensi - potensi pasar yang menjadi dasar perencanaan 2026 tidak sesuai perencaan',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-1-a',
                   'cause': 'Potensi - potensi pasar yang menjadi dasar perencanaan 2026 realisasi tidak sesuai',
                   'kri': 'Penambahan Pelanggan TM (Additional Demand)',
                   'kri_unit': 'MVA',
                   'kri_safe': 60,
                   'kri_caution': '> 50 - < 60',
                   'kri_danger': 50,
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Realisasi daya tersambung layanan khusus pelanggan TM 2025',
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Melakukan komunikasi intensif dengan pelanggan yang termasuk dalam potensi pasar serta melakukan probing untuk '
                                       'mengidentifikasi calon pelanggan di luar potensi yang terdata\n'
                                       '---\n'
                                       'Melakukan percepatan penyambungan pelanggan\n'
                                       '---\n'
                                       'Peningkatan rasio elektrisifikasi dengan program listrik desa\n'
                                       '---\n'
                                       'Mengadakan promosi produk layanan misalnya gratis naik daya',
                   'actual_output': None,
                   'planned_cost_source': 96466576981.79527,
                   'actual_cost': 43626667650.0,
                   'absorption_source': 0.4522464569073807,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [10, 11, 12, 13]},
               2: {'source_no': 2,
                   'indicator': 'Percepatan Sambungan Pelanggan (tanpa perluasan jaringan): 1hari untuk 1 phasa, 3 hari untuk 3 phasa TR, dan 5 hari untuk TM',
                   'event': 'Tidak tersedianya material penyambungan',
                   'description': 'Terlambatnya penyambungan pelanggan akibat tidak tersedianya material',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-2-a',
                   'cause': 'Keterlambatan kedatangan material di gudang',
                   'kri': 'Stock minimum material',
                   'kri_unit': '%',
                   'kri_safe': '≥ 100%',
                   'kri_caution': '≥95 - <100%',
                   'kri_danger': '<95',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': '- History TMP Material kosong 2022 - 2025\n- Hasil evaluasi SDS 2025',
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Monitoring kecukupan material (Material Distribusi Utama dan Material Pendukung) berdasarkan stok minimum material',
                   'actual_output': None,
                   'planned_cost_source': None,
                   'actual_cost': 0.0,
                   'absorption_source': None,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [14]},
               3: {'source_no': 3,
                   'indicator': 'Penambahan Pelanggan Layanan Khusus sebesar 147,89 MVA',
                   'event': 'Tidak terpenuhi target jumlah pelanggan produk layanan khusus',
                   'description': 'Kurangnya minat pelanggan atas produk layanan khusus di tahun 2026',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-3-a',
                   'cause': 'Kurangnya strategi marketing untuk produk layanan khusus',
                   'kri': 'HJR LAYANAN KHUSUS',
                   'kri_unit': 'Rupiah/kWh',
                   'kri_safe': '>Rp 1.500',
                   'kri_caution': 'RP 1.400 - Rp 1.500',
                   'kri_danger': '< Rp 1.400',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Realisasi daya tersambung layanan khusus pelanggan TM 2022 - 2025',
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Pasang Baru pelanggan TM, diberikan dengan taif layanan khusus',
                   'actual_output': None,
                   'planned_cost_source': 293694476034.675,
                   'actual_cost': 15031358629.0,
                   'absorption_source': 0.05118025654396484,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [15]},
               4: {'source_no': 4,
                   'indicator': 'System Average Interruption Duration Index  (SAIDI) Distribusi 31,52 Menit/Plg',
                   'event': 'Waktu penanganan gangguan terlalu lama',
                   'description': 'Lamanya waktu penanganan gangguan mengakibatkan tingginya  nilai ENS',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-4-a',
                   'cause': 'pencarian titik gangguan yang lama',
                   'kri': 'Recovery Time',
                   'kri_unit': 'Menit',
                   'kri_safe': '≥ 120',
                   'kri_caution': '≥100 - <120',
                   'kri_danger': '< 100',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Nilai ENS akibat gangguan jaringan distribusi',
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Pemasangan Recloser untuk percepatan pemulihan gangguan\n'
                                       '---\n'
                                       'Upgrade Kubikel LBS menjadi CB di GT Existing (ZDT)\n'
                                       '---\n'
                                       'Pemasangan GD Kios untuk percepatan pemulihan sistem',
                   'actual_output': None,
                   'planned_cost_source': 16427421000.0,
                   'actual_cost': 380938900.0,
                   'absorption_source': 0.02318920906696188,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [16, 17, 18]},
               5: {'source_no': 5,
                   'indicator': 'System Average Interruption Frequency Index  (SAIFI) Distribusi 0,3 Kali/Plg',
                   'event': 'Terjadi gangguan penyulang',
                   'description': 'seringga terjadi gangguan mengakibatkan tingginya  nilai ENS',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-5-a',
                   'cause': 'Kurangnya pengawasan pekerjaan utilitas',
                   'kri': 'Jumlah gangguan penyulang karena pekerjaan utilitas',
                   'kri_unit': 'Kali',
                   'kri_safe': '<10',
                   'kri_caution': '≥ 10-<12',
                   'kri_danger': '≥ 12',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Nilai ENS akibat utilitas',
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Melakukan ground patrol dan pengawasan secara langsung di laapangan dengan terjadwal\n'
                                       '---\n'
                                       'Upgrade Kubikel Air Insulated (Plg TM) / VM6-MG & Siemens RMU\n'
                                       '---\n'
                                       'Upgrade  Arester & FCO/Arester dan Pemasangan grounding pentanahan pada Gardu Portal\n'
                                       '---\n'
                                       'peningkatan kehandalan dengan melkukan Upgrade SUTM Menjadi SKTM\n'
                                       '---\n'
                                       'Peningkatan kehandalan dengan Upgrade Jaringan Distribusi  (rekonduktor tegangan drop, pecah beban jurusan, upgrade '
                                       'JTR dan SR Berderet)\n'
                                       '---\n'
                                       'Melaksanakan kepatuhan terhadap peraturan perundang-undangan yang mengatur operasi Sistem Distribusi.\n'
                                       '---\n'
                                       'Upaya percepatan pengadaan material dan peralatan pemeliharaan\n'
                                       '---\n'
                                       'Melaksanakan pekerjaan pemeliharaan Distribusi',
                   'actual_output': None,
                   'planned_cost_source': 36055097939.4439,
                   'actual_cost': 7140587327.0,
                   'absorption_source': 0.1980465380788294,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [19, 20, 21, 22, 23, 24, 25, 26]},
               6: {'source_no': 6,
                   'indicator': 'Susut Jaringan Distribusi 3,3%',
                   'event': 'Penyalahgunaan penggunaan tenaga listrik',
                   'description': 'Adanya penggunaan tegangan listrik secara illegal',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-6-a',
                   'cause': 'Perilaku pelanggan yang cenderung ingin melakukan penghematan',
                   'kri': 'Pelaksanaan P2TL Gabungan',
                   'kri_unit': 'MWh',
                   'kri_safe': '≥ 13000',
                   'kri_caution': '≥10000 - <13000',
                   'kri_danger': '<10000',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Realisasi P2TL 2022 - 2025',
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'P2TL Gabungan\n'
                                       '---\n'
                                       'Melakukan Upgrade kWh Tua\n'
                                       '---\n'
                                       'Mnjaga kelancaran kualitas komunikasi modem AMR\n'
                                       '---\n'
                                       'menjadikan koreksi rekening sebagai SLA petugas baca meter pda kontrak kerjasama manbill\n'
                                       '---\n'
                                       'Pembuatan Gardu Sisip',
                   'actual_output': None,
                   'planned_cost_source': 17931639178.561966,
                   'actual_cost': 7518129569.0,
                   'absorption_source': 0.41926616379768794,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [27, 28, 29, 30, 31]},
               7: {'source_no': 7,
                   'indicator': 'Pemenuhan Kualitas Penerapan Manajemen Risiko 100%',
                   'event': 'Tidak terpenuhinya parameter kualitas manajemen risiko',
                   'description': 'Tidak Comply terhadap PER-2 KBUMN Tahun 2023',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-7-a',
                   'cause': 'Budaya sadar risiko, kapabilitas dan tata kelola belum terimplementasi secara efektif, efisien dan menyeluruh',
                   'kri': 'Jumlah Program Pemenuhan',
                   'kri_unit': '%',
                   'kri_safe': 1,
                   'kri_caution': 'N/A',
                   'kri_danger': 'N/A',
                   'risk_type': 'Kualitatif',
                   'impact_assumption': None,
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Monitoring  berkala (bulanan)',
                   'actual_output': None,
                   'planned_cost_source': None,
                   'actual_cost': 0.0,
                   'absorption_source': None,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [32]},
               8: {'source_no': '8+9',
                   'indicator': 'Penyelesaian Program Improvement K3L 100%',
                   'event': 'Terjadinya kecelakan kerja',
                   'description': 'Terjadi kecelakaan pada saat bekerja',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-8-a',
                   'cause': 'Kurangnya awareness terhadap peratran - peraturan yang telah ditetapkan',
                   'kri': 'Zero Accident',
                   'kri_unit': 'kali',
                   'kri_safe': 1,
                   'kri_caution': 1,
                   'kri_danger': 0,
                   'risk_type': 'Kualitatif',
                   'impact_assumption': 'Kejadian kecelakaan kerja 2023',
                   'residual_snapshot': 'Q2',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Implementasi Aplikasi Inspekta\n'
                                       '---\n'
                                       'Inspeksi HSSE SM/MU/MUP3\n'
                                       '---\n'
                                       'Inspeksi Perlengkapan K3 (APD, Alat Pemadam)\n'
                                       '---\n'
                                       'Simulasi Tanggap Darurat\n'
                                       '---\n'
                                       'Laporan Kesiapan SISPROK (Sistem Proteksi Kebakaran)\n'
                                       '---\n'
                                       'Penerapan SMK2\n'
                                       '---\n'
                                       'Rapat P2K3 (Panitia Pembina Keselamatan Dan Kesehatan Kerja)\n'
                                       '---\n'
                                       'Sertifikat Laik Operasi\n'
                                       '---\n'
                                       'Implementasi 5R/5S',
                   'actual_output': None,
                   'planned_cost_source': 76500000.0,
                   'actual_cost': 39165000.0,
                   'absorption_source': 0.5119607843137255,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [33, 34, 35, 36, 37, 38, 39, 40, 41],
                   'source_numbers': [8, 9]},
               10: {'source_no': 10,
                    'indicator': 'Maturity Level Sustainability 100%',
                    'event': 'Lambatnya respon dalam pemenuhan data penilaian / assesment',
                    'description': 'Lambatnya respon dalam pemenuhan data penilaian / assesment',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-10-a',
                    'cause': 'ketidak tersediaan data untuk pemenuhan kriteria penilian',
                    'kri': 'Maturity level',
                    'kri_unit': '%',
                    'kri_safe': 1,
                    'kri_caution': '85% - 99%',
                    'kri_danger': '< 85%',
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Pemenuhan dokumen/data dukung penilaian maturity level korporat',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [42]},
               11: {'source_no': 11,
                    'indicator': 'Pendapatan dari luar PLN Group (exclude PTL) sebesar Rp 1 M',
                    'event': 'Pelanggan tidak mengetahui layanan beyond kwh yang tersdia di PLN Batam',
                    'description': 'Tidak tercapainya kinerja beyond kwh korporat',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-11-a',
                    'cause': 'Belum banyak pelanggan yang mengetahui layanan beyond kWh PLN Batam',
                    'kri': 'Pendapatan beyond kWh',
                    'kri_unit': 'Rp Milyar',
                    'kri_safe': '>= 2',
                    'kri_caution': '<2-1.8',
                    'kri_danger': '<1.8',
                    'risk_type': 'Kuantitatif',
                    'impact_assumption': 'realisasi penerimaan beyon dkWh 2022 - 2025',
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Promosi layanan beyond kWh kepada pelanggan',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [43]},
               12: {'source_no': 12,
                    'indicator': 'Penyerapan Investasi (AI)',
                    'event': 'Pengadaan gagal',
                    'description': 'Program investasi terkontrak melalui proses pengadaan.Proses pengadaan bisa gagal akibat hal teknis dan administrasi',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-12-a',
                    'cause': 'Jumlah peserta lelang tidak sesuai persyaratan',
                    'kri': 'Persentase peserta lelang',
                    'kri_unit': '%',
                    'kri_safe': '>100%',
                    'kri_caution': 1,
                    'kri_danger': '<100%',
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Percepatan pelaksana pengadaan dan pembayaran',
                    'actual_output': None,
                    'planned_cost_source': 144000000.0,
                    'actual_cost': 43866916.2,
                    'absorption_source': 0.3046313625,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [44]},
               13: {'source_no': 13,
                    'indicator': 'Pengendalian penggunaan Anggaran Kas Investasi sesuai RKAP 2026 95-100%',
                    'event': 'Tagihan tidak bisa terbayar tepat waktu',
                    'description': 'Pembayaran tagihan akan mempengaruhi penyerapan AKI',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-13-a',
                    'cause': 'adanya pekerjaan tambah kurang pada pekerjaan proyek investasi',
                    'kri': 'Kelengkapan dokumen pembayaran',
                    'kri_unit': '%',
                    'kri_safe': 1,
                    'kri_caution': 0.95,
                    'kri_danger': 0.9,
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Percepatan pelaksana pengadaan dan pembayaran',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [45]},
               14: {'source_no': 14,
                    'indicator': 'Ketepatan Waktu Pengadaaan Investasi sesuai dengan Dokumen  Rencana Pengadaan (DRP) 90%',
                    'event': 'Pengadaan gagal',
                    'description': 'Program investasi terkontrak melalui proses pengadaan.Proses pengadaan bisa gagal akibat hal teknis dan administrasi',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-14-a',
                    'cause': 'Jumlah peserta lelang tidak  sesuai persyaratan',
                    'kri': 'Persentase peserta lelang',
                    'kri_unit': '%',
                    'kri_safe': '>100%',
                    'kri_caution': 1,
                    'kri_danger': '<100%',
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Percepatan pelaksana pengadaan',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [46]},
               15: {'source_no': 15,
                    'indicator': 'Implementasi Peningkatan Penggunaan Produk Dalam Negeri (P3DN) Dalam Proses Pengadaan Barang dan Jasa 25%',
                    'event': 'Spek teknis yang dibutuhkan bernilai TKDN rendah',
                    'description': 'Spek teknis peralatan/jasa sangan mempengaruhi nilai TKDN',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-15-a',
                    'cause': 'Barang/jasa tidak tersedia di dalam negeri',
                    'kri': 'Form Penilaian TKDN',
                    'kri_unit': '%',
                    'kri_safe': 0.5,
                    'kri_caution': '< 25%',
                    'kri_danger': '< 50 - >25',
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Percepatan pelaksana pengadaan berdasarkan persyaratan pemenuhan TKDN',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [47]},
               16: {'source_no': 16,
                    'indicator': 'Human Capital Readiness (HCR) & Organizational Capital Readiness (OCR) dan Produktivitas Pegawai 100%',
                    'event': 'Minimnya Awareness pegawai terhadap program Budaya perusahaan ( COC)',
                    'description': 'Nilai HCR OCR dipengaruhi oleh tingkat kehadiran pegawai dalam program COC',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-16-a',
                    'cause': 'Kurangnya minat pegawai mengikuti coc',
                    'kri': 'Rasio Kehadiran COC',
                    'kri_unit': '%',
                    'kri_safe': 1,
                    'kri_caution': 0.95,
                    'kri_danger': 0.9,
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Monitoring peningkatan awareness pegawai terkait program HCR OCR melalui WA Grup',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [48]},
               17: {'source_no': 17,
                    'indicator': 'Nihil Kecelakaan',
                    'event': 'Terjadinya kecelakan kerja',
                    'description': 'Terjadi kecelakaan pada saat bekerja',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-17-a',
                    'cause': 'Kurangnya awareness terhadap peratran - peraturan yang telah ditetapkan',
                    'kri': 'Zero Accident',
                    'kri_unit': 'kali',
                    'kri_safe': 1,
                    'kri_caution': 1,
                    'kri_danger': 0,
                    'risk_type': 'Kualitatif',
                    'impact_assumption': 'Kejadian kecelakaan kerja 2023',
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Pemenuhan program aspek K3 2025',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [49]},
               18: {'source_no': 18,
                    'indicator': 'Compliance (GCG, Kepatuhan HSSE, Auditor, Reporting, Busdev Alignment, PACA, Critical Events, ICOFR & SPIN)',
                    'event': 'Terjadi pengurangan poin penilaian kineja',
                    'description': 'akibat tidak terpenuhinya kriteria kepatuhan, maka dilakukan pengurangan penilaian',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-18-a',
                    'cause': 'Lambatnya respon dalam pemenuhan data penilaian / assesment',
                    'kri': 'Tidak ada pengurangan nilai',
                    'kri_unit': 'skor',
                    'kri_safe': 0,
                    'kri_caution': -1,
                    'kri_danger': -0.5,
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q2',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Meningkatkan koordinasi kepada bidang terkait',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [50]}}},
 7: {'month': 7,
     'month_name': 'Juli',
     'residual_snapshot': 'Q3',
     'items': {1: {'source_no': 1,
                   'indicator': 'Growth Penjualan Tenaga Listrik TUL 309 Batam sebesar 5.015,01 GWh',
                   'event': 'Penjualan Ekstensifikasi tidak sesuai dengan perencanaan',
                   'description': 'Potensi - potensi pasar yang menjadi dasar perencanaan 2026 tidak sesuai perencaan',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-1-a',
                   'cause': 'Potensi - potensi pasar yang menjadi dasar perencanaan 2026 realisasi tidak sesuai',
                   'kri': 'Penambahan Pelanggan TM (Additional Demand)',
                   'kri_unit': 'MVA',
                   'kri_safe': 60,
                   'kri_caution': '> 50 - < 60',
                   'kri_danger': 50,
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Realisasi daya tersambung layanan khusus pelanggan TM 2025',
                   'residual_snapshot': 'Q3',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Melakukan komunikasi intensif dengan pelanggan yang termasuk dalam potensi pasar serta melakukan probing untuk '
                                       'mengidentifikasi calon pelanggan di luar potensi yang terdata\n'
                                       '---\n'
                                       'Melakukan percepatan penyambungan pelanggan\n'
                                       '---\n'
                                       'Peningkatan rasio elektrisifikasi dengan program listrik desa\n'
                                       '---\n'
                                       'Mengadakan promosi produk layanan misalnya gratis naik daya',
                   'actual_output': None,
                   'planned_cost_source': 96466576981.79527,
                   'actual_cost': 65023387428.0,
                   'absorption_source': 0.6740509455442885,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [10, 11, 12, 13]},
               2: {'source_no': 2,
                   'indicator': 'Percepatan Sambungan Pelanggan (tanpa perluasan jaringan): 1hari untuk 1 phasa, 3 hari untuk 3 phasa TR, dan 5 hari untuk TM',
                   'event': 'Tidak tersedianya material penyambungan',
                   'description': 'Terlambatnya penyambungan pelanggan akibat tidak tersedianya material',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-2-a',
                   'cause': 'Keterlambatan kedatangan material di gudang',
                   'kri': 'Stock minimum material',
                   'kri_unit': '%',
                   'kri_safe': '≥ 100%',
                   'kri_caution': '≥95 - <100%',
                   'kri_danger': '<95',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': '- History TMP Material kosong 2022 - 2025\n- Hasil evaluasi SDS 2025',
                   'residual_snapshot': 'Q3',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Monitoring kecukupan material (Material Distribusi Utama dan Material Pendukung) berdasarkan stok minimum material',
                   'actual_output': None,
                   'planned_cost_source': None,
                   'actual_cost': 0.0,
                   'absorption_source': None,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [14]},
               3: {'source_no': 3,
                   'indicator': 'Penambahan Pelanggan Layanan Khusus sebesar 147,89 MVA',
                   'event': 'Tidak terpenuhi target jumlah pelanggan produk layanan khusus',
                   'description': 'Kurangnya minat pelanggan atas produk layanan khusus di tahun 2026',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-3-a',
                   'cause': 'Kurangnya strategi marketing untuk produk layanan khusus',
                   'kri': 'HJR LAYANAN KHUSUS',
                   'kri_unit': 'Rupiah/kWh',
                   'kri_safe': '>Rp 1.500',
                   'kri_caution': 'RP 1.400 - Rp 1.500',
                   'kri_danger': '< Rp 1.400',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Realisasi daya tersambung layanan khusus pelanggan TM 2022 - 2025',
                   'residual_snapshot': 'Q3',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Pasang Baru pelanggan TM, diberikan dengan taif layanan khusus',
                   'actual_output': None,
                   'planned_cost_source': 533989956427.0,
                   'actual_cost': 521641884452.0,
                   'absorption_source': 0.9768758347860648,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [15]},
               4: {'source_no': 4,
                   'indicator': 'System Average Interruption Duration Index  (SAIDI) Distribusi 31,52 Menit/Plg',
                   'event': 'Waktu penanganan gangguan terlalu lama',
                   'description': 'Lamanya waktu penanganan gangguan mengakibatkan tingginya  nilai ENS',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-4-a',
                   'cause': 'pencarian titik gangguan yang lama',
                   'kri': 'Recovery Time',
                   'kri_unit': 'Menit',
                   'kri_safe': '≥ 120',
                   'kri_caution': '≥100 - <120',
                   'kri_danger': '< 100',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Nilai ENS akibat gangguan jaringan distribusi',
                   'residual_snapshot': 'Q3',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Pemasangan Recloser untuk percepatan pemulihan gangguan\n'
                                       '---\n'
                                       'Upgrade Kubikel LBS menjadi CB di GT Existing (ZDT)\n'
                                       '---\n'
                                       'Pemasangan GD Kios untuk percepatan pemulihan sistem',
                   'actual_output': None,
                   'planned_cost_source': 16427421000.0,
                   'actual_cost': 14882561218.0,
                   'absorption_source': 0.9059584713875659,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [16, 17, 18]},
               5: {'source_no': 5,
                   'indicator': 'System Average Interruption Frequency Index  (SAIFI) Distribusi 0,3 Kali/Plg',
                   'event': 'Terjadi gangguan penyulang',
                   'description': 'seringga terjadi gangguan mengakibatkan tingginya  nilai ENS',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-5-a',
                   'cause': 'Kurangnya pengawasan pekerjaan utilitas',
                   'kri': 'Jumlah gangguan penyulang karena pekerjaan utilitas',
                   'kri_unit': 'Kali',
                   'kri_safe': '<10',
                   'kri_caution': '≥ 10-<12',
                   'kri_danger': '≥ 12',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Nilai ENS akibat utilitas',
                   'residual_snapshot': 'Q3',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Melakukan ground patrol dan pengawasan secara langsung di laapangan dengan terjadwal\n'
                                       '---\n'
                                       'Upgrade Kubikel Air Insulated (Plg TM) / VM6-MG & Siemens RMU\n'
                                       '---\n'
                                       'Upgrade  Arester & FCO/Arester dan Pemasangan grounding pentanahan pada Gardu Portal\n'
                                       '---\n'
                                       'peningkatan kehandalan dengan melkukan Upgrade SUTM Menjadi SKTM\n'
                                       '---\n'
                                       'Peningkatan kehandalan dengan Upgrade Jaringan Distribusi  (rekonduktor tegangan drop, pecah beban jurusan, upgrade '
                                       'JTR dan SR Berderet)\n'
                                       '---\n'
                                       'Melaksanakan kepatuhan terhadap peraturan perundang-undangan yang mengatur operasi Sistem Distribusi.\n'
                                       '---\n'
                                       'Upaya percepatan pengadaan material dan peralatan pemeliharaan\n'
                                       '---\n'
                                       'Melaksanakan pekerjaan pemeliharaan Distribusi',
                   'actual_output': None,
                   'planned_cost_source': 36055097939.4439,
                   'actual_cost': 31391808533.0,
                   'absorption_source': 0.8706621345398619,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [19, 20, 21, 22, 23, 24, 25, 26]},
               6: {'source_no': 6,
                   'indicator': 'Susut Jaringan Distribusi 3,3%',
                   'event': 'Penyalahgunaan penggunaan tenaga listrik',
                   'description': 'Adanya penggunaan tegangan listrik secara illegal',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-6-a',
                   'cause': 'Perilaku pelanggan yang cenderung ingin melakukan penghematan',
                   'kri': 'Pelaksanaan P2TL Gabungan',
                   'kri_unit': 'MWh',
                   'kri_safe': '≥ 13000',
                   'kri_caution': '≥10000 - <13000',
                   'kri_danger': '<10000',
                   'risk_type': 'Kuantitatif',
                   'impact_assumption': 'Realisasi P2TL 2022 - 2025',
                   'residual_snapshot': 'Q3',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'P2TL Gabungan\n'
                                       '---\n'
                                       'Melakukan Upgrade kWh Tua\n'
                                       '---\n'
                                       'Mnjaga kelancaran kualitas komunikasi modem AMR\n'
                                       '---\n'
                                       'menjadikan koreksi rekening sebagai SLA petugas baca meter pda kontrak kerjasama manbill\n'
                                       '---\n'
                                       'Pembuatan Gardu Sisip',
                   'actual_output': None,
                   'planned_cost_source': 17931639178.561966,
                   'actual_cost': 16670122637.0,
                   'absorption_source': 0.9296485653653926,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [27, 28, 29, 30, 31]},
               7: {'source_no': 7,
                   'indicator': 'Pemenuhan Kualitas Penerapan Manajemen Risiko 100%',
                   'event': 'Tidak terpenuhinya parameter kualitas manajemen risiko',
                   'description': 'Tidak Comply terhadap PER-2 KBUMN Tahun 2023',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-7-a',
                   'cause': 'Budaya sadar risiko, kapabilitas dan tata kelola belum terimplementasi secara efektif, efisien dan menyeluruh',
                   'kri': 'Jumlah Program Pemenuhan',
                   'kri_unit': '%',
                   'kri_safe': 1,
                   'kri_caution': 'N/A',
                   'kri_danger': 'N/A',
                   'risk_type': 'Kualitatif',
                   'impact_assumption': None,
                   'residual_snapshot': 'Q3',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Monitoring  berkala (bulanan)',
                   'actual_output': None,
                   'planned_cost_source': None,
                   'actual_cost': 0.0,
                   'absorption_source': None,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [32]},
               8: {'source_no': '8+9',
                   'indicator': 'Penyelesaian Program Improvement K3L 100%',
                   'event': 'Terjadinya kecelakan kerja',
                   'description': 'Terjadi kecelakaan pada saat bekerja',
                   'cause_no': 'a',
                   'cause_code': 'UB DISYAN-8-a',
                   'cause': 'Kurangnya awareness terhadap peratran - peraturan yang telah ditetapkan',
                   'kri': 'Zero Accident',
                   'kri_unit': 'kali',
                   'kri_safe': 1,
                   'kri_caution': 1,
                   'kri_danger': 0,
                   'risk_type': 'Kualitatif',
                   'impact_assumption': 'Kejadian kecelakaan kerja 2023',
                   'residual_snapshot': 'Q3',
                   'residual_impact': None,
                   'residual_impact_scale': None,
                   'residual_probability': None,
                   'residual_probability_scale': None,
                   'residual_exposure': None,
                   'residual_score': None,
                   'residual_level': None,
                   'effectiveness': 'Sebagian efektif',
                   'actual_treatment': 'Implementasi Aplikasi Inspekta\n'
                                       '---\n'
                                       'Inspeksi HSSE SM/MU/MUP3\n'
                                       '---\n'
                                       'Inspeksi Perlengkapan K3 (APD, Alat Pemadam)\n'
                                       '---\n'
                                       'Simulasi Tanggap Darurat\n'
                                       '---\n'
                                       'Laporan Kesiapan SISPROK (Sistem Proteksi Kebakaran)\n'
                                       '---\n'
                                       'Penerapan SMK2\n'
                                       '---\n'
                                       'Rapat P2K3 (Panitia Pembina Keselamatan Dan Kesehatan Kerja)\n'
                                       '---\n'
                                       'Sertifikat Laik Operasi\n'
                                       '---\n'
                                       'Implementasi 5R/5S',
                   'actual_output': None,
                   'planned_cost_source': 76500000.0,
                   'actual_cost': 39165000.0,
                   'absorption_source': 0.5119607843137255,
                   'pic': 'SM UBDISYAN',
                   'status': None,
                   'status_explanation': None,
                   'progress_source': None,
                   'kri_actual_threshold': None,
                   'kri_actual_value': None,
                   'source_rows_iiib': [33, 34, 35, 36, 37, 38, 39, 40, 41],
                   'source_numbers': [8, 9]},
               10: {'source_no': 10,
                    'indicator': 'Maturity Level Sustainability 100%',
                    'event': 'Lambatnya respon dalam pemenuhan data penilaian / assesment',
                    'description': 'Lambatnya respon dalam pemenuhan data penilaian / assesment',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-10-a',
                    'cause': 'ketidak tersediaan data untuk pemenuhan kriteria penilian',
                    'kri': 'Maturity level',
                    'kri_unit': '%',
                    'kri_safe': 1,
                    'kri_caution': '85% - 99%',
                    'kri_danger': '< 85%',
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q3',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Pemenuhan dokumen/data dukung penilaian maturity level korporat',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [42]},
               11: {'source_no': 11,
                    'indicator': 'Pendapatan dari luar PLN Group (exclude PTL) sebesar Rp 1 M',
                    'event': 'Pelanggan tidak mengetahui layanan beyond kwh yang tersdia di PLN Batam',
                    'description': 'Tidak tercapainya kinerja beyond kwh korporat',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-11-a',
                    'cause': 'Belum banyak pelanggan yang mengetahui layanan beyond kWh PLN Batam',
                    'kri': 'Pendapatan beyond kWh',
                    'kri_unit': 'Rp Milyar',
                    'kri_safe': '>= 2',
                    'kri_caution': '<2-1.8',
                    'kri_danger': '<1.8',
                    'risk_type': 'Kuantitatif',
                    'impact_assumption': 'realisasi penerimaan beyon dkWh 2022 - 2025',
                    'residual_snapshot': 'Q3',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Promosi layanan beyond kWh kepada pelanggan',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [43]},
               12: {'source_no': 12,
                    'indicator': 'Penyerapan Investasi (AI)',
                    'event': 'Pengadaan gagal',
                    'description': 'Program investasi terkontrak melalui proses pengadaan.Proses pengadaan bisa gagal akibat hal teknis dan administrasi',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-12-a',
                    'cause': 'Jumlah peserta lelang tidak sesuai persyaratan',
                    'kri': 'Persentase peserta lelang',
                    'kri_unit': '%',
                    'kri_safe': '>100%',
                    'kri_caution': 1,
                    'kri_danger': '<100%',
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q3',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Percepatan pelaksana pengadaan dan pembayaran',
                    'actual_output': None,
                    'planned_cost_source': 144000000.0,
                    'actual_cost': 82547589.0,
                    'absorption_source': 0.5732471458333334,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [44]},
               13: {'source_no': 13,
                    'indicator': 'Pengendalian penggunaan Anggaran Kas Investasi sesuai RKAP 2026 95-100%',
                    'event': 'Tagihan tidak bisa terbayar tepat waktu',
                    'description': 'Pembayaran tagihan akan mempengaruhi penyerapan AKI',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-13-a',
                    'cause': 'adanya pekerjaan tambah kurang pada pekerjaan proyek investasi',
                    'kri': 'Kelengkapan dokumen pembayaran',
                    'kri_unit': '%',
                    'kri_safe': 1,
                    'kri_caution': 0.95,
                    'kri_danger': 0.9,
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q3',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Percepatan pelaksana pengadaan dan pembayaran',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [45]},
               14: {'source_no': 14,
                    'indicator': 'Ketepatan Waktu Pengadaaan Investasi sesuai dengan Dokumen  Rencana Pengadaan (DRP) 90%',
                    'event': 'Pengadaan gagal',
                    'description': 'Program investasi terkontrak melalui proses pengadaan.Proses pengadaan bisa gagal akibat hal teknis dan administrasi',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-14-a',
                    'cause': 'Jumlah peserta lelang tidak  sesuai persyaratan',
                    'kri': 'Persentase peserta lelang',
                    'kri_unit': '%',
                    'kri_safe': '>100%',
                    'kri_caution': 1,
                    'kri_danger': '<100%',
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q3',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Percepatan pelaksana pengadaan',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [46]},
               15: {'source_no': 15,
                    'indicator': 'Implementasi Peningkatan Penggunaan Produk Dalam Negeri (P3DN) Dalam Proses Pengadaan Barang dan Jasa 25%',
                    'event': 'Spek teknis yang dibutuhkan bernilai TKDN rendah',
                    'description': 'Spek teknis peralatan/jasa sangan mempengaruhi nilai TKDN',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-15-a',
                    'cause': 'Barang/jasa tidak tersedia di dalam negeri',
                    'kri': 'Form Penilaian TKDN',
                    'kri_unit': '%',
                    'kri_safe': 0.5,
                    'kri_caution': '< 25%',
                    'kri_danger': '< 50 - >25',
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q3',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Percepatan pelaksana pengadaan berdasarkan persyaratan pemenuhan TKDN',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [47]},
               16: {'source_no': 16,
                    'indicator': 'Human Capital Readiness (HCR) & Organizational Capital Readiness (OCR) dan Produktivitas Pegawai 100%',
                    'event': 'Minimnya Awareness pegawai terhadap program Budaya perusahaan ( COC)',
                    'description': 'Nilai HCR OCR dipengaruhi oleh tingkat kehadiran pegawai dalam program COC',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-16-a',
                    'cause': 'Kurangnya minat pegawai mengikuti coc',
                    'kri': 'Rasio Kehadiran COC',
                    'kri_unit': '%',
                    'kri_safe': 1,
                    'kri_caution': 0.95,
                    'kri_danger': 0.9,
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q3',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Monitoring peningkatan awareness pegawai terkait program HCR OCR melalui WA Grup',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [48]},
               17: {'source_no': 17,
                    'indicator': 'Nihil Kecelakaan',
                    'event': 'Terjadinya kecelakan kerja',
                    'description': 'Terjadi kecelakaan pada saat bekerja',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-17-a',
                    'cause': 'Kurangnya awareness terhadap peratran - peraturan yang telah ditetapkan',
                    'kri': 'Zero Accident',
                    'kri_unit': 'kali',
                    'kri_safe': 1,
                    'kri_caution': 1,
                    'kri_danger': 0,
                    'risk_type': 'Kualitatif',
                    'impact_assumption': 'Kejadian kecelakaan kerja 2023',
                    'residual_snapshot': 'Q3',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Pemenuhan program aspek K3 2025',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [49]},
               18: {'source_no': 18,
                    'indicator': 'Compliance (GCG, Kepatuhan HSSE, Auditor, Reporting, Busdev Alignment, PACA, Critical Events, ICOFR & SPIN)',
                    'event': 'Terjadi pengurangan poin penilaian kineja',
                    'description': 'akibat tidak terpenuhinya kriteria kepatuhan, maka dilakukan pengurangan penilaian',
                    'cause_no': 'a',
                    'cause_code': 'UB DISYAN-18-a',
                    'cause': 'Lambatnya respon dalam pemenuhan data penilaian / assesment',
                    'kri': 'Tidak ada pengurangan nilai',
                    'kri_unit': 'skor',
                    'kri_safe': 0,
                    'kri_caution': -1,
                    'kri_danger': -0.5,
                    'risk_type': 'Kualitatif',
                    'impact_assumption': None,
                    'residual_snapshot': 'Q3',
                    'residual_impact': None,
                    'residual_impact_scale': None,
                    'residual_probability': None,
                    'residual_probability_scale': None,
                    'residual_exposure': None,
                    'residual_score': None,
                    'residual_level': None,
                    'effectiveness': 'Sebagian efektif',
                    'actual_treatment': 'Meningkatkan koordinasi kepada bidang terkait',
                    'actual_output': None,
                    'planned_cost_source': None,
                    'actual_cost': 0.0,
                    'absorption_source': None,
                    'pic': 'SM UBDISYAN',
                    'status': None,
                    'status_explanation': None,
                    'progress_source': None,
                    'kri_actual_threshold': None,
                    'kri_actual_value': None,
                    'source_rows_iiib': [50]}}}}


# SOURCE_ACTUAL_TIMELINE_KV_V1
# Exact values from III.B K:V, consolidated with OR across treatment rows.
SOURCE_ACTUAL_TIMELINE = {5: {1: [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 2: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 3: [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 4: [0, 0, 0, 0, 1, 1, 0, 1, 0, 1, 1, 0], 5: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 6: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 7: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 8: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 10: [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1], 11: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 12: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 13: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 14: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 15: [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1], 16: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 17: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 18: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]}, 6: {1: [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 2: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 3: [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 4: [0, 0, 0, 0, 1, 1, 0, 1, 0, 1, 1, 0], 5: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 6: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 7: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 8: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 10: [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1], 11: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 12: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 13: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 14: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 15: [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1], 16: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 17: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 18: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]}, 7: {1: [0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1], 2: [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 3: [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 4: [0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 1], 5: [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 6: [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], 7: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 8: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], 10: [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], 11: [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], 12: [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1], 13: [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1], 14: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1], 15: [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1], 16: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1], 17: [0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1], 18: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]}}

def norm(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("&", " dan ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def D(value):
    if value in (None, "", "-"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def pct(value):
    d = D(value)
    if d is None:
        return None
    if abs(d) <= 1:
        d *= Decimal("100")
    return d


def int_or_none(value):
    d = D(value)
    return int(d) if d is not None else None


def risk_type(value):
    n = norm(value)
    if "kualitatif" in n:
        return "qualitative"
    if "kuantitatif" in n:
        return "quantitative"
    return None


def treatment_status(value):
    n = norm(value)
    if not n:
        return None
    if "continue" in n or "lanjut" in n:
        return "continue"
    if "discontinue" in n or "selesai" in n:
        return "discontinue"
    if "delayed" in n or "terlambat" in n:
        return "delayed"
    return None


def scale(model, value):
    n = int_or_none(value)
    if n is None:
        return None
    return model.objects.filter(nilai=n).first()


def get_profile():
    qs = ReAssessmentSummary.objects.filter(tahun=YEAR).select_related("unit_bisnis", "kontrak_manajemen")
    exact = qs.filter(judul__iexact=PROFILE_TITLE).first()
    if exact:
        profile = exact
    else:
        candidates = [x for x in qs if "ubdisyan" in norm(x.judul).replace(" ", "")]
        if len(candidates) != 1:
            raise RuntimeError(f"Profil UBDISYAN tidak unik: {[(x.id, x.judul) for x in candidates]}")
        profile = candidates[0]
    unit_name = getattr(profile.unit_bisnis, "name", "") or getattr(profile.unit_bisnis, "nama", "")
    if "disyan" not in norm(unit_name):
        raise RuntimeError(f"Profil ditemukan tetapi unit tidak cocok: id={profile.id}, unit={unit_name!r}")
    return profile


def latest_existing_report(profile):
    return (
        MonthlyRiskReport.objects.filter(reassessment=profile, periode__tahun_buku__tahun=YEAR)
        .select_related("periode")
        .order_by("-periode__tanggal_mulai", "-id")
        .first()
    )


def exact_candidates(profile, src):
    en = norm(src["event"]); kn = norm(src["kri"])
    out=[]
    for r in ReAssessmentItem.objects.filter(summary=profile).select_related("km_item"):
        ev=norm(r.peristiwa_risiko); kri=norm(r.key_risk_indicators)
        event_ok = ev == en
        kri_ok = kri == kn
        # canonical alias for RMI/KPMR source wording
        if src.get("source_no") == 7:
            event_ok = event_ok or ("parameter" in ev and "penilaian rmi" in ev)
            kri_ok = kri_ok or ("jumlah program pemenuhan" in kri)
        if event_ok and kri_ok:
            out.append(r)
    return out


def indicator_similarity(src, risk_event):
    src_i=norm(src.get("indicator"))
    km_i=norm(getattr(risk_event.km_item, "indikator_kinerja_kunci", "") if risk_event.km_item_id else "")
    if not src_i or not km_i:
        return 0.0
    if src_i == km_i:
        return 1.0
    if src_i in km_i or km_i in src_i:
        return 0.9
    return SequenceMatcher(None, src_i, km_i).ratio()


def resolve_mapping(profile):
    prior = latest_existing_report(profile)
    prior_ids = set(prior.items.values_list("risk_event_id", flat=True)) if prior else set()
    resolved={}
    used=set()
    diagnostics=[]
    for source_no, src in SOURCE[5]["items"].items():
        candidates=exact_candidates(profile, src)
        # Source 17 Nihil Kecelakaan must use the dedicated KM-linked item when available.
        if source_no == 17:
            dedicated=[r for r in candidates if "nihil kecelakaan" in norm(getattr(r.km_item,"indikator_kinerja_kunci", ""))]
            if dedicated:
                candidates=dedicated
        # Source 8+9 is K3L improvement, not the separate Nihil Kecelakaan KPI.
        if source_no == 8:
            non_nihil=[r for r in candidates if "nihil kecelakaan" not in norm(getattr(r.km_item,"indikator_kinerja_kunci", ""))]
            if non_nihil:
                candidates=non_nihil
        # Distinguish the two 'Pengadaan gagal' rows by source KPI/KM wording.
        if source_no == 14:
            preferred=[r for r in candidates if "ketepatan waktu pengadaan" in norm(getattr(r.km_item,"indikator_kinerja_kunci", ""))]
            if preferred:
                candidates=preferred
        if source_no == 12:
            non_ketepatan=[r for r in candidates if "ketepatan waktu pengadaan" not in norm(getattr(r.km_item,"indikator_kinerja_kunci", ""))]
            if non_ketepatan:
                candidates=non_ketepatan

        available=[r for r in candidates if r.id not in used]
        if len(available) > 1:
            from_prior=[r for r in available if r.id in prior_ids]
            if len(from_prior) == 1:
                available=from_prior
            else:
                available=sorted(available, key=lambda r:(-indicator_similarity(src,r), r.no_item or 9999, r.id))
                if len(available)>1 and indicator_similarity(src,available[0]) <= indicator_similarity(src,available[1]) + 0.05:
                    # still ambiguous: do not guess
                    pass
                elif available:
                    available=[available[0]]
        if len(available)==1:
            chosen=available[0]
            resolved[source_no]=chosen
            used.add(chosen.id)
            diagnostics.append((source_no, "FOUND", chosen, candidates))
        else:
            diagnostics.append((source_no, "AMBIGUOUS" if available else "MISSING", None, candidates))
    return resolved, diagnostics, prior


def get_prepared_by(profile):
    prior = latest_existing_report(profile)
    if prior and prior.prepared_by_id:
        return prior.prepared_by
    User=get_user_model()
    return User.objects.filter(is_active=True, is_staff=True).order_by("id").first() or User.objects.filter(is_active=True).order_by("id").first()


def get_period(tahun_buku, month):
    code=f"{YEAR}-{month:02d}"
    period=PeriodeLaporan.objects.filter(tahun_buku=tahun_buku, kode_periode=code).first()
    if period:
        return period
    start=datetime(YEAR,month,1).date(); end=datetime(YEAR,month,calendar.monthrange(YEAR,month)[1]).date()
    return PeriodeLaporan.objects.create(
        tahun_buku=tahun_buku,
        kode_periode=code,
        nama_periode=f"{SOURCE[month]['month_name']} {YEAR}",
        jenis_periode="bulanan",
        tanggal_mulai=start,
        tanggal_selesai=end,
        is_locked=False,
    )


def backup_sqlite():
    cfg=settings.DATABASES["default"]
    if cfg.get("ENGINE") != "django.db.backends.sqlite3":
        print("BACKUP: skip, database bukan SQLite")
        return None
    src=Path(cfg["NAME"])
    backup_dir=src.parent / "backup"
    if not backup_dir.exists():
        backup_dir=Path("/home/adminsvr/backup") if Path("/home/adminsvr").exists() else src.parent
    backup_dir.mkdir(parents=True, exist_ok=True)
    dst=backup_dir / f"db_before_smdisyan_may_jul_{datetime.now():%Y%m%d_%H%M%S}.sqlite3"
    shutil.copy2(src,dst)
    print(f"BACKUP OK: {dst}")
    return dst


def apply_item(report, risk_event, src):
    obj,created=MonthlyRiskReportItem.objects.get_or_create(report=report,risk_event=risk_event)
    obj.km_item=risk_event.km_item
    obj.jenis_risiko=risk_type(src.get("risk_type"))
    obj.realisasi_asumsi_dampak=src.get("impact_assumption")
    # Exact quarter snapshot only. No fallback to Q1.
    if obj.jenis_risiko == "qualitative":
        obj.realisasi_nilai_dampak=None
    else:
        obj.realisasi_nilai_dampak=D(src.get("residual_impact"))
    obj.realisasi_skala_dampak=scale(MasterSkalaDampak,src.get("residual_impact_scale"))
    obj.realisasi_nilai_probabilitas=pct(src.get("residual_probability"))
    obj.realisasi_skala_probabilitas=scale(MasterSkalaProbabilitas,src.get("residual_probability_scale"))
    obj.realisasi_eksposur=D(src.get("residual_exposure"))
    obj.realisasi_skor_risiko=int_or_none(src.get("residual_score"))
    obj.realisasi_level_risiko=src.get("residual_level")
    obj.efektivitas_perlakuan_risiko=src.get("effectiveness")

    obj.realisasi_rencana_perlakuan=src.get("actual_treatment")
    obj.realisasi_output_perlakuan=src.get("actual_output")
    # IMPORT_MONTHLY_PLANNED_COST_V2
    obj.rencana_biaya_perlakuan=D(src.get("planned_cost_source"))
    obj.realisasi_biaya_perlakuan=D(src.get("actual_cost"))
    obj.persentase_serapan_biaya=pct(src.get("absorption_source"))
    obj.realisasi_pic=(str(src.get("pic"))[:255] if src.get("pic") else None)
    obj.status_rencana_perlakuan=treatment_status(src.get("status"))
    obj.penjelasan_status_rencana=src.get("status_explanation")
    obj.progress_pelaksanaan_percent=pct(src.get("progress_source"))
    obj.realisasi_threshold_kri=(str(src.get("kri_actual_threshold"))[:255] if src.get("kri_actual_threshold") else None)
    obj.realisasi_threshold_kri_skor=(str(src.get("kri_actual_value"))[:100] if src.get("kri_actual_value") else None)
    # Source current-month KRI value cells are blank. Never infer numeric KRI.
    obj.realisasi_nilai_kri=None

    # APPLY_ACTUAL_TIMELINE_KV_V1
    month = report.periode.tanggal_mulai.month
    flags = SOURCE_ACTUAL_TIMELINE.get(month, {}).get(src.get("source_no"), [0] * 12)
    for timeline_month, flag in enumerate(flags, start=1):
        setattr(obj, f"realisasi_timeline_{timeline_month}", 1 if flag else 0)

    obj.save()
    return obj,created


def audit():
    profile=get_profile()
    mapping,diags,prior=resolve_mapping(profile)
    print("SOURCE AUDIT")
    for month in (5,6,7):
        block=SOURCE[month]
        residual_nonempty=sum(1 for x in block["items"].values() if x.get("residual_score") not in (None,"","-"))
        mitigation_cost=sum(Decimal(str(x.get("actual_cost") or 0)) for x in block["items"].values())
        print(f"  {block['month_name']}: source_no=18; canonical=17 (8+9 merged); residual={block['residual_snapshot']}; residual nonempty={residual_nonempty}; actual cost total={mitigation_cost}")
    print("  III.D/III.E: sheet source tidak tersedia -> TIDAK DIUBAH")
    print("  Source hashes:")
    for month,h in SOURCE_HASHES.items(): print(f"    {SOURCE[month]['month_name']}: {h}")

    print("BASELINE")
    unit_name=getattr(profile.unit_bisnis,"name","") or getattr(profile.unit_bisnis,"nama","")
    print(f"  profile: id={profile.id}, judul={profile.judul!r}, status={profile.status}, unit={unit_name!r}, KM={profile.kontrak_manajemen_id}, master items={profile.items.count() if hasattr(profile,'items') else ReAssessmentItem.objects.filter(summary=profile).count()}")
    if prior:
        print(f"  representative prior report: id={prior.id}, kode={prior.kode}, status={prior.status}, items={prior.items.count()}")
    else:
        print("  representative prior report: NONE")
    unresolved=[]
    for source_no,status,chosen,candidates in diags:
        src=SOURCE[5]["items"][source_no]
        label="8+9" if source_no==8 else str(source_no)
        if chosen:
            km_label=getattr(chosen.km_item,"indikator_kinerja_kunci",None) if chosen.km_item_id else None
            print(f"    source {label}: FOUND risk_event={chosen.id} no_item={chosen.no_item} no_risiko={chosen.no_risiko} | {chosen.peristiwa_risiko} | KRI={chosen.key_risk_indicators} | KM={km_label!r}")
        else:
            unresolved.append(source_no)
            print(f"    source {label}: {status} | event={src['event']!r} | KRI={src['kri']!r} | KPI={src['indicator']!r}")
            for c in candidates[:10]:
                print(f"      candidate id={c.id} no_item={c.no_item} no_risiko={c.no_risiko} KM={getattr(c.km_item,'indikator_kinerja_kunci',None)!r}")
    print(f"  mapping resolved={len(mapping)}/{EXPECTED_CANONICAL}; distinct={len(set(x.id for x in mapping.values()))}")

    tahun=TahunBuku.objects.filter(tahun=YEAR).first()
    for month in (5,6,7):
        report=None
        if tahun:
            period=PeriodeLaporan.objects.filter(tahun_buku=tahun,kode_periode=f"{YEAR}-{month:02d}").first()
            if period:
                report=MonthlyRiskReport.objects.filter(reassessment=profile,periode=period,versi=1).first()
        if report:
            print(f"  {SOURCE[month]['month_name']} report: FOUND id={report.id}, kode={report.kode}, status={report.status}, items={report.items.count()}")
        else:
            print(f"  {SOURCE[month]['month_name']} report: MISSING -> will create")
    return profile,mapping,unresolved


def run(apply=False):
    profile,mapping,unresolved=audit()
    if unresolved or len(mapping)!=EXPECTED_CANONICAL or len(set(x.id for x in mapping.values()))!=EXPECTED_CANONICAL:
        raise RuntimeError(f"Mapping source belum aman. unresolved={unresolved}, resolved={len(mapping)}/{EXPECTED_CANONICAL}. Database TIDAK diubah.")
    if not apply:
        print("MODE: AUDIT SAJA")
        print("Tidak ada data diubah. Jalankan --apply hanya setelah mapping 17/17 direview.")
        return

    prepared=get_prepared_by(profile)
    if not prepared:
        raise RuntimeError("prepared_by tidak ditemukan")
    backup_sqlite()

    with transaction.atomic():
        tahun,_=TahunBuku.objects.get_or_create(tahun=YEAR,defaults={"aktif":True})
        results=[]
        for month in (5,6,7):
            period=get_period(tahun,month)
            report,created=MonthlyRiskReport.objects.get_or_create(
                reassessment=profile,periode=period,versi=1,
                defaults={
                    "kode":f"MRR-DISYAN-{YEAR}-{month:02d}",
                    "tahun_buku":tahun,
                    "status":"draft",
                    "prepared_by":prepared,
                    "kontrak_manajemen":profile.kontrak_manajemen,
                }
            )
            if report.status not in ALLOWED_STATUSES:
                raise RuntimeError(f"Report {report.id} {report.kode} status={report.status}; hanya draft/revision yang boleh diupdate")
            changed=[]
            if not report.kode: report.kode=f"MRR-DISYAN-{YEAR}-{month:02d}"; changed.append("kode")
            if not report.tahun_buku_id: report.tahun_buku=tahun; changed.append("tahun_buku")
            if not report.prepared_by_id: report.prepared_by=prepared; changed.append("prepared_by")
            if not report.kontrak_manajemen_id: report.kontrak_manajemen=profile.kontrak_manajemen; changed.append("kontrak_manajemen")
            if changed: report.save(update_fields=changed+["updated_at"])

            # Protect against unknown pre-existing rows: do not delete silently.
            known_ids={r.id for r in mapping.values()}
            extras=list(report.items.exclude(risk_event_id__in=known_ids).values_list("risk_event_id",flat=True))
            if extras:
                raise RuntimeError(f"Report {report.kode} memiliki item di luar mapping canonical: {extras}. Tidak dihapus otomatis.")

            new_items=0
            for source_no,risk_event in mapping.items():
                _,created_item=apply_item(report,risk_event,SOURCE[month]["items"][source_no])
                new_items += int(created_item)
            report.total_risiko=report.items.count()
            report.total_high=report.items.filter(realisasi_level_risiko__icontains="high").count()
            report.total_mitigasi_terlambat=report.items.filter(mitigation_status="delayed").count()
            report.total_selesai=report.items.filter(status_rencana_perlakuan="discontinue").count()
            report.save(update_fields=["total_risiko","total_high","total_mitigasi_terlambat","total_selesai","updated_at"])
            results.append((month,report,created,new_items))

    print("MODE: APPLY")
    print("APPLY OK")
    print(f"  profile={profile.id} {profile.judul}; canonical risks={len(mapping)}")
    for month,report,created,new_items in results:
        print(f"  {SOURCE[month]['month_name']}: report id={report.id}, kode={report.kode}, created={created}, items={report.items.count()}, new_items={new_items}, status={report.status}")
        for source_no,risk_event in mapping.items():
            item=report.items.get(risk_event=risk_event)
            label="8+9" if source_no==8 else str(source_no)
            print(f"    source {label} -> risk_event={risk_event.id} item={item.id}; impact={item.realisasi_nilai_dampak}; prob={item.realisasi_nilai_probabilitas}; score={item.realisasi_skor_risiko}; level={item.realisasi_level_risiko!r}; actual_cost={item.realisasi_biaya_perlakuan}; progress={item.progress_pelaksanaan_percent}; KRI={item.realisasi_threshold_kri!r}/{item.realisasi_threshold_kri_skor!r}")

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true",help="Commit perubahan ke database production")
    args=parser.parse_args()
    run(apply=args.apply)
