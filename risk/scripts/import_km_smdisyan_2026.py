"""Import/merge Kontrak Manajemen SM DISYAN 2026 from three approved screenshots.

Default is read-only audit:
    python risk/scripts/import_km_smdisyan_2026.py

Apply changes:
    python risk/scripts/import_km_smdisyan_2026.py --apply

Design rules:
- All three screenshot sets are stored in ONE KM: SM DISYAN / UB DISYAN / 2026.
- Existing ItemKontrakManajemen rows referenced by ReAssessmentItem are reused when
  a semantic match is found. Referenced legacy rows that do not occur in the
  screenshots are retained at the end of their section so FK relations never break.
- Unreferenced stale/blank rows are removed on apply.
- Imported rows are numbered sequentially within A-F. Duplicate KPI names are
  intentionally allowed because the user confirmed all three screenshot sets belong
  to the same KM.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.dev")

import django

django.setup()

from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Count

from risk.models import (
    BagianKontrakManajemen,
    ItemKontrakManajemen,
    KontrakManajemen,
    MasterBagianKM,
    MasterTemplateKM,
    ReAssessmentItem,
)

YEAR = 2026
UNIT_NAME = "UB DISYAN"
TITLE = "SM DISYAN"

SECTIONS = {
    "A": "Nilai Ekonomi dan Sosial Untuk Indonesia",
    "B": "Inovasi Model Bisnis",
    "C": "Kepemimpinan Teknologi",
    "D": "Peningkatan Investasi",
    "E": "Pengembangan Talenta",
    "F": "Kepatuhan",
}

SMT_FORMULA = """Prosentase Rata-rata Waktu Pemenuhan Eviden di tanggal 30 September 2026:\n1. Maturity ISO 22301 Sistem Manajemen Kelangsungan Usaha (SMKU) Level 4\n2. Maturity ISO 45001 Sistem Manajemen Keselamatan dan Kesehatan Kerja (K3) Level 3\n3. Maturity PERMEN ESDM 10/2021 Sistem Manajemen Keselamatan Ketenagalistrikan (SMK2) Level 3\n4. Maturity Sistem Manajemen Aset 55001 Level 2"""

HC_FORMULA = """Rata-rata Pencapaian:\n1. Produktivitas Pegawai dan Penguatan Budaya\n2. Pengelolaan Human Capital Services"""

ICOFR_FORMULA = """Jumlah defisiensi yang sudah ditindaklanjuti di UB DISYAN x 100%\nJumlah defisiensi yang harus ditindaklanjuti di UB DISYAN"""

COMPLIANCE_1 = """Jumlah nilai pengurang dari unsur:\n- Keterlambatan Laporan Kinerja (termasuk laporan manajemen risiko)\n- Maturity Level GCG\n- Kepatuhan pengelolaan HSSE\n- Tindak lanjut temuan SPI, BPK, dan Auditor lainnya\n- Keterlambatan Laporan Kinerja (termasuk laporan manajemen risiko)\n- Pengendalian Nilai Non Allowable Cost/NAC sesuai RKAP 2026\n- Planning Accuracy Compliance Adjustment (PACA)"""

COMPLIANCE_23 = """Jumlah nilai pengurang dari unsur:\n- Keterlambatan Laporan dan Akurasi Data Kinerja Setiap Tanggal 3 pada Bulan N+1\n- Maturity Level GCG\n- Kepatuhan pengelolaan HSSE\n- Tindak lanjut temuan SPI, BPK, dan Auditor lainnya\n- Keterlambatan Laporan Kinerja (termasuk laporan manajemen risiko)\n- Pengendalian Nilai Non Allowable Cost/NAC sesuai RKAP 2026\n- Planning Accuracy Compliance Adjustment (PACA)\n- Tindak Lanjut Defisiensi ICOFR & SPIN"""


@dataclass(frozen=True)
class SourceRow:
    source: int
    section: str
    indicator: str
    formula: str
    unit: str
    weight: float
    target: str
    polarity: str = "positif"


def R(source, section, indicator, formula, unit, weight, target, polarity="positif"):
    return SourceRow(source, section, indicator, formula, unit, float(weight), str(target), polarity)


ROWS = [
    # ------------------------------------------------------------------
    # Screenshot 1
    # ------------------------------------------------------------------
    R(1,"A","Optimalisasi Biaya Pemeliharaan","Realisasi Optimalisasi Biaya Pemeliharaan","%",7,"95 - 100%"),
    R(1,"A","Penjualan Tenaga Listrik TUL 309 Batam","Penjualan Tenaga Listrik TUL 309 Batam","MWh",7,"5,015,013.70"),
    R(1,"A","Maturity Level Sustainability","Hasil Asesmen Maturity Level Sustainability","%",5,"100%"),
    R(1,"A","Kualitas Penerapan Manajemen Risiko (KPMR)","Penerapan Manajemen Risiko (KPMR) di UB DISYAN","Skor",5,"80"),
    R(1,"A","Penambahan Pelanggan","Penambahan Daya (PB, CO, UD, UT) Captive Market, B2B, Layanan Khusus dan TM Potensial","MVA",7,"147.89"),
    R(1,"A","Penghapusan Piutang Ragu-ragu","Penyelesaian Penghapusan Piutang Ragu-ragu Pelanggan","Waktu",7,"30 Nov 2026","negatif"),
    R(1,"A","Pelunasan Legalisasi","Jumlah Pelunasan Legalisasi","Rp Milyar",5,"12"),
    R(1,"B","Penjualan Renewable Energy Certificate (REC) PLN Batam","Pendapatan dari Sertifikat REC","Rp Juta",7,"1,000"),
    R(1,"B","Customer Visit","Seluruh Jumlah Pelanggan TM Tahun 2025","Pelanggan",5,"100"),
    R(1,"C","Susut Distribusi","[(kWh Siap Salur Distribusi - kWh PS - kWh Penjualan) / kWh Siap Salur Distribusi] x 100%","%",7,"3.57","negatif"),
    R(1,"C","Temuan P2TL","kWh Temuan P2TL","MWh",5,"10,000"),
    R(1,"C","Pemeriksaan On Desk","Pemeriksaan On Desk Pelanggan TM 2 kali dalam 1 tahun","%",6,"100"),
    R(1,"C","Implementasi Sistem Manajemen Terintegrasi",SMT_FORMULA,"%",5,"100%"),
    R(1,"D","Pengendalian Penggunaan Anggaran Investasi sesuai RKAP 2026","Kesesuaian Realisasi Anggaran Kas Investasi dengan Pos Anggaran Investasi Sesuai Peruntukannya","%",7,"95 - 100"),
    R(1,"D","Penyelesaian Tindak Lanjut defisiensi ICOFR tahun 2025",ICOFR_FORMULA,"%",5,"50%"),
    R(1,"E","Pengelolaan Human Capital",HC_FORMULA,"%",5,"100%"),
    R(1,"E","Penyelesaian Program Improvement K3L","Penyelesaian Program Improvement K3L sesuai Target x 100 %","%",5,"100%"),
    R(1,"F","Compliance",COMPLIANCE_1,"Nilai Pengurang",0,"Max -10","negatif"),

    # ------------------------------------------------------------------
    # Screenshot 2
    # ------------------------------------------------------------------
    R(2,"A","Maturity Level Sustainability","Hasil Asesmen Maturity Level Sustainability","%",4,"100%"),
    R(2,"A","Kualitas Penerapan Manajemen Risiko (KPMR)","Penerapan Manajemen Risiko (KPMR) di UB DISYAN","Skor",4,"80%"),
    R(2,"A","Pendapatan Inovatif","Pendapatan dari luar PLN Group (exclude PTL)","Rp Miliar",7,"5"),
    R(2,"A","Pekerjaan Mobil Penerangan","Perburuan Gardu Siap Untuk Penerangan","Gardu",5,"4"),
    R(2,"B","Penguatan Jaringan pada Pelanggan Layanan Khusus","Jumlah Pelanggan Migrasi Layanan Khusus Diamond yang Disetujui oleh Direksi Pembina","Pelanggan",4,"9"),
    R(2,"B","Pengembangan Pelanggan TM dengan pemasaran","Rata-rata Pencapaian Sambungan Pelanggan (PB & UJD) 3 Phasa TM","Hari Kerja",5,"15","negatif"),
    R(2,"B","Pemberagaman Trafo Distribusi (Penomoran)","Realisasi penambahan kapasitas trafo distribusi Penyambungan Baru","Unit",4,"60"),
    R(2,"B","Pembangunan JTM","Realisasi penambahan panjang JTM distribusi","KMS",4,"479.55"),
    R(2,"B","Pembangunan JTR","Realisasi penambahan panjang JTR distribusi","KMS",4,"131"),
    R(2,"B","Evaluasi Jaringan Untuk Kehandalan","Penyelesaian Pekerjaan Evaluasi Jaringan Untuk Keandalan","Pelanggan",5,"22"),
    R(2,"B","Penerbitan RAB Penyambungan - Permohonan Kolektif","Rata-Rata Pencapaian Penerbitan RAB atas Permohonan Penyambungan Pelanggan Kolektif","Hari Kerja",4,"5","negatif"),
    R(2,"B","Penerbitan RAB Penyambungan - Permohonan Non-Kolektif","Rata-rata Pencapaian Penerbitan RAB atas Permohonan PB/UJD Pelanggan Non Kolektif","Hari Kerja",4,"2","negatif"),
    R(2,"B","Buku Standarisasi Konstruksi","Tersedianya Buku Standarisasi Konstruksi yang telah disahkan oleh Pejabat yang Berwenang","Waktu",4,"31 Juni 2026","negatif"),
    R(2,"B","Ketersediaan Material","Tingkat Pemenuhan Stock Minimum Material berdasarkan Standar Stock Minimum yang telah ditetapkan Tahun 2026","%",4,"100%"),
    R(2,"C","Implementasi Sistem Manajemen Terintegrasi",SMT_FORMULA,"%",5,"100%"),
    R(2,"C","Pembangunan Jaringan Mobil Perisai","Dokumen Laporan Pembangunan Jaringan Mobil Perisai yang Disahkan Oleh SM","Lokasi",5,"10"),
    R(2,"D","Pengendalian Penggunaan Anggaran Investasi sesuai RKAP 2026","Kesesuaian Realisasi Anggaran Kas Investasi dengan Pos Anggaran Investasi Sesuai Peruntukannya","%",5,"95 - 100"),
    R(2,"D","Penyerapan Investasi (AI)","Kesesuaian Realisasi Anggaran Investasi Murni 2026 dengan Pos Anggaran Investasi Sesuai Peruntukannya","%",5,"100%"),
    R(2,"D","Penyelesaian Tindak Lanjut defisiensi ICOFR tahun 2025",ICOFR_FORMULA,"%",4,"50%"),
    R(2,"D","Kompensasi Service Level Agreement (SLA) Pelanggan Layanan Khusus Premium","Rupiah Kompensasi Pengurangan Tagihan Rekening Listrik Akibat SLA Tidak Tercapai","Rp Juta",5,"3,202","negatif"),
    R(2,"E","Pengelolaan Human Capital",HC_FORMULA,"%",4,"100%"),
    R(2,"E","Penyelesaian Program Improvement K3L","Penyelesaian Program Improvement K3L sesuai Target x 100 %","%",5,"100%"),
    R(2,"F","Compliance",COMPLIANCE_23,"Nilai Pengurang",0,"Max -10","negatif"),

    # ------------------------------------------------------------------
    # Screenshot 3
    # ------------------------------------------------------------------
    R(3,"A","Optimalisasi Biaya Operasi Pemeliharaan","Kesesuaian Realisasi Biaya Pemeliharaan","%",4,"95 - 100%"),
    R(3,"A","Maturity Level Sustainability","Hasil Assessment Maturity Level Sustainability","%",4,"100%"),
    R(3,"A","Kualitas Penerapan Manajemen Risiko (KPMR)","Penerapan Manajemen Risiko (KPMR)","Skor",4,"82"),
    R(3,"A","Pendapatan Inovatif","Pendapatan dari luar PLN Group (exclude PTL)","Rp Miliar",3,"5"),
    R(3,"B","Pemeliharaan Jaringan FO untuk Paket Distribusi","Tersedianya Gardu Terpilih/Peta Distribusi (Digitalisasi Gardu Distribusi)","Gardu",4,"200"),
    R(3,"B","Key Point Gardu Distribusi (Integrasi SCADA)","Total Integrasi SCADA 107 Gardu","%",4,"100"),
    R(3,"B","Buku Standarisasi Konstruksi","Tersedianya Buku Standarisasi Konstruksi yang telah disahkan oleh Pejabat yang Berwenang","Waktu",3,"30 Juni 2026","negatif"),
    R(3,"B","Program Penurunan ENS dengan Optimasi SCADA","Jumlah Energi yang Tidak Tersalurkan (ENS)","MWh",3,"84.484","negatif"),
    R(3,"B","Yantek Optimization - Respon Time Gangguan","Rata-rata field waktu respon time (pengaduan/penjadwalan)","Menit",3,"35.59","negatif"),
    R(3,"B","Yantek Optimization - Recovery Time Gangguan","Rata-rata 0.95% waktu recovery time gangguan setelah pengaduan","Menit",3,"59","negatif"),
    R(3,"B","Gangguan Penyulang","Kali Penyulang Padam","Kali",5,"11","negatif"),
    R(3,"B","Gangguan Trafo","Kali Trafo Padam","Kali",5,"1","negatif"),
    R(3,"C","SAIDI Distribusi","Σ (Jumlah Lama Padam x Jumlah Pelanggan Padam) / Jumlah Pelanggan Dalam Satu Periode di Wilayah Kerja","Menit/Plg",5,"21.87","negatif"),
    R(3,"C","SAIFI Distribusi","Σ (Kali Padam x Jumlah Pelanggan Padam) / Jumlah Pelanggan Dalam Satu Periode di Wilayah Kerja","Kali/Plg",5,"0.30","negatif"),
    R(3,"C","Susut Distribusi","[(kWh Siap Salur Distribusi - kWh PS - kWh Penjualan) / kWh Siap Salur Distribusi] x 100%","%",4,"3.57","negatif"),
    R(3,"C","Upgrade Kabel","Jumlah Gardu dilakukan Upgrade yang disetujui oleh Pengurus Unit Bisnis","Gardu",3,"20"),
    R(3,"C","Inspeksi Gardu","Laporan Inspeksi Gardu yang direkap oleh SM UBDISYAN","Gardu",3,"Smt 1: 100%; Smt 2: 100%"),
    R(3,"C","Upgrade Gardu Overload","Jumlah Gardu dilakukan Upgrade Overload","Gardu",4,"35"),
    R(3,"C","Upgrade Kubikel Air Insulated (MM6-MG) & Siemens RMU (Gas Insulated Metal)","Jumlah Gardu dilakukan Upgrade yang disetujui oleh Pengurus Unit Bisnis","Gardu",3,"17"),
    R(3,"C","Implementasi Sistem Manajemen Terintegrasi",SMT_FORMULA,"%",4,"100"),
    R(3,"D","Pengendalian Penggunaan Anggaran Investasi sesuai RKAP 2026","Kesesuaian Realisasi Anggaran Kas Investasi dengan Pos Anggaran Investasi Sesuai Peruntukannya","%",4,"95 - 100"),
    R(3,"D","Penyerapan Investasi (AI)","Kesesuaian Realisasi Anggaran Investasi Murni 2026 dengan Pos Anggaran Investasi Sesuai Peruntukannya","%",5,"100%"),
    R(3,"D","Kompensasi Service Level Agreement (SLA) Pelanggan Layanan Khusus Premium","Rupiah Kompensasi Pengurangan Tagihan Rekening Listrik Akibat SLA Tidak Tercapai","Rp Juta",5,"3,282","negatif"),
    R(3,"D","Penyelesaian Tindak Lanjut defisiensi ICOFR tahun 2025",ICOFR_FORMULA,"%",4,"80"),
    R(3,"E","Pengelolaan Human Capital",HC_FORMULA,"%",4,"100"),
    R(3,"E","Penyelesaian Program Improvement K3L","Penyelesaian Program Improvement K3L sesuai Target x 100 %","%",2,"100"),
    R(3,"F","Compliance",COMPLIANCE_23,"Nilai Pengurang",0,"Max -10","negatif"),
]


def norm(value: str | None) -> str:
    value = (value or "").lower().replace("\xa0", " ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def score(row: SourceRow, item: ItemKontrakManajemen, refs: int) -> float:
    a = norm(row.indicator)
    b = norm(item.indikator_kinerja_kunci)
    if not a or not b:
        return -1
    same_section = getattr(item.master_bagian, "kode_bagian", None) == row.section
    # Cross-section reuse is allowed only for an exact KPI name. This repairs
    # old rows that were filed under the wrong A-F section without guessing.
    if not same_section and a != b:
        return -1
    formula_a = norm(row.formula)
    formula_b = norm(item.formula)
    formula_ratio = SequenceMatcher(None, formula_a, formula_b).ratio() if formula_a and formula_b else 0.0
    if a == b:
        s = 100.0
    else:
        ratio = SequenceMatcher(None, a, b).ratio()
        if ratio < 0.72:
            # A renamed KPI may still be the same objective when its formula is
            # strongly equivalent. Restrict this fallback to the same A-F section.
            if same_section and formula_ratio >= 0.72:
                s = 70.0 + (formula_ratio * 20.0)
            else:
                return -1
        else:
            s = ratio * 70
    if formula_a and formula_a == formula_b:
        s += 20
    elif formula_ratio >= 0.90:
        s += 10
    if str(row.target).replace("%", "").strip() == str(item.target or "").replace("%", "").strip():
        s += 5
    if abs(float(row.weight) - float(item.bobot or 0)) < 0.01:
        s += 5
    if same_section:
        s += 5
    if refs:
        s += min(refs, 10) * 0.2
    return s


def source_audit():
    by_source = defaultdict(float)
    by_source_section = defaultdict(float)
    for row in ROWS:
        by_source[row.source] += row.weight
        by_source_section[(row.source, row.section)] += row.weight
    print("SOURCE AUDIT")
    for source in sorted(by_source):
        detail = ", ".join(
            f"{section}={by_source_section[(source, section)]:.2f}"
            for section in SECTIONS
        )
        print(f"  screenshot {source}: rows={sum(r.source == source for r in ROWS)}, bobot={by_source[source]:.2f} [{detail}]")
    print(f"  total imported rows={len(ROWS)}, aggregate bobot={sum(r.weight for r in ROWS):.2f}")


def main(apply: bool):
    source_audit()
    unit = Group.objects.get(name=UNIT_NAME)
    kontrak = KontrakManajemen.objects.filter(tahun=YEAR, unit_bisnis=unit).order_by("id").first()
    if not kontrak:
        raise RuntimeError(f"KM {YEAR} untuk {UNIT_NAME} tidak ditemukan; script ini sengaja tidak membuat KM baru tanpa baseline.")

    template = kontrak.template or MasterTemplateKM.objects.filter(tahun=YEAR).first()
    if not template:
        raise RuntimeError(f"MasterTemplateKM {YEAR} tidak ditemukan.")

    masters = {}
    parts = {}
    for code, name in SECTIONS.items():
        master = MasterBagianKM.objects.filter(template=template, kode_bagian=code).first()
        if not master:
            raise RuntimeError(f"Master bagian {code} tidak ditemukan pada template {template}.")
        masters[code] = master
        part = BagianKontrakManajemen.objects.filter(kontrak=kontrak, kode_bagian=code).first()
        if not part:
            raise RuntimeError(f"Bagian transaksi {code} tidak ditemukan pada {kontrak}.")
        parts[code] = part

    existing = list(
        ItemKontrakManajemen.objects.filter(kontrak=kontrak)
        .select_related("master_bagian", "bagian")
        .annotate(ref_count=Count("reassessment_item"))
    )
    refs_total = sum(int(getattr(x, "ref_count", 0)) for x in existing)
    print(f"BASELINE: KM id={kontrak.id}, judul={kontrak.judul!r}, status={kontrak.status}, items={len(existing)}, refs={refs_total}")
    print("MODE:", "APPLY" if apply else "AUDIT SAJA")
    if not apply:
        print("Tidak ada data diubah. Jalankan kembali dengan --apply setelah audit output.")
        return

    with transaction.atomic():
        kontrak.judul = TITLE
        kontrak.status = "Final"
        kontrak.template = template
        kontrak.save(update_fields=["judul", "status", "template"])

        # Temporarily move all sequence numbers out of the way to avoid unique collisions.
        for item in existing:
            item.no_urut = 10000 + item.id
            item.save(update_fields=["no_urut"])

        unmatched = set(x.id for x in existing)
        by_id = {x.id: x for x in existing}
        next_no = defaultdict(int)
        reused = created = 0

        for row in ROWS:
            next_no[row.section] += 1
            no = next_no[row.section]
            candidates = [by_id[i] for i in unmatched]
            ranked = sorted(
                ((score(row, item, int(getattr(item, "ref_count", 0))), item) for item in candidates),
                key=lambda pair: pair[0],
                reverse=True,
            )
            best_score, item = ranked[0] if ranked else (-1, None)
            if item is not None and best_score >= 68:
                unmatched.remove(item.id)
                reused += 1
            else:
                item = ItemKontrakManajemen(kontrak=kontrak)
                created += 1

            item.master_bagian = masters[row.section]
            item.bagian = parts[row.section]
            item.no_urut = no
            item.indikator_kinerja_kunci = row.indicator
            item.formula = row.formula
            item.satuan = row.unit
            item.bobot = row.weight
            item.target = row.target
            item.polaritas = row.polarity
            item.save()

        deleted = retained_legacy = 0
        for item_id in sorted(unmatched):
            item = by_id[item_id]
            refs = int(getattr(item, "ref_count", 0))
            if refs == 0:
                item.delete()
                deleted += 1
                continue
            code = item.master_bagian.kode_bagian
            next_no[code] += 1
            item.no_urut = next_no[code]
            item.bagian = parts[code]
            item.save(update_fields=["no_urut", "bagian"])
            retained_legacy += 1
            print(f"  LEGACY REFERENCED retained: id={item.id} refs={refs} {code}.{item.no_urut} {item.indikator_kinerja_kunci!r}")

        final_items = ItemKontrakManajemen.objects.filter(kontrak=kontrak).count()
        final_refs = ReAssessmentItem.objects.filter(km_item__kontrak=kontrak).count()
        if final_refs != refs_total:
            raise RuntimeError(f"FK safety failed: refs before={refs_total}, after={final_refs}")

        print("APPLY OK")
        print(f"  reused={reused}, created={created}, deleted_unreferenced={deleted}, legacy_referenced={retained_legacy}")
        print(f"  final items={final_items}, refs preserved={final_refs}")
        for code in SECTIONS:
            qs = ItemKontrakManajemen.objects.filter(kontrak=kontrak, master_bagian=masters[code])
            print(f"  {code}: items={qs.count()}, bobot={sum(float(x.bobot or 0) for x in qs):.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply import; default is read-only audit.")
    args = parser.parse_args()
    main(args.apply)
