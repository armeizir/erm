#!/usr/bin/env python3
"""
IMPORT RKM BID STRADA — JULI 2026 (SAFE v2)

Sumber:
  REALISASI KPI STRADA sd JULI 2026 OKE.xlsx
  - Sheet "KPI STRADA 2026"
  - Sheet "RKM 2026"
  - Periode Januari 2026 s.d. Juli 2026
  - Dokumen bertanggal Batam, 4 Agustus 2026

Target production yang DIVALIDASI, bukan dibuat:
  Unit : BID STRADA
  KM   : VPSTRADA
  Tahun: 2026

Prinsip:
- KM master VPSTRADA TIDAK diubah.
- Wajib memetakan 10/10 KPI source secara unik ke ItemKontrakManajemen existing.
- Placeholder KM dengan no_urut sama tetapi indikator kosong diabaikan; tidak dihapus.
- Mengabaikan KPI tambahan/bridge di luar no_urut 1..10.
- Membuat atau memperbarui RKM Juli 2026 hanya jika belum Final/Disetujui.
- Realisasi Januari–Juli disalin sesuai sumber.
- Sel kosong pada sumber tetap kosong; tidak diubah menjadi 0.
- Persen capaian menggunakan angka KPI sumber, bukan hasil kalkulasi generik model.
- Tidak menghapus RKMItem existing di luar 10 KPI sumber.
- Default adalah DRY RUN transaction rollback.
- --apply membuat backup SQLite sebelum commit.

Pemakaian:
  python risk/scripts/import_rkm_strada_juli_2026.py

Apply setelah output dry-run diperiksa:
  python risk/scripts/import_rkm_strada_juli_2026.py --apply
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.prod")

import django
django.setup()

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction

from risk.models import (
    ItemKontrakManajemen,
    KontrakManajemen,
    RKMItem,
    RKMSummary,
)

YEAR = 2026
MONTH = 7
UNIT_NAME = "BID STRADA"
KM_TITLE = "VPSTRADA"
RKM_TITLE = "RKM BID STRADA Juli 2026"

SOURCE_NAME = "REALISASI KPI STRADA sd JULI 2026 OKE.xlsx"
SOURCE_SHA256 = "2bc3fe32e9231cff2cedd8ebc9b0abd7a6fd5ceea042313e09e9758909701b0e"

SECTION_NAMES = {
    "A": "Nilai Ekonomi dan Sosial Untuk Indonesia",
    "B": "Inovasi Model Bisnis",
    "C": "Kepemimpinan Teknologi",
    "D": "Peningkatan Investasi",
    "E": "Pengembangan Talenta",
    "F": "Kepatuhan",
}

MONTH_FIELDS = [
    ("januari", 0),
    ("februari", 1),
    ("maret", 2),
    ("april", 3),
    ("mei", 4),
    ("juni", 5),
    ("juli", 6),
]


class DryRunRollback(Exception):
    pass


def norm(value) -> str:
    s = str(value or "").casefold().replace("\xa0", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    s = str(value).strip()
    if not s or s == "-":
        return None
    s = s.replace("%", "").replace(" ", "")
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        s = format(value, "f")
    else:
        s = str(value)
    return s.strip()


@dataclass(frozen=True)
class SourceRow:
    no: int
    section: str
    indicator: str
    aliases: tuple[str, ...]
    expected_weight: Decimal
    expected_target_tokens: tuple[str, ...]
    source_unit: str
    initiative: str
    program: str
    risk: str
    mitigation: str
    action: str
    target_accumulation: str
    target_unit: str
    monthly_actuals: tuple[str, str, str, str, str, str, str]
    achievement: Decimal | None
    pic: str
    analysis: str


ROWS = [
    SourceRow(
        1, "A",
        "Penyelesain Proyek RUPTL",
        ("Penyelesaian Proyek RUPTL",),
        Decimal("12"), ("100",), "%",
        "Melaksanakan penyelesaian Proyek Rencana Usaha Penyediaan Tenaga Listrik (RUPTL)",
        "Memastikan penyelesaian Proyek Rencana Usaha Penyediaan Tenaga Listrik (RUPTL) sesuai target",
        "Penyelesaian proyek RUPTL terlambat",
        "Mengoptimalkan penggunaan aplikasi dalam proses pengolaan data pengadaan barang/jasa",
        "Meningkatkan keandalan sistem Listrik mengoperasikan kapasitas pembangkitan dan penguatan jaringan transmisi dan distribusi.",
        "1", "%",
        ("", "", "", "", "", "74.56", "74.56"),
        Decimal("74.56"),
        "VP STRADA\nMAN LAKDA\nMANRENDA",
        "Penyelesaian Proyek RUPTL yaitu 75 % (s.d Juli-26)",
    ),
    SourceRow(
        2, "A",
        "Penyelesaian Proses Pengadaan Barang dan Jasa (AO & AI Sentralisasi)",
        (
            "Penyelesaian Proses Pengadaan Barang dan Jasa (AO & AI Sentralisasi) - Rata-Rata Waktu Proses PBJ",
            "Penyelesaian Proses Pengadaan Barang dan Jasa (AI & AO Sentralisasi)",
        ),
        Decimal("12"), ("50",), "Hari Kerja",
        "Melaksanakan Penyelesaian Proses Pengadaan Barang dan Jasa (AI & AO sentralisasi) sesuai target",
        "Memastikan dan melaksanakan penyelesaian Proses Pengadaan Barang dan Jasa (AI & AO sentralisasi) sesuai target",
        "Proses pelaksanaan Pengadaan lebih dari 50 Hari Kerja.",
        "Mengoptimalkan penggunaan aplikasi dalam proses pengolaan data pengadaan barang/jasa",
        "1. Memastikan kegiatan review dokumen TOR, Spek Teknik, RKS untuk mengevaluasi ketentuan dan persyaratan pada dokumen yang lengkap, jelas dan kompetitif.\n"
        "2. Memastikan referensi data dan informasi harga pasar (RFI) dalam penyusunan HPS.\n"
        "3. Berkoordinasi dengan pihak lain (user/wakil pengguna) untuk membantu proses evaluasi Dokumen Teknis Penawaran.\n"
        "4. Koordinasi penyebab risiko dengan Wakil Pengguna Barang/Jasa dan/atau rapat internal/ViCon.",
        "50", "Hari Kerja",
        ("41", "41", "51.5", "51.5", "75", "59.71", "53.38"),
        Decimal("93.24"),
        "VP STRADA\nMAN LAKDA\nMANRENDA",
        "Penyelesaian Proses Pengadaan Barang dan Jasa (AO & AI) yaitu 53 Hari Kerja (s.d Juli-26)",
    ),
    SourceRow(
        3, "A",
        "Keberhasilan Nilai Kontrak Pengadaan Barang dan Jasa (AO/AI sentralisasi)",
        ("Keberhasilan Nilai Kontrak Pengadaan Barang dan Jasa (AO & AI sentralisasi)",),
        Decimal("12"), ("5.6", "5,6", "5.60", "5,60"), "%",
        "Meningkatkan efisiensi melalui keberhasilan negosiasi",
        "Memastikan keberhasilan Nilai Terkontrak terhadap HPS",
        "Efisiensi dari hasil negosiasi tidak tercapai",
        "Mempersiapkan strategi negosiasi antara lain membandingkan harga pasar dengan penawaran peserta dan tidak mengumumkan nilai HPS kepada peserta tender.",
        "1. Menjalankan prosedur pelaksanaan Pengadaan Barang/Jasa terkait penyusunan HPS.\n"
        "2. Melakukan analisis data pasar dan keuangan global seperti inflasi, kurs dollar, dan harga material (LME) dalam menyusun HPS.",
        "5,60%", "%",
        ("3.77", "3.77", "2.94", "9.297797237352661", "9.297797237352661", "9.297797237352661", "9.3"),
        Decimal("110.00"),
        "VP STRADA\nMAN LAKDA",
        "Total Realisasi Keberhasilan Nilai Terkontrak seluruh PBJ terhadap HPS yaitu 9 % (s.d Juli-26)",
    ),
    SourceRow(
        4, "A",
        "Kualitas Penerapan Manajemen Risiko (KPMR)",
        ("KPMR",),
        Decimal("12"), ("80",), "Skor",
        "Implementasi penerapan Manajemen Risiko dilaksanakan sesuai target",
        "Memastikan penerapan Manajemen Risiko dilaksanakan sesuai target",
        "Program Manajemen Risiko di bawah target",
        "Melakukan monitoring pelaksanaan Manajemen Risiko",
        "1. Melaksanakan Manajemen Risiko pada BID STRADA.\n2. Membuat laporan monitoring mitigasi risiko tepat waktu.",
        "80", "%",
        ("", "", "", "", "", "86", "86"),
        Decimal("107.50"),
        "VP STRADA\nMAN LAKDA\nMANRENDA",
        "Penerapan Manajemen Risiko di BID STRADA yaitu 86 % (s.d Juli-26)",
    ),
    SourceRow(
        5, "A",
        "Maturity Level Sustainability",
        (),
        Decimal("12"), ("100",), "%",
        "Melaksanakan Maturity Level Sustainability pada proses Pengadaan di Bidang STRADA sesuai target",
        "Memastikan Maturity Level Sustainability pada proses Pengadaan di Bidang STRADA sesuai target",
        "Ketidakterpenuhinya dokumen terkait Maturity Level Sustainability pada Bidang STRADA",
        "Memastikan ketentuan terkait sustainability procurement tercantum dalam dokumen tender.",
        "Melaksanakan proses Perencana dan Pelaksana Pengadaan yang sesuai dengan ketentuan pada Maturity Level Sustainability.",
        "100", "%",
        ("", "", "", "", "", "110", "110"),
        Decimal("110.00"),
        "VP STRADA\nMAN LAKDA\nMANRENDA",
        "Hasil Asesmen Maturity Level Sustainability yaitu 110 % (s.d Juli-26)",
    ),
    SourceRow(
        6, "B",
        "Survei Kepuasan Vendor/Pemasok",
        ("Survey Kepuasan Vendor/Pemasok",),
        Decimal("10"), ("4.62", "4,62"), "Indeks",
        "Meningkatkan layanan Tim STRADA dalam proses pengadaan barang/jasa",
        "Melakukan survey tingkat kepuasan vendor/pemasok atas layanan PBJ",
        "Hasil Indeks Kepuasan Vendor/Pemasok kurang dari target",
        "1. Seluruh Tim STRADA menjaga integritas pada setiap proses pengadaan.\n"
        "2. Menyampaikan form survey kepuasan pemasok segera setelah proses tender selesai.\n"
        "3. Menjaga komunikasi positif dengan seluruh vendor.",
        "1. Memberikan pelayanan yang baik terhadap vendor/pemasok pada setiap tahapan PBJ sesuai tugas dan kewenangan.\n"
        "2. Program pengembangan kapabilitas pegawai.",
        "4.62", "Indeks",
        ("", "", "", "", "", "", ""),
        None,
        "VP STRADA, MAN RENDA, MAN LAKDA",
        "Dinilai pada Semester II 2026",
    ),
    SourceRow(
        7, "C",
        "Ketepatan Waktu Pengadaaan Investasi sesuai dengan Dokumen Rencana Pengadaan (DRP)",
        (
            "Ketepatan Waktu Pengadaan Investasi sesuai dengan Dokumen Rencana Pengadaan (DRP)",
            "Ketepatan Waktu Pengadaaan   Investasi sesuai dengan Dokumen Rencana Pengadaan  (DRP)",
        ),
        Decimal("10"), ("90",), "%",
        "Melaksanakan Ketepatan Waktu Pengadaan Investasi sesuai dengan Dokumen Rencana Pengadaan (DRP) sesuai target",
        "Memastikan Ketepatan Waktu Pengadaan Investasi sesuai dengan Dokumen Rencana Pengadaan (DRP) sesuai target",
        "Penyelesaian ketepatan waktu Pengadaan Investasi sesuai DRP tahun 2026 tidak tercapai",
        "Memastikan pengumuman tender dapat diakses secara luas oleh calon penyedia.",
        "1. Koordinasi lebih awal dengan Wakil Pengguna Barang/Jasa dalam penyampaian usulan PBJ.\n"
        "2. Menyusun draft DRP sebelum pengesahan RKAP untuk dibahas dalam rapat VfM/Radir.\n"
        "3. Membuat beberapa skenario dalam penyusunan draft DRP.\n"
        "4. Melakukan workshop penyusunan TOR dan RAB.",
        "90", "%",
        ("", "", "", "", "", "", ""),
        None,
        "VP STRADA\nMAN LAKDA\nMANRENDA",
        "Belum dinilai pada Periode s.d Juli 2026",
    ),
    SourceRow(
        8, "D",
        "Implementasi Peningkatan Penggunaan Produk Dalam Negeri (P3DN) Dalam Proses Pengadaan Barang dan Jasa",
        ("Implementasi Peningkatan Penggunaan Produk Dalam Negeri (P3DN)",),
        Decimal("8"), ("28",), "%",
        "Memastikan Komitmen Tingkat Komponen Dalam Negeri (TKDN)",
        "Mencantumkan ketentuan terkait Komitmen Tingkat Komponen Dalam Negeri (TKDN) dalam setiap proses tender",
        "Ketidakpatuhan Komitmen Tingkat Komponen Dalam Negeri (TKDN)",
        "Memastikan ketentuan terkait komitmen TKDN tercantum dalam dokumen tender.",
        "1. Persyaratan Komitmen TKDN dalam dokumen RKS/Dokumen Tender.\n"
        "2. Persyaratan melaporkan hasil realisasi Komitmen TKDN pada saat akhir penyelesaian kontrak.",
        "28", "%",
        ("100", "100", "100", "100", "98,65", "41.78", "63.59"),
        Decimal("110.00"),
        "VP STRADA, MAN RENDA, MAN LAKDA",
        "Implementasi peningkatan penggunaan produk dalam negeri (P3DN) dalam Proses Pengadaan Barang dan Jasa yaitu 64 % (s.d Juli-26)",
    ),
    SourceRow(
        9, "E",
        "Pengelolaan Human Capital",
        ("Pengelolaan  Human Capital",),
        Decimal("12"), ("100",), "%",
        "Melaksanakan pemenuhan pengelolaan Human Capital di Bidang Strategi Pengadaan sesuai target",
        "Memastikan pengelolaan Human Capital di Bidang Strategi Pengadaan sesuai target",
        "Pemenuhan Nilai Pengelolaan Human Capital tidak sesuai target",
        "Menyiapkan data dan laporan yang terkait dengan pemenuhan Pengelolaan Human Capital",
        "1. Mengusulkan PIC HCR OCR Bidang STRADA bila diminta HCGA.\n"
        "2. Melaporkan laporan terkait program HCR OCR.\n"
        "3. Koordinasi terkait pemenuhan persyaratan penilaian HCR OCR.\n"
        "4. Melakukan list personil STRADA yang telah melakukan survey, pengisian aplikasi KOMANDO, dan pemenuhan terkait HCR OCR.",
        "100", "%",
        ("", "", "", "", "", "104", "104"),
        Decimal("104.00"),
        "VP STRADA, MAN RENDA, MAN LAKDA",
        "Pemenuhan Pengelolaan Human Capital yaitu 104 % (s.d Juli-26)",
    ),
    SourceRow(
        10, "F",
        "Compliance",
        (),
        Decimal("0"), ("max -10", "max-10"), "Nilai Pengurang",
        "Memastikan Compliance sesuai target",
        "Memastikan Compliance sesuai target",
        "Nilai Compliance di bawah target",
        "Memastikan Compliance (Maturity Level GCG, Kepatuhan Pengelolaan HSSE, Tindak lanjut Temuan SPI/BPK/audit lainnya, Keterlambatan Laporan Kinerja, dan PACA) yang menjadi tanggung jawab Bidang STRADA.",
        "1. Melakukan koordinasi dengan pihak terkait.\n2. Menyampaikan Laporan Realisasi Kinerja tepat waktu.",
        "Max -10", "Nilai Pengurang",
        ("", "", "", "", "", "", ""),
        None,
        "VP STRADA, MAN RENDA, MAN LAKDA",
        "Pemenuhan Compliance (GCG, Kepatuhan HSSE, Tindak lanjut SPI/BPK/audit lainnya): tidak terdapat nilai pengurang periode s.d Juli-26.",
    ),
]


def banner(title: str) -> None:
    print("\n" + "=" * 118)
    print(title)
    print("=" * 118)


def backup_sqlite() -> Path | None:
    engine = settings.DATABASES["default"].get("ENGINE", "")
    if "sqlite" not in engine:
        print("BACKUP DB: dilewati karena database bukan SQLite.")
        return None

    src = Path(str(settings.DATABASES["default"]["NAME"])).expanduser().resolve()
    if not src.is_file():
        raise RuntimeError(f"STOP: file SQLite tidak ditemukan: {src}")

    outdir = ROOT / "backups"
    outdir.mkdir(parents=True, exist_ok=True)
    dst = outdir / f"db_before_import_rkm_strada_juli_2026_{datetime.now():%Y%m%d_%H%M%S}.sqlite3"

    # SQLite online backup lebih aman daripada copy biasa saat DB aktif.
    with sqlite3.connect(src) as source:
        with sqlite3.connect(dst) as target:
            source.backup(target)

    with sqlite3.connect(dst) as con:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"STOP: backup SQLite integrity_check={integrity!r}")

    print("BACKUP DB:", dst)
    return dst


def resolve_target():
    groups = list(Group.objects.filter(name__iexact=UNIT_NAME).order_by("pk"))
    if len(groups) != 1:
        raise RuntimeError(
            f"STOP: Group {UNIT_NAME!r} harus tepat 1, ditemukan "
            f"{[(x.pk, x.name) for x in groups]}"
        )
    unit = groups[0]

    kms = list(
        KontrakManajemen.objects.filter(
            tahun=YEAR,
            unit_bisnis=unit,
        ).order_by("pk")
    )
    exact = [x for x in kms if norm(x.judul) == norm(KM_TITLE)]
    if len(exact) != 1:
        raise RuntimeError(
            f"STOP: KM {KM_TITLE!r}/{YEAR}/{UNIT_NAME} harus tepat 1. "
            f"Kandidat={[(x.pk, x.judul, x.status) for x in kms]}"
        )
    km = exact[0]

    return unit, km


def validate_km_mapping(km):
    banner("MAPPING KM STRADA — READ ONLY")

    mapping = {}
    used_ids = set()

    for src in ROWS:
        candidates = list(
            ItemKontrakManajemen.objects.filter(
                kontrak=km,
                no_urut=src.no,
            ).select_related("master_bagian", "bagian")
        )

        if not candidates:
            raise RuntimeError(
                f"STOP KPI {src.no}: tidak ada KMItem dengan no_urut={src.no}."
            )

        names = {norm(src.indicator), *(norm(x) for x in src.aliases)}

        def name_matches(obj):
            item_name = norm(obj.indikator_kinerja_kunci)
            if not item_name:
                return False
            if item_name in names:
                return True
            return any(
                n and len(n) >= 12 and (n in item_name or item_name in n)
                for n in names
            )

        # VPSTRADA production dapat memiliki placeholder/row lama dengan no_urut
        # yang sama tetapi indikator kosong. Jangan gagal hanya karena placeholder.
        named_matches = [x for x in candidates if name_matches(x)]

        if len(named_matches) == 1:
            item = named_matches[0]
        elif len(named_matches) > 1:
            # Perketat dengan bagian dan bobot jika nama masih menghasilkan >1 kandidat.
            narrowed = []
            for x in named_matches:
                section_code = getattr(getattr(x, "master_bagian", None), "kode_bagian", None)
                weight = dec(getattr(x, "bobot", None))
                section_ok = (
                    not section_code
                    or str(section_code).strip().upper() == src.section
                )
                weight_ok = (
                    weight is None
                    or weight == src.expected_weight
                )
                if section_ok and weight_ok:
                    narrowed.append(x)

            if len(narrowed) == 1:
                item = narrowed[0]
            else:
                raise RuntimeError(
                    f"STOP KPI {src.no}: mapping ambigu setelah filter nama/bagian/bobot. "
                    f"candidates={[(x.pk, x.indikator_kinerja_kunci, getattr(x, 'bobot', None)) for x in candidates]}"
                )
        else:
            # Tidak ada kecocokan nama. Tampilkan semua kandidat agar tidak pernah
            # menebak item hanya dari nomor urut.
            raise RuntimeError(
                f"STOP KPI {src.no}: tidak ada kandidat bernama cocok pada no_urut={src.no}.\n"
                f"  source={src.indicator!r}\n"
                f"  candidates={[(x.pk, x.indikator_kinerja_kunci, getattr(x, 'bobot', None)) for x in candidates]}"
            )

        item_name = norm(item.indikator_kinerja_kunci)

        section_code = getattr(getattr(item, "master_bagian", None), "kode_bagian", None)
        if section_code and str(section_code).strip().upper() != src.section:
            raise RuntimeError(
                f"STOP KPI {src.no}: bagian mismatch source={src.section}, "
                f"DB={section_code!r}, item={item.pk}"
            )

        weight = dec(getattr(item, "bobot", None))
        if weight is not None and weight != src.expected_weight:
            raise RuntimeError(
                f"STOP KPI {src.no}: bobot mismatch source={src.expected_weight}, "
                f"DB={weight}, item={item.pk}"
            )

        target_db = norm(getattr(item, "target", None))
        if src.expected_target_tokens and target_db:
            if not any(norm(tok) in target_db or target_db in norm(tok) for tok in src.expected_target_tokens):
                raise RuntimeError(
                    f"STOP KPI {src.no}: target KM tampak berbeda. "
                    f"source expected~={src.expected_target_tokens}, DB={getattr(item, 'target', None)!r}"
                )

        if item.pk in used_ids:
            raise RuntimeError(f"STOP: KMItem {item.pk} terpetakan dua kali.")
        used_ids.add(item.pk)
        mapping[src.no] = item

        print(
            f"{src.no:02d}. KMItem={item.pk:<4} | bagian={src.section} | "
            f"no_urut={item.no_urut} | bobot={getattr(item, 'bobot', None)!r} | "
            f"target={getattr(item, 'target', None)!r} | {item.indikator_kinerja_kunci}"
        )

    if len(mapping) != 10 or len(used_ids) != 10:
        raise RuntimeError("STOP: mapping bukan 10/10 unique.")

    extras = list(
        ItemKontrakManajemen.objects.filter(kontrak=km)
        .exclude(pk__in=used_ids)
        .order_by("no_urut", "pk")
    )
    print(f"\nMAPPED: 10/10 unique")
    print(f"KM items di luar source: {len(extras)} (TIDAK DIUBAH)")
    for x in extras:
        print(f"  EXTRA KMItem={x.pk} no={x.no_urut}: {x.indikator_kinerja_kunci!r}")

    return mapping


def summary_defaults(unit, km):
    data = {
        "judul": RKM_TITLE,
        "tahun": YEAR,
        "bulan": MONTH,
        "unit_bisnis": unit,
        "kontrak_manajemen": km,
        "tanggal_mulai": date(YEAR, MONTH, 1),
        "tanggal_selesai": date(YEAR, MONTH, 31),
        "status": "Draft",
        "pic": UNIT_NAME,
    }
    fields = {f.name for f in RKMSummary._meta.fields}
    if "status_pengajuan" in fields:
        data["status_pengajuan"] = "Belum"
    return {k: v for k, v in data.items() if k in fields}


def get_or_create_summary(unit, km):
    qs = RKMSummary.objects.filter(
        tahun=YEAR,
        bulan=MONTH,
        unit_bisnis=unit,
        kontrak_manajemen=km,
    ).order_by("pk")

    count = qs.count()
    if count > 1:
        raise RuntimeError(
            f"STOP: ditemukan {count} RKMSummary STRADA Juli 2026; "
            "harus diselesaikan manual sebelum import."
        )

    if count == 0:
        summary = RKMSummary(**summary_defaults(unit, km))
        summary.full_clean()
        summary.save()
        return summary, True

    summary = qs.first()

    status = norm(getattr(summary, "status", ""))
    status_pengajuan = norm(getattr(summary, "status_pengajuan", ""))
    if status == "final" or status_pengajuan == "disetujui":
        raise RuntimeError(
            f"STOP: RKM existing id={summary.pk} sudah Final/Disetujui; importer tidak boleh overwrite."
        )

    updates = []
    if getattr(summary, "judul", None) != RKM_TITLE:
        summary.judul = RKM_TITLE
        updates.append("judul")
    if getattr(summary, "tanggal_mulai", None) is None:
        summary.tanggal_mulai = date(YEAR, MONTH, 1)
        updates.append("tanggal_mulai")
    if getattr(summary, "tanggal_selesai", None) is None:
        summary.tanggal_selesai = date(YEAR, MONTH, 31)
        updates.append("tanggal_selesai")
    if hasattr(summary, "pic") and not getattr(summary, "pic", ""):
        summary.pic = UNIT_NAME
        updates.append("pic")

    if updates:
        summary.full_clean()
        summary.save(update_fields=updates)

    return summary, False


def source_row_defaults(src: SourceRow, km_item):
    # Realisasi RKM source bersifat kumulatif; "jumlah_realisasi" memakai posisi Juli,
    # bukan penjumlahan Jan..Jul.
    july_actual = src.monthly_actuals[6]
    achievement_text = (
        f"Capaian Juli 2026 sesuai KPI sumber: {src.achievement}%"
        if src.achievement is not None
        else "Capaian Juli 2026 belum/tidak diukur pada sumber."
    )

    data = {
        "no_item": src.no,
        "kategori_rkm": src.section,
        "sasaran": km_item.indikator_kinerja_kunci,
        "kpi_indikator": km_item.indikator_kinerja_kunci,
        "kpi_satuan": getattr(km_item, "satuan", None) or src.source_unit,
        "kpi_target": getattr(km_item, "target", None) or "",
        "inisiatif_strategis": src.initiative,
        "program_kerja_utama": src.program,
        "risiko": src.risk,
        "mitigasi_risiko": src.mitigation,
        "rencana_aksi": src.action,
        "anggaran_rp_ribu": None,
        "target_akumulasi": src.target_accumulation,
        "target_akumulasi_satuan": src.target_unit,
        "target_juli": src.target_accumulation,
        "realisasi_juli": july_actual,
        "jumlah_realisasi": july_actual,
        "persen_capaian": src.achievement,
        "realisasi_anggaran": None,
        "pic_rkm": src.pic,
        "hasil_analisa_program_kerja": src.analysis,
        "target_bulanan": (
            f"Juli 2026 — target akumulasi: {src.target_accumulation} {src.target_unit}".strip()
        ),
        "realisasi": (
            f"Juli 2026 — realisasi: {july_actual} {src.target_unit}".strip()
            if july_actual else src.analysis
        ),
        "deviasi": achievement_text,
        "keterangan": src.analysis,
    }

    for field_name, idx in MONTH_FIELDS:
        data[f"realisasi_{field_name}"] = src.monthly_actuals[idx]

    fields = {f.name for f in RKMItem._meta.fields}
    return {k: v for k, v in data.items() if k in fields}


def upsert_items(summary, mapping):
    imported_ids = []

    for src in ROWS:
        km_item = mapping[src.no]

        conflict = (
            RKMItem.objects.filter(summary=summary, no_item=src.no)
            .exclude(km_item=km_item)
            .first()
        )
        if conflict:
            raise RuntimeError(
                f"STOP: no_item={src.no} sudah dipakai RKMItem={conflict.pk} "
                f"untuk km_item={conflict.km_item_id}; tidak ada overwrite silang."
            )

        existing = RKMItem.objects.filter(summary=summary, km_item=km_item).first()
        defaults = source_row_defaults(src, km_item)

        if existing is None:
            item = RKMItem(summary=summary, km_item=km_item, **defaults)
        else:
            item = existing
            for field, value in defaults.items():
                setattr(item, field, value)

        item.full_clean()
        item.save()

        # Model save() dapat menghitung ulang capaian memakai formula generik.
        # Kembalikan angka sumber secara eksplisit setelah save.
        update = {}
        if "persen_capaian" in {f.name for f in RKMItem._meta.fields}:
            update["persen_capaian"] = src.achievement
        if "jumlah_realisasi" in {f.name for f in RKMItem._meta.fields}:
            update["jumlah_realisasi"] = src.monthly_actuals[6]

        if update:
            RKMItem.objects.filter(pk=item.pk).update(**update)
            item.refresh_from_db()

        imported_ids.append(item.pk)

        print(
            f"{src.no:02d}. RKMItem={item.pk:<4} | km_item={km_item.pk:<4} | "
            f"Jul={getattr(item, 'realisasi_juli', None)!r} | "
            f"capaian={getattr(item, 'persen_capaian', None)!r} | "
            f"{getattr(item, 'kpi_indikator', '')}"
        )

    return imported_ids


def verify(summary, mapping, imported_ids):
    banner("VERIFY TRANSACTION")

    items = list(
        RKMItem.objects.filter(summary=summary)
        .select_related("km_item")
        .order_by("no_item", "pk")
    )
    imported = [x for x in items if x.pk in imported_ids]

    checks = [
        (summary.tahun == YEAR and summary.bulan == MONTH, "periode 07/2026"),
        (summary.unit_bisnis.name.casefold() == UNIT_NAME.casefold(), "unit BID STRADA"),
        (summary.kontrak_manajemen.judul.casefold() == KM_TITLE.casefold(), "KM VPSTRADA"),
        (len(imported) == 10, "10 source RKMItem"),
        (sorted(x.no_item for x in imported) == list(range(1, 11)), "no_item 1..10"),
        (len({x.km_item_id for x in imported}) == 10, "km_item unique 10/10"),
        (
            {x.km_item_id for x in imported} == {mapping[n].pk for n in range(1, 11)},
            "mapping sama dengan KM source",
        ),
    ]

    for ok, label in checks:
        print(f"{label:28}: {'PASS' if ok else 'FAIL'}")
        if not ok:
            raise RuntimeError(f"STOP VERIFY: {label}")

    expected = {r.no: r for r in ROWS}
    by_no = {x.no_item: x for x in imported}
    for no in range(1, 11):
        src = expected[no]
        item = by_no[no]
        actual_jul = fmt(getattr(item, "realisasi_juli", ""))
        exp_jul = fmt(src.monthly_actuals[6])
        if actual_jul != exp_jul:
            raise RuntimeError(
                f"STOP VERIFY KPI {no}: realisasi_juli DB={actual_jul!r}, source={exp_jul!r}"
            )

        db_pct = getattr(item, "persen_capaian", None)
        if src.achievement is None:
            if db_pct is not None:
                raise RuntimeError(
                    f"STOP VERIFY KPI {no}: capaian seharusnya kosong, DB={db_pct!r}"
                )
        else:
            if dec(db_pct) != src.achievement:
                raise RuntimeError(
                    f"STOP VERIFY KPI {no}: capaian DB={db_pct!r}, source={src.achievement!r}"
                )

    extras = RKMItem.objects.filter(summary=summary).exclude(pk__in=imported_ids).count()
    print(f"Existing RKMItem di luar source: {extras} (dipertahankan)")
    print("VERIFY 10/10 OK")


def audit_source():
    banner("SOURCE AUDIT — EMBEDDED FROM WORKBOOK")
    print("Source :", SOURCE_NAME)
    print("SHA256 :", SOURCE_SHA256)
    print("Periode: Januari 2026 s.d Juli 2026")
    print("KPI    : 10")
    print("Bobot  :", sum((x.expected_weight for x in ROWS), Decimal("0")))
    print("Rows:")
    for x in ROWS:
        print(
            f"  {x.no:02d}. {x.indicator} | bagian={x.section} | "
            f"bobot={x.expected_weight} | Jul={x.monthly_actuals[6]!r} | "
            f"capaian={x.achievement!r}"
        )


def execute(apply: bool):
    audit_source()

    unit, km = resolve_target()
    banner("TARGET PRODUCTION")
    print(f"Unit : id={unit.pk} | {unit.name}")
    print(
        f"KM   : id={km.pk} | {km.judul} | tahun={km.tahun} | "
        f"status={km.status} | items={ItemKontrakManajemen.objects.filter(kontrak=km).count()}"
    )

    mapping = validate_km_mapping(km)

    existing = RKMSummary.objects.filter(
        tahun=YEAR,
        bulan=MONTH,
        unit_bisnis=unit,
        kontrak_manajemen=km,
    ).order_by("pk").first()

    banner("BASELINE RKM")
    if existing:
        print(
            f"FOUND id={existing.pk} | judul={existing.judul!r} | "
            f"status={existing.status!r} | status_pengajuan={getattr(existing, 'status_pengajuan', None)!r} | "
            f"items={RKMItem.objects.filter(summary=existing).count()}"
        )
    else:
        print("MISSING — akan dibuat RKM BID STRADA Juli 2026.")

    if apply:
        backup_sqlite()

    summary_id = None
    created = False

    try:
        with transaction.atomic():
            # Lock KM pada saat import agar mapping tidak berubah di tengah transaksi.
            km_locked = KontrakManajemen.objects.select_for_update().get(pk=km.pk)
            current_mapping = validate_km_mapping(km_locked)

            summary, created = get_or_create_summary(unit, km_locked)
            summary_id = summary.pk

            banner("UPSERT RKM ITEMS")
            imported_ids = upsert_items(summary, current_mapping)
            verify(summary, current_mapping, imported_ids)

            if not apply:
                raise DryRunRollback()

    except DryRunRollback:
        banner("RINGKASAN DRY RUN")
        print(f"RKM summary : {'akan dibuat' if created else 'akan diperbarui'}")
        print("Source KPI  : 10")
        print("Mapped KPI  : 10/10 existing KM VPSTRADA")
        print("KM master   : TIDAK DIUBAH")
        print("Delete row  : 0")
        print("Database    : TIDAK BERUBAH — transaction rollback")
        print("\nDRY RUN BERHASIL. Review output; jika bersih jalankan ulang dengan --apply.")
        return

    banner("APPLY & VERIFY BERHASIL")
    summary = RKMSummary.objects.get(pk=summary_id)
    items = list(RKMItem.objects.filter(summary=summary).order_by("no_item", "pk"))
    print(
        f"RKM={summary.pk} | {summary.judul} | "
        f"periode={summary.bulan:02d}/{summary.tahun} | "
        f"status={summary.status!r} | items_total={len(items)}"
    )
    print("KM VPSTRADA tetap existing dan tidak dimodifikasi oleh importer.")
    print("Import RKM STRADA Juli 2026 selesai.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit perubahan. Default selalu DRY RUN rollback.",
    )
    args = parser.parse_args()
    execute(args.apply)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValidationError) as exc:
        print(f"\nSTOP: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except Exception as exc:
        print(f"\nUNEXPECTED ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
