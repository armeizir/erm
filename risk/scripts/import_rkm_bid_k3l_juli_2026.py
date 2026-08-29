"""Import KM prerequisite + RKM BID K3L Juli 2026 from approved PDF.

Source:
    01. KM K3LKAM dan RKM Juli 2026.pdf
    - page 1: Kontrak Manajemen 2026 VP K3L
    - page 2: Rencana Kerja Tahun 2026 Bidang K3L, Jul-26

Safe default (read-only audit):
    python risk/scripts/import_rkm_bid_k3l_juli_2026.py

Apply:
    python risk/scripts/import_rkm_bid_k3l_juli_2026.py --apply

Production example (after loading the same environment file used by erm.service):
    DJANGO_SETTINGS_MODULE=riskproject.settings.prod \
      python risk/scripts/import_rkm_bid_k3l_juli_2026.py

Design rules:
- Ensures unit Group "BID K3L" exists.
- Ensures one 2026 KM for BID K3L, conventionally titled "VPK3L".
- Seeds/updates the 9 KM KPI rows from page 1 without deleting unrelated existing rows.
- Creates/updates RKM Juli 2026 with only the 6 KPI rows shown on page 2
  (source numbers 1, 2, 4, 5, 6, 8).
- Existing RKM rows not present in the PDF are retained; the importer never deletes
  existing production RKM data.
- Source achievement percentages are preserved exactly. This is important because
  RKMItem.save() derives achievement from numeric target/actual and would otherwise
  replace values such as 74.85%, 100%, and 110% from the signed source document.
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
UNIT_NAME = "BID K3L"
KM_TITLE = "VPK3L"
RKM_TITLE = "RKM BID K3L Juli 2026"

SECTIONS = {
    "A": "Nilai Ekonomi dan Sosial Untuk Indonesia",
    "B": "Inovasi Model Bisnis",
    "C": "Kepemimpinan Teknologi",
    "D": "Peningkatan Investasi",
    "E": "Pengembangan Talenta",
    "F": "Kepatuhan",
}

SMT_FORMULA = """Prosentase Rata-rata Waktu Pemenuhan Eviden di tanggal 30 September 2026:
1. Maturity ISO 14001 Sistem Manajemen Lingkungan Level 3
2. Maturity ISO 45001 Sistem Manajemen Keselamatan dan Kesehatan Kerja (K3) Level 3
3. Maturity Perpol 7/2019 Sistem Manajemen Pengamanan Level 2
4. Maturity PP50/2012 Kemenaker Sistem Manajemen Keselamatan dan Kesehatan Kerja (SMK3) Level 3"""

HC_FORMULA = """Rata-rata Pencapaian:
1. Produktivitas Pegawai dan Penguatan Budaya
2. Pengelolaan Human Capital Services"""

COMPLIANCE_FORMULA = """Jumlah nilai pengurang dari unsur:
- Maturity Level GCG
- Kepatuhan pengelolaan HSSE
- Tindak lanjut temuan SPI, BPK, dan Auditor lainnya
- Keterlambatan Laporan Kinerja (termasuk laporan manajemen risiko)
- Planning Accuracy Compliance Adjustment (PACA)"""


@dataclass(frozen=True)
class KMRow:
    section: str
    section_no: int
    indicator: str
    formula: str
    unit: str
    weight: float
    target: str
    polarity: str = "positif"


KM_ROWS = [
    KMRow("A", 1, "Optimalisasi Biaya Pemeliharaan", "Realisasi Optimalisasi Biaya Pemeliharaan K3L", "%", 10, "95 - 100%"),
    KMRow("A", 2, "Maturity Level Sustainability", "Hasil Asesmen Maturity Level Sustainability", "Level", 15, "3.10"),
    KMRow("A", 3, "Kualitas Penerapan Manajemen Risiko (KPMR)", "Penerapan Manajemen Risiko (KPMR) di Bidang K3L", "Skor", 12, "80"),
    KMRow("B", 1, "Implementasi Sistem Manajemen Terintegrasi", SMT_FORMULA, "%", 10, "100"),
    KMRow("C", 1, "Penguatan K3L pada Level Mitra Kerja: Mengidentifikasi Kondisi Bahaya Tempat Kerja/Aset di Area Proyek", "Tersedianya Laporan Unsafe Action dan/atau Unsafe Condition di Lokasi Area Proyek RUPTL Beserta Rekomendasi Atas Temuan per-Semester", "%", 14, "100"),
    KMRow("D", 1, "Penyelesaian Program Improvement K3L", "Penyelesaian Program Improvement K3L sesuai Target x 100%", "%", 12, "100"),
    KMRow("E", 1, "Pengelolaan Human Capital", HC_FORMULA, "%", 12, "100"),
    KMRow("E", 2, "Pengelolaan Safety Culture", "Lost Time Injury Frequency Rate", "Indeks", 15, "0,332 indeks (per 1 juta jam kerja)", "negatif"),
    KMRow("F", 1, "Compliance", COMPLIANCE_FORMULA, "Nilai Pengurang", 0, "Max -10", "negatif"),
]

SUSTAINABILITY_PROGRAM = """Melakukan upaya penilaian Matlev Sustainability PLN Batam dengan:
1. Environmental Management
1.1. Pengelolaan Limbah Padat Domestik
1.2. Pemanfaatan Limbah FABA
1.3. Pengelolaan Limbah B3
1.4. Pengelolaan Limbah Cair
1.5. Pengurangan Emisi Non-GRK
1.6. Sertifikasi Sistem Manajemen Lingkungan
2. Water Stewardship
2.1. Program Efisiensi Penggunaan Air
2.2. Program Pengelolaan Risiko Fisik Air
3. Climate Change Management
3.1.1. Climate Click
3.2.1. APPLE-GATRIK
3.2.2. Perdagangan Emisi
3.3. Aksi Adaptasi Perubahan Iklim
3.4. Offset Emisi
4. Land Use and Biodiversity
4.1. Pengelolaan Biodiversity dan Penutupan Lahan"""

IMPROVEMENT_PROGRAM = """Penyelesaian Program Improvement K3L sebagai upaya untuk menurunkan tingkat risiko kecelakaan kerja, meningkatkan kepedulian pekerja, serta memastikan kepatuhan terhadap peraturan perundang-undangan.
Program Improvement: K3L:
1. PROGRAM KERJA DAN ANGGARAN
2. IMPLEMENTASI APLIKASI INSPEKTA
3. INSPEKSI K3L DAN KEAMANAN LAPANGAN
4. KETEPATAN WAKTU PELAPORAN
5. PENANGGULANGAN KEBAKARAN
6. KEPATUHAN SMK2 DAN SMK3
7. IMPLEMENTASI 5R/5S
8. PEMENUHAN DOKUMEN LINGKUNGAN DAN IZIN LINGKUNGAN/PERSETUJUAN LINGKUNGAN
9. PENGENDALIAN PENCEMARAN AIR
10. PENGENDALIAN PENCEMARAN UDARA
11. PENGELOLAAN LIMBAH B3
12. PENGELOLAAN B3
13. PENGENDALIAN KOMITMEN MANAJEMEN PENGAMANAN
14. POLA PENGAMANAN"""


@dataclass(frozen=True)
class RKMSourceRow:
    source_no: int
    section: str
    km_indicator: str
    target: str
    initiative: str
    program: str
    action: str
    target_july: str
    actual_july: str
    achievement: Decimal
    note: str = ""
    target_unit: str = ""


RKM_ROWS = [
    RKMSourceRow(
        1,
        "A",
        "Optimalisasi Biaya Pemeliharaan",
        "95-100%",
        "Peningkatan biaya Bidang K3LKAM melalui pengendalian anggaran dan optimalisasi anggaran",
        "Melaksanakan pengendalian biaya K3LKAM secara berkala, evaluasi realisasi anggaran, serta optimalisasi penggunaan sumber anggaran Bidang K3LKAM",
        "1. Monitoring realisasi biaya setiap bulan.\n2. Evaluasi deviasi biaya terhadap Pagu Anggaran.\n3. Optimalisasi penggunaan biaya dari anggaran K3LKAM.",
        "14,635,524,374",
        "10,480,058,420",
        Decimal("74.85"),
        "Pencapaian Bulan Juli adalah estimasi realisasi AO K3L per bulan juli. Perhitungan Final di akhir tahun 2026",
        "Rp",
    ),
    RKMSourceRow(
        2,
        "A",
        "Maturity Level Sustainability",
        "3.1",
        "Rekapulasi Penilaian Matlev Sustainability PLN Batam tahun 2026",
        SUSTAINABILITY_PROGRAM,
        "Melakukan Penyelesaian Rekapulasi Penilaian Matlev Sustainability PLN Batam tahun 2026",
        "-",
        "-",
        Decimal("100.00"),
        "Realisasi semester I tahun 2026 sebesar 3.07 dari target 2.70. Target semester II tahun 2026 sebesar 3.10",
    ),
    RKMSourceRow(
        4,
        "B",
        "Implementasi Sistem Manajemen Terintegrasi",
        "1",
        "Presentase Rata-rata Waktu Pemenuhan Eviden di tanggal 30 September 2026:",
        SMT_FORMULA,
        "Target pemenuhan eviden minggu ke 2 Agustus 2026",
        "0",
        "0",
        Decimal("100.00"),
        "Kelengkapan dokumen maksimal pada tanggal 30 september 2026",
    ),
    RKMSourceRow(
        5,
        "C",
        "Penguatan K3L pada Level Mitra Kerja: Mengidentifikasi Kondisi Bahaya Tempat Kerja/Aset di Area Proyek",
        "100%",
        "Laporan Unsafe Action dan/atau Unsafe Condition di Lokasi Area Proyek RUPTL Beserta Rekomendasi Atas Temuan per-Semester",
        "Tersedianya Laporan Unsafe Action dan/atau Unsafe Condition di Lokasi Area Proyek RUPTL Beserta Rekomendasi Atas Temuan per-Semester",
        "Melakukan Penyelesaian Laporan Unsafe Action dan/atau Unsafe Condition di Lokasi Area Proyek RUPTL Beserta Rekomendasi Atas Temuan per-Semester",
        "0",
        "0",
        Decimal("100.00"),
        "Target semester II sebanyak 8 proyek RUPTL",
    ),
    RKMSourceRow(
        6,
        "D",
        "Penyelesaian Program Improvement K3L",
        "100%",
        "Implementasi Penyelesaian Program Improvement K3L",
        IMPROVEMENT_PROGRAM,
        "Melakukan Penyelesaian Program Improvement K3L untuk penilaian per Semester",
        "0.00",
        "0.00",
        Decimal("100.00"),
        "Monitoring program semester II setiap bulan pada setiap Unit",
    ),
    RKMSourceRow(
        8,
        "E",
        "Pengelolaan Safety Culture",
        "Indeks (per 1 juta jam kerja)",
        "Melakukan upaya pencegahan kecelakaan kerja yang menyebabkan kehilangan jam kerja.",
        "Melakukan upaya pencegahan Kecelakaan Kerja dengan: Penyelesaian Program Improvement K3L",
        "Melakukan Pelaporan LTIF Setiap Bulan",
        "0.38",
        "0.000",
        Decimal("110.00"),
        "",
        "Indeks",
    ),
]


def norm(value: str | None) -> str:
    value = (value or "").lower().replace("\xa0", " ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def find_group():
    return Group.objects.filter(name__iexact=UNIT_NAME).order_by("id").first()


def find_contract(unit):
    if not unit:
        return None
    qs = KontrakManajemen.objects.filter(tahun=YEAR, unit_bisnis=unit).order_by("id")
    exact = qs.filter(judul__iexact=KM_TITLE).first()
    if exact:
        return exact
    k3 = [x for x in qs if "k3l" in norm(x.judul)]
    if len(k3) == 1:
        return k3[0]
    if qs.count() == 1:
        return qs.first()
    return None


def find_km_item(kontrak, section: str, indicator: str):
    if not kontrak:
        return None
    target = norm(indicator)
    candidates = list(
        ItemKontrakManajemen.objects.filter(
            kontrak=kontrak,
            master_bagian__kode_bagian=section,
        ).select_related("master_bagian")
    )
    for item in candidates:
        if norm(item.indikator_kinerja_kunci) == target:
            return item
    # Conservative aliases for source wording.
    if "safety culture" in target:
        for item in candidates:
            text = norm(item.indikator_kinerja_kunci) + " " + norm(item.formula)
            if "lost time injury frequency rate" in text or "safety culture" in text:
                return item
    return None


def source_audit():
    print("SOURCE AUDIT")
    print(f"  KM page 1: items={len(KM_ROWS)}, bobot={sum(x.weight for x in KM_ROWS):.2f}")
    by_section = {code: 0 for code in SECTIONS}
    for row in KM_ROWS:
        by_section[row.section] += row.weight
    print("  KM bobot per bagian: " + ", ".join(f"{k}={v:.2f}" for k, v in by_section.items()))
    print(f"  RKM page 2: rows={len(RKM_ROWS)}, source_no={[x.source_no for x in RKM_ROWS]}")
    print("  RKM Juli values:")
    for row in RKM_ROWS:
        print(
            f"    {row.source_no}. {row.km_indicator}: target={row.target_july!r}, "
            f"realisasi={row.actual_july!r}, capaian={row.achievement}%"
        )


def audit_baseline():
    unit = find_group()
    kontrak = find_contract(unit)
    summary = None
    if unit and kontrak:
        summary = RKMSummary.objects.filter(
            tahun=YEAR,
            bulan=MONTH,
            unit_bisnis=unit,
            kontrak_manajemen=kontrak,
        ).order_by("id").first()
    print("BASELINE")
    print(f"  unit: {'FOUND id=' + str(unit.id) if unit else 'MISSING -> will create ' + UNIT_NAME}")
    if kontrak:
        print(
            f"  KM: FOUND id={kontrak.id}, judul={kontrak.judul!r}, status={kontrak.status}, "
            f"items={ItemKontrakManajemen.objects.filter(kontrak=kontrak).count()}"
        )
    else:
        print(f"  KM: MISSING -> will create {KM_TITLE} / {YEAR}")
    if summary:
        print(
            f"  RKM: FOUND id={summary.id}, judul={summary.judul!r}, status={summary.status}, "
            f"items={RKMItem.objects.filter(summary=summary).count()}"
        )
        source_km_ids = set()
        if kontrak:
            for src in RKM_ROWS:
                item = find_km_item(kontrak, src.section, src.km_indicator)
                if item:
                    source_km_ids.add(item.id)
        extras = RKMItem.objects.filter(summary=summary).exclude(km_item_id__in=source_km_ids).count()
        if extras:
            print(f"  existing RKM items not represented by PDF: {extras} (will be retained)")
    else:
        print(f"  RKM: MISSING -> will create {RKM_TITLE}")


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
        changed = False
        if master.nama_bagian != name:
            master.nama_bagian = name
            changed = True
        if master.urutan != order:
            master.urutan = order
            changed = True
        if changed:
            master.save(update_fields=["nama_bagian", "urutan"])
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
        updates = []
        if kontrak.judul != KM_TITLE:
            kontrak.judul = KM_TITLE
            updates.append("judul")
        if kontrak.template_id != template.id:
            kontrak.template = template
            updates.append("template")
        if kontrak.status != "Final":
            kontrak.status = "Final"
            updates.append("status")
        if updates:
            kontrak.save(update_fields=updates)

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
    updated = 0
    for row in KM_ROWS:
        item = find_km_item(kontrak, row.section, row.indicator)
        if item is None:
            desired = row.section_no
            occupied = ItemKontrakManajemen.objects.filter(
                kontrak=kontrak,
                master_bagian=masters[row.section],
                no_urut=desired,
            ).exists()
            if occupied:
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
            updated += 1

        item.master_bagian = masters[row.section]
        item.bagian = parts[row.section]
        item.indikator_kinerja_kunci = row.indicator
        item.formula = row.formula
        item.satuan = row.unit
        item.bobot = row.weight
        item.target = row.target
        item.polaritas = row.polarity
        item.save()
        result[(row.section, norm(row.indicator))] = item

    return result, created, updated


def resolve_source_km_item(km_items, src: RKMSourceRow):
    key = (src.section, norm(src.km_indicator))
    item = km_items.get(key)
    if item:
        return item
    for (section, indicator), candidate in km_items.items():
        if section != src.section:
            continue
        if "safety culture" in norm(src.km_indicator) and (
            "safety culture" in indicator or "lost time injury frequency rate" in norm(candidate.formula)
        ):
            return candidate
    raise RuntimeError(f"KM item tidak ditemukan untuk RKM source no {src.source_no}: {src.km_indicator}")


def apply_import():
    with transaction.atomic():
        unit, _template, masters, kontrak, parts = ensure_structure()
        km_items, km_created, km_updated = ensure_km_items(kontrak, masters, parts)

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
                status="Draft",
                pic=UNIT_NAME,
            )
            summary_created = True
        else:
            updates = []
            if summary.judul != RKM_TITLE:
                summary.judul = RKM_TITLE
                updates.append("judul")
            if summary.tanggal_mulai is None:
                summary.tanggal_mulai = date(YEAR, MONTH, 1)
                updates.append("tanggal_mulai")
            if summary.tanggal_selesai is None:
                summary.tanggal_selesai = date(YEAR, MONTH, 31)
                updates.append("tanggal_selesai")
            if not summary.pic:
                summary.pic = UNIT_NAME
                updates.append("pic")
            if updates:
                summary.save(update_fields=updates)

        imported_ids = []
        for src in RKM_ROWS:
            km_item = resolve_source_km_item(km_items, src)
            existing = RKMItem.objects.filter(summary=summary, km_item=km_item).first()
            conflict = RKMItem.objects.filter(summary=summary, no_item=src.source_no).exclude(km_item=km_item).first()
            if conflict:
                raise RuntimeError(
                    f"Konflik no_item={src.source_no}: sudah digunakan RKMItem id={conflict.id} "
                    f"untuk KPI {conflict.kpi_indikator!r}. Tidak ada data yang dihapus."
                )

            defaults = {
                "no_item": src.source_no,
                "kategori_rkm": src.section,
                "sasaran": km_item.indikator_kinerja_kunci,
                "kpi_indikator": km_item.indikator_kinerja_kunci,
                "kpi_satuan": km_item.satuan,
                "kpi_target": src.target,
                "inisiatif_strategis": src.initiative,
                "program_kerja_utama": src.program,
                "rencana_aksi": src.action,
                "target_akumulasi": src.target_july,
                "target_akumulasi_satuan": src.target_unit or km_item.satuan,
                "target_juli": src.target_july,
                "realisasi_juli": src.actual_july,
                "target_bulanan": (
                    f"Juli 2026 target: {src.target_unit + ' ' if src.target_unit else ''}{src.target_july}"
                ).strip(),
                "realisasi": (
                    f"Juli 2026 realisasi: {src.target_unit + ' ' if src.target_unit else ''}{src.actual_july}"
                ).strip(),
                "deviasi": f"Capaian Juli 2026 sesuai dokumen: {src.achievement}%",
                "pic_rkm": UNIT_NAME,
                "keterangan": src.note,
            }

            if existing:
                for field, value in defaults.items():
                    setattr(existing, field, value)
                existing.save()
                item = existing
            else:
                item = RKMItem.objects.create(summary=summary, km_item=km_item, **defaults)

            # Preserve signed/documented source achievement. Model.save() recalculates
            # from target/actual and is not equivalent to the source's business formula.
            RKMItem.objects.filter(pk=item.pk).update(
                persen_capaian=src.achievement,
                jumlah_realisasi=src.actual_july,
            )
            imported_ids.append(item.id)

        extras = RKMItem.objects.filter(summary=summary).exclude(id__in=imported_ids).count()

        print("APPLY OK")
        print(f"  unit={unit.id} {unit.name}")
        print(f"  KM={kontrak.id} {kontrak.judul}; source KM items created={km_created}, updated/reused={km_updated}")
        print(
            f"  RKM={summary.id} {summary.judul}; created={summary_created}; "
            f"source rows imported/updated={len(imported_ids)}"
        )
        print(f"  existing RKM rows outside source retained={extras}")
        print("  imported source numbers: " + ", ".join(str(x.source_no) for x in RKM_ROWS))
        for src in RKM_ROWS:
            item = RKMItem.objects.get(summary=summary, no_item=src.source_no)
            print(
                f"    {src.source_no}: RKMItem id={item.id}; target Juli={item.target_juli!r}; "
                f"realisasi Juli={item.realisasi_juli!r}; capaian={item.persen_capaian}%"
            )


def main(apply: bool):
    source_audit()
    audit_baseline()
    if not apply:
        print("MODE: AUDIT SAJA")
        print("Tidak ada data diubah. Jalankan kembali dengan --apply setelah audit output diperiksa.")
        return
    print("MODE: APPLY")
    apply_import()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply KM prerequisite and RKM Juli 2026 import")
    args = parser.parse_args()
    main(args.apply)
