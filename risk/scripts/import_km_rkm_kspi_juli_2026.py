"""Import Kontrak Manajemen (KM) KSPI 2026 + RKM KSPI Juli 2026.

Source document:
    7. Pencapaian Kontrak Manajemen Tahun 2026
    Satuan Pengawasan Intern (SPI) s.d Juli 2026.pdf

Source mapping:
- pages 1-2 : Pencapaian Kontrak Manajemen SPI s.d. Juli 2026 (10 KPI)
- pages 8-14: Rencana Kerja Manajemen (RKM) KSPI Tahun 2026

Safe default (read-only audit):
    python risk/scripts/import_km_rkm_kspi_juli_2026.py

Apply:
    python risk/scripts/import_km_rkm_kspi_juli_2026.py --apply

Production example:
    PYTHONPATH=/home/adminsvr/erm \
    DJANGO_SETTINGS_MODULE=riskproject.settings.prod \
    python risk/scripts/import_km_rkm_kspi_juli_2026.py

Design rules:
- Uses unit/group KSPI and one 2026 KM titled KSPI.
- Reuses/updates existing KM KPI rows; it does not delete unrelated production rows.
- Imports one RKM summary for July 2026 and one RKMItem per KM KPI (10 KPI).
  Where the source RKM has several activity rows for one KPI, the activity content is
  consolidated into the corresponding RKMItem because the application enforces one
  RKMItem per KM item per monthly summary.
- Source/document achievement values are preserved after save(), so they are not
  silently recalculated by generic model logic.
- Existing RKM rows outside these 10 source KPI are retained and reported.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.dev")

import django

django.setup()

from django.contrib.auth.models import Group
from django.db import transaction

from risk.models import (
    BagianKontrakManajemen,
    ItemKontrakManajemen,
    KontrakManajemen,
    MasterBagianKM,
    MasterTemplateKM,
    RKMItem,
    RKMSummary,
)

YEAR = 2026
MONTH = 7
UNIT_NAME = "KSPI"
KM_TITLE = "KSPI"
RKM_TITLE = "RKM KSPI Juli 2026"
SOURCE_SIGNED_DATE = date(2026, 8, 3)

SECTIONS = {
    "A": "Nilai Ekonomi dan Sosial Untuk Indonesia",
    "B": "Inovasi Model Bisnis",
    "C": "Kepemimpinan Teknologi",
    "D": "Peningkatan Investasi",
    "E": "Pengembangan Talenta",
    "F": "Kepatuhan",
}

COMPLIANCE_FORMULA = """Jumlah nilai pengurang dari unsur:
- Maturity Level GCG
- Kepatuhan Pengelolaan HSSE
- Tindak lanjut temuan SPI, BPK, dan Auditor lainnya
- Keterlambatan Laporan Kinerja (termasuk laporan manajemen risiko)
- Planning Accuracy Compliance Adjustment (PACA)"""

HC_FORMULA = """Rata-rata Pencapaian:
1. Produktivitas Pegawai dan Penguatan Budaya
2. Pengelolaan Human Capital Services"""


@dataclass(frozen=True)
class KMRow:
    no: int
    section: str
    indicator: str
    formula: str
    unit: str
    weight: float
    target: str
    polarity: str = "positif"
    july_actual: str = ""
    july_achievement: Decimal | None = None
    july_value: str = ""
    note: str = ""


KM_ROWS = [
    KMRow(
        1,
        "A",
        "Prosentase Penyelesaian Tindak Lanjut Temuan/Rekomendasi SPI PT PLN (Persero) & Audit Internal PLN Batam",
        "Jumlah temuan dan rekomendasi yang sudah ditindaklanjuti x 100% / Jumlah temuan dan rekomendasi jatuh tempo yang harus ditindaklanjuti",
        "%",
        14,
        "100%",
        july_actual="111,11%",
        july_achievement=Decimal("110.00"),
        july_value="15,40",
        note="Sebanyak 20 rekomendasi dari 18 rekomendasi yang jatuh tempo sampai bulan Juli 2026 telah selesai ditindaklanjuti tepat waktu (Lampiran 1).",
    ),
    KMRow(
        2,
        "A",
        "Prosentase Tepat Waktu Penyelesaian Tindak Lanjut Temuan/Rekomendasi SPI PT PLN (Persero) & Audit Internal PLN Batam",
        "Jumlah temuan dan rekomendasi ditindaklanjuti tepat waktu x 100% / Jumlah temuan dan rekomendasi yang jatuh tempo",
        "%",
        12,
        "100%",
        july_actual="100,00%",
        july_achievement=Decimal("100.00"),
        july_value="12,00",
        note="Sebanyak 18 rekomendasi dari 18 rekomendasi yang jatuh tempo sampai bulan Juli 2026 telah ditindaklanjuti tepat waktu (Lampiran 1).",
    ),
    KMRow(
        3,
        "A",
        "Advancing in Sustainable Development Goals (SDGs)",
        "Skor Maturitas SPI",
        "Skor",
        16,
        "3,15",
        july_actual="-",
        july_achievement=Decimal("100.00"),
        july_value="16,00",
        note="Hasil penilaian akan disampaikan pada TW IV 2026.",
    ),
    KMRow(
        4,
        "A",
        "Kualitas Penerapan Manajemen Risiko (KPMR)",
        "Penerapan Manajemen Risiko (KPMR) di Satuan Pengawasan Intern",
        "Skor",
        12,
        "80",
        july_actual="89",
        july_achievement=Decimal("110.00"),
        july_value="13,20",
        note="Kertas Kerja Self Assessment KPMR SPI sampai bulan Juli 2026 (Lampiran 5).",
    ),
    KMRow(
        5,
        "A",
        "Perbaikan Tingkat Defisiensi ICOFR",
        "Penyelesaian tindak lanjut defisiensi sesuai laporan hasil evaluasi manajemen atas efektivitas pengendalian internal atas pelaporan keuangan (ICOFR) tahun 2025",
        "%",
        8,
        "50",
        "negatif",
        july_actual="-",
        july_achievement=Decimal("100.00"),
        july_value="8,00",
        note="Laporan hasil evaluasi manajemen efektivitas pengendalian internal atas pelaporan keuangan (ICOFR) PT PLN Batam tanggal 24 April 2026. Tindak lanjut defisiensi On Progress.",
    ),
    KMRow(
        6,
        "B",
        "Pelaksanaan Audit Internal",
        "Rata-rata Selesainya Laporan Hasil Audit Tahun 2026 Sesuai PKPT 2026",
        "Hari Kerja",
        12,
        "40",
        "negatif",
        july_actual="34",
        july_achievement=Decimal("110.00"),
        july_value="13,20",
        note="Audit selesai: Audit Subsidi Listrik, Audit ICOFR, Audit UB BES, dan Audit Tematik Manajemen Risiko. Pelaksanaan Audit UB DISYAN On Progress (Lampiran 3).",
    ),
    KMRow(
        7,
        "C",
        "Penyelesaian Tindak Lanjut Temuan/Rekomendasi BPK & KAP",
        "Tersedianya monitoring penyelesaian tindak lanjut temuan/rekomendasi BPK dan KAP tepat waktu",
        "%",
        8,
        "100%",
        july_actual="100,00%",
        july_achievement=Decimal("100.00"),
        july_value="8,00",
        note="Laporan Monitoring Penyelesaian Tindak Lanjut BPK RI dan KAP (Lampiran 2).",
    ),
    KMRow(
        8,
        "D",
        "Layanan Konsultasi",
        "Jumlah hari realisasi konsultasi x 100% / Jumlah hari BA Kesepakatan konsultasi",
        "%",
        8,
        "100%",
        july_actual="100,00%",
        july_achievement=Decimal("100.00"),
        july_value="8,00",
        note="Laporan Monitoring Layanan Konsultasi (Lampiran 4). Tidak ada permintaan konsultasi dari klien s.d. Juli 2026.",
    ),
    KMRow(
        9,
        "E",
        "Pengelolaan Human Capital",
        HC_FORMULA,
        "%",
        10,
        "100%",
        july_actual="-",
        july_achievement=Decimal("100.00"),
        july_value="10,00",
        note="Pemantauan program HCR/OCR; pada RKM Juli tercatat On Progress.",
    ),
    KMRow(
        10,
        "F",
        "Compliance",
        COMPLIANCE_FORMULA,
        "Nilai Pengurang",
        0,
        "Max -10",
        "negatif",
        july_actual="",
        july_achievement=None,
        july_value="0,00",
        note="Nilai pengurang maksimum -10 sesuai Kontrak Manajemen 2026.",
    ),
]


@dataclass(frozen=True)
class RKMSourceRow:
    no: int
    section: str
    km_indicator: str
    target: str
    initiative: str
    program: str
    risk: str
    mitigation: str
    action: str
    target_accumulation: str
    target_unit: str
    july_actual: str
    achievement: Decimal | None
    analysis: str


RKM_ROWS = [
    RKMSourceRow(
        1,
        "A",
        KM_ROWS[0].indicator,
        "100,00",
        "Memastikan dan memonitoring tindak lanjut temuan auditor internal dan SPI PT PLN (Persero) di Tahun 2026 ditindaklanjuti 100%.",
        "Monitoring tindak lanjut melalui auditor SPI PT PLN (Persero)/internal, update aplikasi eRBAS, komunikasi dengan auditor, evaluasi dokumen tindak lanjut, pembahasan tindak lanjut bila diperlukan, dan laporan monitoring tindak lanjut kepada DIRUT/Komite Audit.",
        "Auditee tidak peduli dengan komitmen tenggat waktu penyelesaian rekomendasi; auditee kurang memahami mekanisme update tindak lanjut pada eRBAS; tindak lanjut dapat terkendala pihak ketiga/komunikasi.",
        "Reminder berkala kepada auditee; memastikan auditee mampu mengoperasikan eRBAS; konsultasi/koordinasi dengan auditor dan PIC; monitoring periodik sampai target waktu yang disepakati.",
        "Memberikan reminder kepada auditee, pendampingan penggunaan eRBAS, komunikasi dengan auditor SPI PT PLN (Persero), menyusun notulen/pembahasan tindak lanjut, dan menyampaikan laporan progress.",
        "Rekomendasi ditindaklanjuti 100% sesuai kesepakatan waktu tindak lanjut yang jatuh tempo di tahun 2026.",
        "%",
        "111,11%",
        Decimal("110.00"),
        KM_ROWS[0].note,
    ),
    RKMSourceRow(
        2,
        "A",
        KM_ROWS[1].indicator,
        "100,00",
        "Memastikan dan memonitoring tindak lanjut temuan auditor SPI PT PLN (Persero) yang jatuh tempo di Tahun 2026 ditindaklanjuti tepat waktu 100%.",
        "Monitoring tepat waktu melalui reminder auditor, update eRBAS, koordinasi dengan admin eRBAS PT PLN (Persero), konsultasi dengan auditor, evaluasi dokumen, dan laporan monitoring triwulanan.",
        "Keterlambatan atau ketidakpedulian auditee terhadap tenggat waktu; auditee kurang memahami update eRBAS; komunikasi/ketersediaan waktu dapat menghambat penyelesaian.",
        "Reminder berkala, pendampingan eRBAS, koordinasi dengan admin/auditor, serta pembahasan hambatan tindak lanjut.",
        "Reminder kepada auditee, sosialisasi/refresment eRBAS, koordinasi dengan admin eRBAS, dan konsultasi dengan auditor SPI PT PLN (Persero).",
        "Rekomendasi ditindaklanjuti 100% sesuai kesepakatan waktu tindak lanjut yang jatuh tempo di tahun 2026.",
        "%",
        "100,00%",
        Decimal("100.00"),
        KM_ROWS[1].note,
    ),
    RKMSourceRow(
        3,
        "A",
        KM_ROWS[2].indicator,
        "3,15",
        "Pemenuhan Roadmap QAR Tahun 2026.",
        "Pelaksanaan peluang peningkatan atas hasil evaluasi Self Assessment QAR Tahun 2025.",
        "Tidak tercapainya indeks Maturity Level SPI Tahun 2026 dan tidak terlaksananya assessment QAR Tahun 2026.",
        "Penetapan tindak lanjut rekomendasi peluang peningkatan QAR secara berkala dan koordinasi dengan SPI PT PLN (Persero).",
        "Menyampaikan tindak lanjut rekomendasi peluang peningkatan QAR secara berkala ke SPI PT PLN (Persero) dan melakukan koordinasi untuk pemantauan peluang peningkatan.",
        "Dokumen hasil evaluasi QAR.",
        "Skor Maturity Level SPI",
        "Laporan Progress Tindak Lanjut Peluang Peningkatan atas Hasil Evaluasi Self Assessment QAR Tahun 2025 s.d Maret 2026",
        Decimal("100.00"),
        "Telah disampaikan ke SPI PT PLN (Persero) pada 10 Juli 2026.",
    ),
    RKMSourceRow(
        4,
        "A",
        KM_ROWS[3].indicator,
        "80",
        "Self Assessment roadmap Penerapan Manajemen Risiko SPI Tahun 2026.",
        "Menyusun dan menyiapkan evidence roadmap implementasi Manajemen Risiko sesuai target setiap bulan; melakukan evaluasi mitigasi risiko dan KRI.",
        "Keterlambatan penyimpanan/penyampaian Self Assessment Kualitas Penerapan Manajemen Risiko (KPMR) SPI Tahun 2026 dan keterlambatan penyampaian evaluasi mitigasi risiko/KRI.",
        "Penunjukan PIC Assessment Kualitas Penerapan Manajemen Risiko (KPMR) SPI Tahun 2026 dan PIC laporan monitoring risiko/KRI.",
        "Melakukan Self Assessment Kualitas Penerapan Manajemen Risiko (KPMR) tepat waktu dan menyampaikan laporan monitoring mitigasi risiko serta key risk indicator tepat waktu.",
        "Self Assessment Kualitas Penerapan Manajemen Risiko (KPMR) pada setiap bulan Tahun 2026 tepat waktu; laporan monitoring mitigasi risiko dan KRI tersedia setiap tanggal 5 m+1.",
        "Skor",
        "Kertas Kerja Self Assessment KPMR SPI; laporan monitoring mitigasi risiko dan key risk indicator tersedia setiap tanggal 5 m+1",
        Decimal("110.00"),
        KM_ROWS[3].note,
    ),
    RKMSourceRow(
        5,
        "A",
        KM_ROWS[4].indicator,
        "50",
        "Penyelesaian tindak lanjut defisiensi sesuai laporan hasil evaluasi manajemen atas efektivitas pengendalian internal atas pelaporan keuangan (ICOFR) tahun 2025.",
        "Tersedianya Laporan Hasil Audit TOE Lini 3 ICOFR (TLC) dan monitoring perbaikan defisiensi atas laporan keuangan (ICOFR) tahun 2025.",
        "Keterlambatan penyampaian laporan hasil Audit TOE Lini 3 ICOFR (TLC) dan defisiensi hasil pelaksanaan ICOFR tidak ditindaklanjuti oleh Lini 1/Lini 2.",
        "Review progress pelaksanaan TOE Lini 3 secara berkala dan monitoring tindak lanjut perbaikan defisiensi atas pelaporan keuangan (ICOFR) tahun 2025.",
        "Ketua Tim melakukan review progress pelaksanaan TOE Lini 3 serta menyampaikan hasil monitoring perbaikan defisiensi kepada Lini 1/Lini 2.",
        "Tersedianya Laporan Hasil Audit TOE Lini 3 ICOFR (TLC); perbaikan defisiensi atas hasil pemeriksaan ICOFR TLC Lini 3 pada transaksi keuangan TA 2025 sebesar 50%.",
        "%",
        "Laporan hasil evaluasi manajemen efektivitas pengendalian internal atas pelaporan keuangan (ICOFR) PT PLN Batam tanggal 24 April 2026; tindak lanjut defisiensi On Progress",
        Decimal("100.00"),
        KM_ROWS[4].note,
    ),
    RKMSourceRow(
        6,
        "B",
        KM_ROWS[5].indicator,
        "40",
        "Rata-rata selesainya Laporan Hasil Audit sesuai PKPT Terintegrasi Tahun 2026.",
        "Melaksanakan audit sesuai PKPT Terintegrasi Tahun 2026 melalui penyusunan Program Kerja Audit (PKA), pelaksanaan/kertas kerja audit (KKA), dan penyusunan Laporan Hasil Audit (LHA).",
        "Waktu yang ditetapkan tidak memadai untuk menyelesaikan pelaksanaan audit dan keterbatasan kompetensi auditor.",
        "Menyusun program kerja audit yang efektif/efisien serta melakukan sharing kompetensi terkait pelaksanaan audit.",
        "Menyusun PKA, melaksanakan audit sesuai PKA/KKA, dan menyusun LHA.",
        "Program Kerja Audit (PKA), Kertas Kerja Audit (KKA), dan Laporan Hasil Audit (LHA).",
        "Hari Kerja",
        "34 Hari Kerja",
        Decimal("110.00"),
        KM_ROWS[5].note,
    ),
    RKMSourceRow(
        7,
        "C",
        KM_ROWS[6].indicator,
        "100,00",
        "Memastikan progress tindak lanjut rekomendasi temuan auditor BPK-RI dan KAP dimonitoring dan ditindaklanjuti.",
        "Reminder kepada auditee, evaluasi dokumen tindak lanjut, pembahasan tindak lanjut dengan Tim TL BPK RI, penyusunan jadwal pembahasan, laporan monitoring, komunikasi dengan auditor KAP, dan laporan progress.",
        "Auditee tidak peduli dengan komitmen tenggat waktu; rekomendasi tidak dapat ditindaklanjuti; keterbatasan waktu pembahasan; tindak lanjut KAP tidak dapat dihubungi/ditindaklanjuti.",
        "Reminder berkala, pembahasan dengan Tim TL BPK RI, konsultasi/koordinasi dengan auditee dan auditor KAP, serta monitoring laporan progress.",
        "Email reminder tindak lanjut rekomendasi, notulen/surat pernyataan/BA rekonsiliasi bila ada, undangan pembahasan, laporan progress, dan komunikasi status closed rekomendasi KAP.",
        "Penyelesaian tindak lanjut BPK RI/KAP tepat waktu dan laporan progress pelaksanaan tindak lanjut.",
        "%",
        "100,00%",
        Decimal("100.00"),
        KM_ROWS[6].note,
    ),
    RKMSourceRow(
        8,
        "D",
        KM_ROWS[7].indicator,
        "100,00",
        "Memastikan pelaksanaan layanan konsultasi atas permintaan auditee terlaksana tepat waktu.",
        "Menyusun Program Kerja Konsultasi (PK-KONS), melaksanakan layanan konsultasi sesuai PK-KONS, dan menyusun Laporan Hasil Konsultasi (LH-KONS).",
        "Waktu yang ditetapkan tidak memadai untuk menyelesaikan pelaksanaan layanan konsultasi dan keterbatasan kompetensi auditor.",
        "Menyusun program kerja konsultasi yang efektif/efisien serta sharing kompetensi terkait pelaksanaan layanan konsultasi.",
        "Menyusun PK-KONS, melaksanakan layanan konsultasi sesuai PK-KONS, dan menyusun LH-KONS.",
        "Laporan Hasil Konsultasi (LH-KONS) jika ada penugasan.",
        "%",
        "Tidak ada permintaan konsultasi dari klien s.d. Juli 2026",
        Decimal("100.00"),
        KM_ROWS[7].note,
    ),
    RKMSourceRow(
        9,
        "E",
        KM_ROWS[8].indicator,
        "100,00",
        "Pemenuhan Nilai Hasil Asesmen Manajemen SDM (HCR/OCR & Produktivitas Pegawai).",
        "Melaksanakan program HCR/OCR.",
        "Tidak ada monitoring pencapaian HCR/OCR.",
        "Penunjukan PIC HCR/OCR.",
        "Melakukan pemantauan program HCR/OCR.",
        "Pemenuhan nilai hasil asesmen Manajemen SDM (HCR-OCR & Produktivitas Pegawai) pada setiap periode sesuai pedoman kinerja tahun 2026.",
        "%",
        "Pemantauan program HCR/OCR",
        Decimal("100.00"),
        "On Progress.",
    ),
    RKMSourceRow(
        10,
        "F",
        KM_ROWS[9].indicator,
        "Max -10",
        "",
        "",
        "",
        "",
        "",
        "",
        "Nilai Pengurang",
        "",
        None,
        KM_ROWS[9].note,
    ),
]


def norm(value: str | None) -> str:
    value = (value or "").lower().replace("\xa0", " ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def find_group():
    exact = Group.objects.filter(name__iexact=UNIT_NAME).order_by("id").first()
    if exact:
        return exact
    candidates = list(Group.objects.filter(name__icontains="SPI").order_by("id"))
    if len(candidates) == 1:
        return candidates[0]
    return None


def find_contract(unit):
    if not unit:
        return None
    qs = KontrakManajemen.objects.filter(tahun=YEAR, unit_bisnis=unit).order_by("id")
    exact = qs.filter(judul__iexact=KM_TITLE).first()
    if exact:
        return exact
    kspi = [x for x in qs if "kspi" in norm(x.judul) or norm(x.judul) == "spi"]
    if len(kspi) == 1:
        return kspi[0]
    if qs.count() == 1:
        return qs.first()
    return None


def find_km_item(kontrak, row: KMRow):
    if not kontrak:
        return None
    candidates = list(
        ItemKontrakManajemen.objects.filter(
            kontrak=kontrak,
            master_bagian__kode_bagian=row.section,
        ).select_related("master_bagian")
    )
    target = norm(row.indicator)
    for item in candidates:
        if norm(item.indikator_kinerja_kunci) == target:
            return item

    # Conservative source aliases for known legacy wording.
    aliases = {
        1: ["prosentase penyelesaian tindak lanjut temuan rekomendasi"],
        2: ["prosentase tepat waktu penyelesaian tindak lanjut"],
        3: ["advancing in sustainable development goals"],
        4: ["kualitas penerapan manajemen risiko"],
        5: ["defisiensi icofr", "defiensi icofr"],
        6: ["pelaksanaan audit internal"],
        7: ["penyelesaian tindak lanjut temuan rekomendasi bpk kap"],
        8: ["layanan konsultasi"],
        9: ["pengelolaan human capital"],
        10: ["compliance"],
    }
    for item in candidates:
        text = norm(item.indikator_kinerja_kunci)
        if any(alias in text for alias in aliases[row.no]):
            return item
    return None


def source_audit():
    print("SOURCE AUDIT")
    print(
        f"  KM pages 1-2: items={len(KM_ROWS)}, "
        f"bobot={sum(row.weight for row in KM_ROWS):.2f}"
    )
    by_section = {code: Decimal("0") for code in SECTIONS}
    for row in KM_ROWS:
        by_section[row.section] += Decimal(str(row.weight))
    print(
        "  KM bobot per bagian: "
        + ", ".join(f"{code}={weight:.2f}" for code, weight in by_section.items())
    )
    print(f"  RKM pages 8-14: KPI rows consolidated={len(RKM_ROWS)}")
    print("  Juli headline values:")
    for row in KM_ROWS:
        cap = "-" if row.july_achievement is None else f"{row.july_achievement}%"
        print(
            f"    {row.no}. {row.indicator}: target={row.target!r}, "
            f"realisasi={row.july_actual!r}, capaian={cap}, nilai={row.july_value!r}"
        )


def audit_baseline():
    print("BASELINE")
    unit = find_group()
    if unit:
        print(f"  unit: FOUND id={unit.id}, name={unit.name!r}")
    else:
        print(f"  unit: MISSING -> will create {UNIT_NAME!r}")

    kontrak = find_contract(unit)
    if kontrak:
        item_count = ItemKontrakManajemen.objects.filter(kontrak=kontrak).count()
        print(
            f"  KM: FOUND id={kontrak.id}, judul={kontrak.judul!r}, "
            f"status={kontrak.status}, items={item_count}"
        )
        for row in KM_ROWS:
            item = find_km_item(kontrak, row)
            if item:
                print(
                    f"    KM {row.no}: FOUND id={item.id}; section={row.section}; "
                    f"bobot={item.bobot}; target={item.target!r}; {item.indikator_kinerja_kunci}"
                )
            else:
                print(f"    KM {row.no}: MISSING -> will create: {row.indicator}")
    else:
        print(f"  KM: MISSING -> will create {KM_TITLE!r}")

    summary = None
    if unit and kontrak:
        summary = RKMSummary.objects.filter(
            tahun=YEAR,
            bulan=MONTH,
            unit_bisnis=unit,
            kontrak_manajemen=kontrak,
        ).order_by("id").first()
    if summary:
        print(
            f"  RKM: FOUND id={summary.id}, judul={summary.judul!r}, "
            f"status={summary.status}, status_pengajuan={summary.status_pengajuan}, "
            f"items={RKMItem.objects.filter(summary=summary).count()}"
        )
    else:
        print(f"  RKM: MISSING -> will create {RKM_TITLE!r}")


def ensure_structure():
    unit = find_group()
    if unit is None:
        unit = Group.objects.create(name=UNIT_NAME)

    template, _ = MasterTemplateKM.objects.get_or_create(
        tahun=YEAR,
        defaults={"nama": f"Bagian KM {YEAR}"},
    )

    masters = {}
    for order, (code, name) in enumerate(SECTIONS.items(), start=1):
        master, _ = MasterBagianKM.objects.get_or_create(
            template=template,
            kode_bagian=code,
            defaults={"nama_bagian": name, "urutan": order},
        )
        changes = []
        if master.nama_bagian != name:
            master.nama_bagian = name
            changes.append("nama_bagian")
        if master.urutan != order:
            master.urutan = order
            changes.append("urutan")
        if changes:
            master.save(update_fields=changes)
        masters[code] = master

    kontrak = find_contract(unit)
    if kontrak is None:
        kontrak = KontrakManajemen.objects.create(
            judul=KM_TITLE,
            tahun=YEAR,
            unit_bisnis=unit,
            status="Final",
            template=template,
        )
    else:
        changes = []
        if kontrak.judul != KM_TITLE:
            kontrak.judul = KM_TITLE
            changes.append("judul")
        if kontrak.template_id != template.id:
            kontrak.template = template
            changes.append("template")
        if kontrak.status != "Final":
            kontrak.status = "Final"
            changes.append("status")
        if changes:
            kontrak.save(update_fields=changes)

    parts = {}
    for code, name in SECTIONS.items():
        part, _ = BagianKontrakManajemen.objects.get_or_create(
            kontrak=kontrak,
            kode_bagian=code,
            defaults={"nama_bagian": name},
        )
        if part.nama_bagian != name:
            part.nama_bagian = name
            part.save(update_fields=["nama_bagian"])
        parts[code] = part

    return unit, template, masters, kontrak, parts


def ensure_km_items(kontrak, masters, parts):
    result = {}
    created = 0
    reused = 0

    for row in KM_ROWS:
        item = find_km_item(kontrak, row)
        if item is None:
            desired = row.no
            if ItemKontrakManajemen.objects.filter(
                kontrak=kontrak,
                master_bagian=masters[row.section],
                no_urut=desired,
            ).exists():
                existing_numbers = list(
                    ItemKontrakManajemen.objects.filter(
                        kontrak=kontrak,
                        master_bagian=masters[row.section],
                    ).values_list("no_urut", flat=True)
                )
                desired = max(existing_numbers or [0]) + 1
            item = ItemKontrakManajemen(
                kontrak=kontrak,
                master_bagian=masters[row.section],
                bagian=parts[row.section],
                no_urut=desired,
            )
            created += 1
        else:
            reused += 1

        item.master_bagian = masters[row.section]
        item.bagian = parts[row.section]
        item.indikator_kinerja_kunci = row.indicator
        item.formula = row.formula
        item.satuan = row.unit
        item.bobot = row.weight
        item.target = row.target
        item.polaritas = row.polarity
        item.save()
        result[row.no] = item

    return result, created, reused


def apply_import():
    with transaction.atomic():
        unit, _template, masters, kontrak, parts = ensure_structure()
        km_items, km_created, km_reused = ensure_km_items(kontrak, masters, parts)

        summary = RKMSummary.objects.filter(
            tahun=YEAR,
            bulan=MONTH,
            unit_bisnis=unit,
            kontrak_manajemen=kontrak,
        ).order_by("id").first()

        summary_created = False
        if summary is None:
            summary = RKMSummary.objects.create(
                judul=RKM_TITLE,
                tahun=YEAR,
                bulan=MONTH,
                unit_bisnis=unit,
                kontrak_manajemen=kontrak,
                tanggal_mulai=date(YEAR, MONTH, 1),
                tanggal_selesai=date(YEAR, MONTH, 31),
                status="Final",
                pic=UNIT_NAME,
                tanggal_pengajuan=SOURCE_SIGNED_DATE,
            )
            summary_created = True
        else:
            summary.judul = RKM_TITLE
            summary.tanggal_mulai = summary.tanggal_mulai or date(YEAR, MONTH, 1)
            summary.tanggal_selesai = summary.tanggal_selesai or date(YEAR, MONTH, 31)
            summary.pic = summary.pic or UNIT_NAME
            summary.tanggal_pengajuan = summary.tanggal_pengajuan or SOURCE_SIGNED_DATE
            # Source page 14 is signed/approved by PLH KSPI on 03 Aug 2026.
            summary.status = "Final"
            summary.save()

        imported_ids = []
        for src in RKM_ROWS:
            km_item = km_items[src.no]
            existing = RKMItem.objects.filter(summary=summary, km_item=km_item).first()
            conflict = (
                RKMItem.objects.filter(summary=summary, no_item=src.no)
                .exclude(km_item=km_item)
                .first()
            )
            if conflict:
                raise RuntimeError(
                    f"Konflik no_item={src.no}: sudah digunakan RKMItem id={conflict.id} "
                    f"untuk KPI {conflict.kpi_indikator!r}. Tidak ada data yang dihapus."
                )

            defaults = {
                "no_item": src.no,
                "kategori_rkm": src.section,
                "sasaran": km_item.indikator_kinerja_kunci,
                "kpi_indikator": km_item.indikator_kinerja_kunci,
                "kpi_satuan": km_item.satuan,
                "kpi_target": src.target,
                "inisiatif_strategis": src.initiative,
                "program_kerja_utama": src.program,
                "risiko": src.risk,
                "mitigasi_risiko": src.mitigation,
                "rencana_aksi": src.action,
                "target_akumulasi": src.target_accumulation,
                "target_akumulasi_satuan": src.target_unit or km_item.satuan,
                "target_juli": src.target,
                "realisasi_juli": src.july_actual,
                "jumlah_realisasi": src.july_actual,
                "pic_rkm": UNIT_NAME,
                "hasil_analisa_program_kerja": src.analysis,
                "target_bulanan": f"Juli 2026 - {src.target_accumulation}" if src.target_accumulation else "",
                "realisasi": f"Juli 2026 - {src.july_actual}" if src.july_actual else "",
                "deviasi": (
                    f"Capaian Juli 2026 sesuai dokumen: {src.achievement}%"
                    if src.achievement is not None
                    else ""
                ),
                "keterangan": src.analysis,
            }

            if existing:
                for field, value in defaults.items():
                    setattr(existing, field, value)
                existing.save()
                item = existing
            else:
                item = RKMItem.objects.create(summary=summary, km_item=km_item, **defaults)

            # Preserve source/document achievement exactly.
            RKMItem.objects.filter(pk=item.pk).update(
                persen_capaian=src.achievement,
                jumlah_realisasi=src.july_actual,
            )
            imported_ids.append(item.id)

        extras = RKMItem.objects.filter(summary=summary).exclude(id__in=imported_ids).count()

        print("APPLY OK")
        print(f"  unit={unit.id} {unit.name}")
        print(
            f"  KM={kontrak.id} {kontrak.judul}; source KM items created={km_created}, "
            f"updated/reused={km_reused}, total_source={len(KM_ROWS)}"
        )
        print(
            f"  RKM={summary.id} {summary.judul}; created={summary_created}; "
            f"status={summary.status}; status_pengajuan={summary.status_pengajuan}; "
            f"source rows imported/updated={len(imported_ids)}"
        )
        print(f"  existing RKM rows outside source retained={extras}")
        for src in RKM_ROWS:
            item = RKMItem.objects.get(summary=summary, km_item=km_items[src.no])
            print(
                f"    {src.no}: RKMItem id={item.id}; target={item.kpi_target!r}; "
                f"realisasi Juli={item.realisasi_juli!r}; capaian={item.persen_capaian}%; "
                f"KPI={item.kpi_indikator}"
            )


def main(apply: bool):
    source_audit()
    audit_baseline()
    if not apply:
        print("MODE: AUDIT SAJA")
        print("Tidak ada data diubah. Jalankan kembali dengan --apply setelah output audit diperiksa.")
        return
    print("MODE: APPLY")
    apply_import()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply KM KSPI 2026 and RKM KSPI Juli 2026 import",
    )
    args = parser.parse_args()
    main(args.apply)
