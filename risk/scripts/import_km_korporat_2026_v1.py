#!/usr/bin/env python3
"""
IMPORT KM KORPORAT 2026 V1

Default = DRY-RUN.
Apply:
    python risk/scripts/import_km_korporat_2026_v1.py --apply

Prasyarat:
- patch_km_korporat_module_v1.py sudah diterapkan;
- migration field esg_kategori dan proxy model sudah di-migrate.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.prod")

import django
django.setup()

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import transaction

from risk.models import (
    BagianKontrakManajemen,
    ItemKontrakManajemen,
    KontrakManajemen,
    MasterBagianKM,
    MasterTemplateKM,
)

YEAR = 2026
CORPORATE_GROUP = "KORPORAT"
KM_TITLE = "KM Korporat 2026"

SECTIONS = {
    "A": ("Nilai Ekonomi dan Sosial Untuk Indonesia", Decimal("60")),
    "B": ("Inovasi Model Bisnis", Decimal("10")),
    "C": ("Kepemimpinan Teknologi", Decimal("10")),
    "D": ("Peningkatan Investasi", Decimal("10")),
    "E": ("Pengembangan Talenta", Decimal("10")),
    "F": ("Kepatuhan", Decimal("0")),
}


@dataclass(frozen=True)
class Row:
    no: int
    section: str
    indicator: str
    formula: str
    esg: str
    unit: str
    weight: Decimal
    target: str
    polarity: str


ROWS = [
    Row(
        1, "A", "EBIT",
        "Laba (Rugi) Usaha + Laba Asosiasi dan Ventura Bersama + "
        "Laba (Rugi) Selisih Kurs",
        "C", "Rp. Miliar", Decimal("12"),
        "Sesuai RKAP yang berlaku hasil RUPS RKAP 2026",
        "positif",
    ),
    Row(
        2, "A",
        "Efisiensi Biaya dan Konsumsi Energi Pembangkit Non-MPP",
        "Rata-rata Pencapaian dari:\n"
        "1. BPP Non MPP\n"
        "2. SFC Gas Non MPP",
        "C", "%", Decimal("12"),
        "100% sesuai ketentuan:\n"
        "1. Sesuai RKAP yang berlaku hasil RUPS RKAP 2026\n"
        "2. 8.943,065 BTU/kWh",
        "positif",
    ),
    Row(
        3, "A",
        "Pendapatan Penjualan Tenaga Listrik",
        "Pendapatan Penjualan Tenaga Listrik sesuai TUL 309 PLN Batam",
        "C", "Rp. Miliar", Decimal("10"),
        "7.951,21",
        "positif",
    ),
    Row(
        4, "A",
        "Reliabilitas Sistem Kelistrikan",
        "Rata-rata Pencapaian dari:\n"
        "1. EAF MPP dan Non MPP\n"
        "2. EFOR MPP dan Non MPP\n"
        "3. Optimalisasi Kesiapan Pasokan Pembangkit\n"
        "5. SAIDI\n"
        "6. SAIFI",
        "S", "%", Decimal("16"),
        "100% sesuai ketentuan:\n"
        "1. 91,11%\n"
        "2. 9,86%\n"
        "3. 85,62%\n"
        "4. 130,24 menit/pelanggan\n"
        "5. 2,45 kali/pelanggan",
        "positif",
    ),
    Row(
        5, "A",
        "Advancing in Sustainable Development Goals (SDGs)",
        "Rata-rata pencapaian program:\n"
        "1. Maturity Level Sustainability\n"
        "2. Pengelolaan Komunikasi & TJSL\n"
        "3. Kualitas Penerapan Manajemen Risiko (KPMR)\n"
        "4. Skor Maturitas SPI",
        "G", "%", Decimal("10"),
        "100% sesuai ketentuan:\n"
        "1. Level 3,1\n"
        "2. 100%\n"
        "3. Skor 80\n"
        "4. Skor 3,15",
        "positif",
    ),
    Row(
        6, "B",
        "Pendapatan Inovatif, Laba Asosiasi, Dividend dan Sinergi",
        "Rata-rata pencapaian:\n"
        "1. Pendapatan Inovatif\n"
        "2. Laba Asosiasi\n"
        "3. Cash Dividend dari JVC\n"
        "4. Sinergi antar SHAP Lain & Pusharlis",
        "C", "%", Decimal("10"),
        "100% sesuai ketentuan:\n"
        "1. Rp 44,72 Miliar\n"
        "2. Rp 23,11 Miliar\n"
        "3. Rp 16,13 Miliar\n"
        "4. Rp 321,40 Miliar",
        "positif",
    ),
    Row(
        7, "C",
        "Electricity Losses",
        "[(kWh siap salur – kWh PS – kWh penjualan) / kWh Siap Salur] x 100%",
        "E", "%", Decimal("10"),
        "3,35",
        "negatif",
    ),
    Row(
        8, "D",
        "Penyelesaian Proyek RUPTL, Moonshot's Cluster, dan Penugasan",
        "Rata-rata pencapaian:\n"
        "1. Penyelesaian Proyek EPC & Non EPC\n"
        "2. Moonshot’s Cluster\n"
        "3. Penyelesaian Tarif Tenaga Listrik (TTL) Baru",
        "C", "%", Decimal("10"),
        "100",
        "positif",
    ),
    Row(
        9, "E",
        "Pengelolaan Human Capital dan Safety Culture",
        "Rata-rata pencapaian:\n"
        "1. Talent Management\n"
        "2. Produktivitas Pegawai dan Penguatan Budaya\n"
        "3. Pengelolaan Human Capital Services\n"
        "4. Lost Time Injury Frequency Rate",
        "S", "%", Decimal("10"),
        "100% sesuai ketentuan:\n"
        "1. 100%\n"
        "2. 100%\n"
        "3. 100%\n"
        "4. 0,332 indeks (per 1 juta jam kerja)",
        "positif",
    ),
    Row(
        10, "F",
        "Compliance (GCG, Kepatuhan HSSE, Auditor, Reporting, Budget Alignment, "
        "PACA, Critical Event, NAC)",
        "Jumlah nilai pengurang dari unsur:\n"
        "- Maturity Level GCG\n"
        "- Kepatuhan Pengelolaan HSSE\n"
        "- Tindak lanjut temuan SPI, BPK, dan Auditor lainnya\n"
        "- Keterlambatan Laporan Kinerja (termasuk laporan manajemen risiko)\n"
        "- Penyelesaian dan Penyampaian Laporan Keuangan Audit Tahun 2025\n"
        "- Ketidaksesuaian pengembangan bisnis dengan Corporate Charter\n"
        "- Planning Accuracy Compliance Adjustment (PACA)\n"
        "- Critical Event\n"
        "- Pengendalian Nilai Non Allowable Cost/NAC sesuai RKAP 2026",
        "G", "Nilai Pengurang", Decimal("0"),
        "Max -10",
        "negatif",
    ),
]


def banner(title: str) -> None:
    print()
    print("=" * 140)
    print(title)
    print("=" * 140)


def model_preflight() -> None:
    names = {f.name for f in ItemKontrakManajemen._meta.fields}
    if "esg_kategori" not in names:
        raise RuntimeError(
            "STOP: field ItemKontrakManajemen.esg_kategori belum tersedia. "
            "Terapkan patch module + migration terlebih dahulu."
        )


def source_audit() -> None:
    banner("SOURCE AUDIT - KM KORPORAT 2026")
    subtotal = {}
    for row in ROWS:
        subtotal[row.section] = subtotal.get(row.section, Decimal("0")) + row.weight
        print(
            f"{row.no:02d} | {row.section} | ESG={row.esg} | "
            f"bobot={row.weight:<3} | target={row.target!r} | {row.indicator}"
        )

    print("-" * 140)
    for code in "ABCDEF":
        actual = subtotal.get(code, Decimal("0"))
        expected = SECTIONS[code][1]
        print(f"Bagian {code}: bobot={actual} | expected={expected}")
        if actual != expected:
            raise RuntimeError(
                f"STOP: subtotal bagian {code}={actual}, expected={expected}"
            )

    total = sum(subtotal.values(), Decimal("0"))
    print("TOTAL BOBOT REGULER:", total)
    if total != Decimal("100"):
        raise RuntimeError(f"STOP: total bobot={total}, expected=100")

    print()
    print(
        "CATATAN COMPLIANCE: source menampilkan 'Max - 10' pada kolom BOBOT. "
        "Di canonical DB disimpan sebagai bobot=0 dan target='Max -10' "
        "karena merupakan nilai pengurang/deduction cap."
    )


def find_state():
    group = Group.objects.filter(name__iexact=CORPORATE_GROUP).order_by("pk").first()
    contracts = KontrakManajemen.objects.none()
    if group:
        contracts = KontrakManajemen.objects.filter(
            tahun=YEAR, unit_bisnis=group
        ).order_by("pk")

    banner("PRODUCTION BASELINE")
    if group:
        print(f"Group corporate: FOUND id={group.pk} | name={group.name!r}")
    else:
        print(f"Group corporate: MISSING -> akan dibuat {CORPORATE_GROUP!r}")

    if not group or not contracts.exists():
        print(f"KM corporate    : MISSING -> akan dibuat {KM_TITLE!r}")
        return group, None

    exact = contracts.filter(judul=KM_TITLE)
    if exact.count() == 1:
        km = exact.first()
    elif exact.count() > 1:
        raise RuntimeError(
            f"STOP: lebih dari satu {KM_TITLE!r}: "
            f"{list(exact.values_list('id', 'judul'))}"
        )
    elif contracts.count() == 1:
        km = contracts.first()
        raise RuntimeError(
            "STOP: Group KORPORAT sudah memiliki KM 2026 dengan judul berbeda: "
            f"id={km.pk} judul={km.judul!r}. Review manual sebelum import."
        )
    else:
        raise RuntimeError(
            "STOP: Group KORPORAT memiliki beberapa KM 2026 dan tidak ada exact title "
            f"{KM_TITLE!r}: {list(contracts.values_list('id','judul'))}"
        )

    items = list(
        ItemKontrakManajemen.objects
        .filter(kontrak=km)
        .select_related("master_bagian")
        .order_by("no_urut", "pk")
    )
    print(
        f"KM corporate    : FOUND id={km.pk} | judul={km.judul!r} | "
        f"status={km.status!r} | items={len(items)}"
    )
    for x in items:
        print(
            f"  item={x.pk:<4} no={x.no_urut:<2} "
            f"bagian={getattr(x.master_bagian,'kode_bagian',None)} "
            f"ESG={getattr(x,'esg_kategori','')!r} bobot={x.bobot!r} "
            f"| {x.indikator_kinerja_kunci}"
        )
    return group, km


def exact_existing_matches_source(km) -> bool:
    items = list(
        ItemKontrakManajemen.objects
        .filter(kontrak=km)
        .select_related("master_bagian")
        .order_by("no_urut", "pk")
    )
    if len(items) != len(ROWS):
        return False

    by_no = {x.no_urut: x for x in items}
    if len(by_no) != len(ROWS):
        return False

    for row in ROWS:
        x = by_no.get(row.no)
        if x is None:
            return False
        if getattr(x.master_bagian, "kode_bagian", None) != row.section:
            return False
        if x.indikator_kinerja_kunci != row.indicator:
            return False
        if (x.formula or "") != row.formula:
            return False
        if (x.satuan or "") != row.unit:
            return False
        if Decimal(str(x.bobot or 0)) != row.weight:
            return False
        if (x.target or "") != row.target:
            return False
        if (getattr(x, "esg_kategori", "") or "") != row.esg:
            return False
        if (x.polaritas or "") != row.polarity:
            return False
    return True


def backup_sqlite() -> Path:
    engine = settings.DATABASES["default"]["ENGINE"]
    if "sqlite3" not in engine:
        raise RuntimeError(
            f"STOP: importer V1 hanya mengotomasi backup SQLite; engine={engine!r}"
        )

    source = Path(settings.DATABASES["default"]["NAME"])
    if not source.exists():
        raise RuntimeError(f"STOP: DB SQLite tidak ditemukan: {source}")

    backup_dir = ROOT / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"db_before_km_korporat_{stamp}.sqlite3"

    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()

    check = sqlite3.connect(str(target))
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()

    if integrity != "ok":
        raise RuntimeError(
            f"STOP: backup SQLite integrity_check={integrity!r}"
        )

    print(f"BACKUP SQLITE: {target}")
    return target


def ensure_structure():
    group, _ = Group.objects.get_or_create(name=CORPORATE_GROUP)

    template = (
        MasterTemplateKM.objects.filter(tahun=YEAR).order_by("pk").first()
    )
    if template is None:
        template = MasterTemplateKM.objects.create(
            tahun=YEAR,
            nama=f"Bagian KM {YEAR}",
        )

    masters = {}
    for order, code in enumerate("ABCDEF", start=1):
        name, _expected_weight = SECTIONS[code]
        master, created = MasterBagianKM.objects.get_or_create(
            template=template,
            kode_bagian=code,
            defaults={
                "nama_bagian": name,
                "urutan": order,
            },
        )
        if not created and master.nama_bagian != name:
            raise RuntimeError(
                f"STOP: MasterBagian {code} existing bernama "
                f"{master.nama_bagian!r}, source mengharapkan {name!r}."
            )
        masters[code] = master

    exact = KontrakManajemen.objects.filter(
        tahun=YEAR,
        unit_bisnis=group,
        judul=KM_TITLE,
    )
    if exact.count() > 1:
        raise RuntimeError(
            f"STOP: duplicate KM corporate exact: "
            f"{list(exact.values_list('pk','judul'))}"
        )

    if exact.exists():
        km = exact.get()
    else:
        other = KontrakManajemen.objects.filter(
            tahun=YEAR, unit_bisnis=group
        )
        if other.exists():
            raise RuntimeError(
                "STOP: sudah ada KM lain pada Group KORPORAT tahun 2026: "
                f"{list(other.values_list('pk','judul'))}"
            )
        km = KontrakManajemen.objects.create(
            judul=KM_TITLE,
            tahun=YEAR,
            unit_bisnis=group,
            status="Final",
            template=template,
        )

    if km.template_id != template.pk:
        raise RuntimeError(
            f"STOP: KM corporate existing memakai template_id={km.template_id}, "
            f"expected={template.pk}."
        )

    parts = {}
    for code, (name, _weight) in SECTIONS.items():
        part, created = BagianKontrakManajemen.objects.get_or_create(
            kontrak=km,
            kode_bagian=code,
            defaults={"nama_bagian": name},
        )
        if not created and part.nama_bagian != name:
            raise RuntimeError(
                f"STOP: BagianKontrak {code} bernama {part.nama_bagian!r}, "
                f"source={name!r}."
            )
        parts[code] = part

    return group, template, masters, km, parts


def create_items(km, masters, parts):
    existing = list(
        ItemKontrakManajemen.objects.filter(kontrak=km).order_by("pk")
    )
    if existing:
        if exact_existing_matches_source(km):
            print("KM corporate sudah identik dengan source. Tidak membuat item baru.")
            return
        raise RuntimeError(
            "STOP: KM corporate sudah memiliki item tetapi tidak identik dengan source. "
            "Importer tidak akan overwrite data existing."
        )

    for row in ROWS:
        item = ItemKontrakManajemen(
            kontrak=km,
            bagian=parts[row.section],
            master_bagian=masters[row.section],
            no_urut=row.no,
            indikator_kinerja_kunci=row.indicator,
            formula=row.formula,
            satuan=row.unit,
            esg_kategori=row.esg,
            bobot=row.weight,
            target=row.target,
            polaritas=row.polarity,
        )
        item.full_clean()
        item.save()
        print(
            f"CREATE item={item.pk:<4} no={row.no:02d} | "
            f"{row.section} | ESG={row.esg} | bobot={row.weight} | "
            f"{row.indicator}"
        )


def verify(km):
    if not exact_existing_matches_source(km):
        raise RuntimeError("STOP: post-check source <> database tidak identik.")

    items = list(
        ItemKontrakManajemen.objects
        .filter(kontrak=km)
        .select_related("master_bagian")
        .order_by("no_urut", "pk")
    )

    subtotal = {}
    total = Decimal("0")
    for x in items:
        code = x.master_bagian.kode_bagian
        b = Decimal(str(x.bobot or 0))
        subtotal[code] = subtotal.get(code, Decimal("0")) + b
        total += b

    expected_subtotal = {c: v[1] for c, v in SECTIONS.items()}
    if subtotal != expected_subtotal:
        raise RuntimeError(
            f"STOP: subtotal DB={subtotal}, expected={expected_subtotal}"
        )
    if total != Decimal("100"):
        raise RuntimeError(f"STOP: total bobot DB={total}, expected=100")

    banner("POST-CHECK")
    print(
        f"KM id={km.pk} | {km.judul} | tahun={km.tahun} | "
        f"unit={km.unit_bisnis} | status={km.status}"
    )
    print("Items      :", len(items))
    print("Subtotal   :", subtotal)
    print("Total bobot:", total)
    print("Source     : 10/10 IDENTIK")


def execute(apply: bool) -> None:
    model_preflight()
    source_audit()
    group, km = find_state()

    if km is not None and exact_existing_matches_source(km):
        banner("RESULT")
        print("KM Korporat 2026 sudah tersedia dan identik dengan source.")
        print("Tidak ada perubahan database.")
        return

    if km is not None:
        existing_count = ItemKontrakManajemen.objects.filter(kontrak=km).count()
        if existing_count:
            raise RuntimeError(
                "STOP: KM corporate existing memiliki data yang berbeda. "
                "Review manual diperlukan; tidak di-overwrite."
            )

    if not apply:
        banner("DRY-RUN RESULT")
        print("Rencana perubahan:")
        print(f"- Group {CORPORATE_GROUP!r}: create bila belum ada")
        print(f"- KM {KM_TITLE!r}: create bila belum ada")
        print("- Bagian A-F: create/reuse canonical template 2026")
        print("- KPI corporate: create 10 item")
        print("- Total bobot reguler: 100")
        print("- Database: TIDAK DIUBAH")
        print()
        print("Jika preview sesuai, jalankan ulang dengan --apply.")
        return

    backup_sqlite()

    with transaction.atomic():
        group, template, masters, km, parts = ensure_structure()
        km = (
            KontrakManajemen.objects.select_for_update()
            .select_related("unit_bisnis", "template")
            .get(pk=km.pk)
        )

        create_items(km, masters, parts)

        if km.status != "Final":
            km.status = "Final"
            km.save(update_fields=["status"])

        verify(km)

    banner("APPLY BERHASIL")
    print("KM Korporat 2026 berhasil diimport.")
    print("Tidak ada KM Unit/Bidang yang diubah.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit perubahan. Tanpa flag ini script hanya dry-run.",
    )
    args = parser.parse_args()
    execute(args.apply)


if __name__ == "__main__":
    main()
