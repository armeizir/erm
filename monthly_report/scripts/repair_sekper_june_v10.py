"""Repair/import Monthly Risk Report SEKPER Juni 2026 - V10.

Tujuan
------
Membuat/sinkronkan Monthly Risk Report Juni 2026 untuk Profil Risiko SEKPER
yang SUDAH ADA (ReAssessmentSummary/Profile ID 13), tanpa membuat profil baru
dan tanpa menghapus 31 ReAssessmentItem historis/detail perlakuan.

Sumber:
1. Profil Risiko SETPER-2026 Update 060326
2. Laporan Mitigasi Risiko Bidang Setper s.d. Juni 2026

Struktur yang dipertahankan:
- Profile/ReAssessmentSummary ID 13 = Profil Risiko SEKPER
- 31 ReAssessmentItem tetap utuh
- 10 risiko utama (no_item 1..10)
- April report MRR-SEKPER-2026-04 sebagai template struktur
- Juni canonical report = MRR-SEKPER-2026-06
- Tepat 10 MonthlyRiskReportItem (satu representative item per risiko utama)

Dry-run:
    python monthly_report/scripts/repair_sekper_june_v10.py

Apply:
    python monthly_report/scripts/repair_sekper_june_v10.py --apply

Keamanan:
- Dry-run tidak mengubah DB.
- --apply membuat backup SQLite otomatis.
- Tidak menghapus profil, ReAssessmentItem, histori Februari/Maret/April.
- Abort bila profil/source report/struktur 10 risiko tidak sesuai.
"""
from __future__ import annotations

import argparse
import copy
import os
import shutil
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.dev")

import django

django.setup()

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db import models, transaction

from monthly_report.models import MonthlyRiskReport


PROFILE_ID = 13
YEAR = 2026
MONTH = 6
SOURCE_APRIL_CODE = "MRR-SEKPER-2026-04"
CANONICAL_JUNE_CODE = "MRR-SEKPER-2026-06"
EXPECTED_ITEMS = 10

# III.A - posisi Juni (Q2).
# nilai_dampak menggunakan nilai yang tersedia pada row sumber bila ada.
RISK_DATA = {
    1: {
        "assumption": "Dari nilai realisasi TJSL sampai dengan bulan Juni serta keterlibatan masyarakat dalam program TSL sampai dengan Juni dan pengaruhnya terhadap jumlah pemberitaan negative di media massa sampai dengan bulan Juni. Terdapat penurunan skala dampak dan skala probabilitas dikarenakan jumlah pemberitaan negative PT PLn batam Publikasi negatif yang lintas sektoral / wilayah / provinsi namun masih tersebar media konvensional.",
        "nilai_dampak": None,
        "skala_dampak": 2,
        "nilai_probabilitas": Decimal("0.3"),
        "skala_probabilitas": 2,
        "eksposur": Decimal("1001616000"),
        "skor_risiko": 6,
        "level_risiko": "Low To Moderate",
        "effectiveness": "efektif",
        "effectiveness_note": "TJSL terealisasi melampaui target sampai dengan Juni dan tidak ada penolakan masyarakat serta minimnya berita negatif terkait PT PLN Batam. Perlakuan risiko efektif sampai dengan Juni 2026 dikarenakan penurunan level risiko.",
    },
    2: {
        "assumption": "Dari nilai pencapaian realisasi nilai maturity GCG sampai dengan Juni yang dihitung secara self assessment, yang menggambarkan tingkat konsistensi PT PLN Batam dalam mencapai target maturity level risiko di tahun 2026. Target Maturity level sampai dengan Juni yaitu 1,03 sementara realisasi sebesar 1,3. Sehingga terdapat penurunan level risiko dikarenakan telah terealisasinya target sampai dengan 55% dari total target tahun 2026.",
        "nilai_dampak": None,
        "skala_dampak": 2,
        "nilai_probabilitas": Decimal("0.45"),
        "skala_probabilitas": 2,
        "eksposur": Decimal("1502424000"),
        "skor_risiko": 6,
        "level_risiko": "Low To Moderate",
        "effectiveness": "efektif",
        "effectiveness_note": "Nilai realisasi maturity level GCG sesuai target s.d. Juni. Perlakuan risiko efektif sampai dengan Juni 2026 dikarenakan penurunan level risiko.",
    },
    3: {
        "assumption": "Dari jumlah advis hukum yang terbit sampai dengan Juni dan jumlah sengketa dikarenakan penerbitan advis hukum sampai dengan Juni yang menyebabkan risiko reputasi.",
        "nilai_dampak": None,
        "skala_dampak": 3,
        "nilai_probabilitas": Decimal("0.2"),
        "skala_probabilitas": 1,
        "eksposur": Decimal("1001616000"),
        "skor_risiko": 10,
        "level_risiko": "Low To Moderate",
        "effectiveness": "efektif",
        "effectiveness_note": "Tidak ada penerbitan advis hukum yang menyebabkan sengketa. Perlakuan risiko efektif sampai dengan Juni 2026 dikarenakan tidak adanya kenaikan level risiko.",
    },
    4: {
        "assumption": "Dari jumlah penyelesaian pendampingan hukum dan biaya yang ditimbulkan akibat tuntutan dan dispute sampai dengan Juni.",
        "nilai_dampak": Decimal("134704085835"),
        "skala_dampak": 2,
        "nilai_probabilitas": Decimal("0.6"),
        "skala_probabilitas": 5,
        "eksposur": Decimal("107763268668"),
        "skor_risiko": 12,
        "level_risiko": "Moderate",
        "effectiveness": "efektif",
        "effectiveness_note": "Jumlah penyelesaian pendampingan hukum dapat terealisasi sebesar 100% sampai dengan Juni. Perlakuan risiko efektif sampai dengan Juni 2026 karena tidak ada kenaikan level risiko.",
    },
    5: {
        "assumption": "Dari jumlah pemberitaan terkait PT PLN Batam sampai dengan Juni 2026, untuk jumlah persentase berita positif, berita negatif dan jumlah berita netral.",
        "nilai_dampak": None,
        "skala_dampak": 2,
        "nilai_probabilitas": Decimal("0.4"),
        "skala_probabilitas": 3,
        "eksposur": Decimal("1335488000"),
        "skor_risiko": 8,
        "level_risiko": "Low To Moderate",
        "effectiveness": "efektif",
        "effectiveness_note": "Jumlah persentase berita negatif sampai dengan Juni relatif kecil (0,8%) dibandingkan total jumlah berita. Perlakuan risiko efektif sampai dengan Juni 2026.",
    },
    6: {
        "assumption": "Dari jumlah realisasi anggaran operasi sampai dengan Juni 2026 dibandingkan dengan rencana bayar sampai dengan TW I 2026.",
        "nilai_dampak": Decimal("1204416256"),
        "skala_dampak": 1,
        "nilai_probabilitas": Decimal("0.12"),
        "skala_probabilitas": 3,
        "eksposur": Decimal("144529950.72"),
        "skor_risiko": 3,
        "level_risiko": "Low",
        "effectiveness": "efektif",
        "effectiveness_note": "Realisasi masih sesuai dengan rencana bayar. Perlakuan risiko efektif.",
    },
    7: {
        "assumption": "Berdasarkan jumlah risiko baru yang muncul dan update profil risiko sampai dengan Juni 2026.",
        "nilai_dampak": None,
        "skala_dampak": 3,
        "nilai_probabilitas": Decimal("0.4"),
        "skala_probabilitas": 3,
        "eksposur": Decimal("2003232000"),
        "skor_risiko": 13,
        "level_risiko": "Moderate",
        "effectiveness": "efektif",
        "effectiveness_note": "Perlakuan risiko efektif karena belum ada risiko baru yang muncul.",
    },
    8: {
        "assumption": "Dari jumlah temuan audit terkait IMS dan penyelesaian temuan audit tahun 2025.",
        "nilai_dampak": None,
        "skala_dampak": 3,
        "nilai_probabilitas": Decimal("0.4"),
        "skala_probabilitas": 3,
        "eksposur": Decimal("2003232000"),
        "skor_risiko": 13,
        "level_risiko": "Moderate",
        "effectiveness": "efektif",
        "effectiveness_note": "Perlakuan efektif dan temuan audit IMS tahun 2025 telah diselesaikan.",
    },
    9: {
        "assumption": "Dari Logbook pengelolaan 3R Limbah Padat Domestik di Unit, karena berkaitan dengan pengelolaan lingkungan yang berdampak pada citra positif perusahaan.",
        "nilai_dampak": None,
        "skala_dampak": None,
        "nilai_probabilitas": None,
        "skala_probabilitas": None,
        "eksposur": None,
        "skor_risiko": None,
        "level_risiko": None,
        "effectiveness": "efektif",
        "effectiveness_note": "Perlakuan masih tahap permintaan data ke unit. Data residual Q2 belum lengkap dan akan dilaporkan oleh Bidang K3L.",
    },
    10: {
        "assumption": "Dari jumlah kecelakaan kerja yang terjadi di lingkungan perusahaan, karena berpotensi mempengaruhi nilai kepatuhan K3L.",
        "nilai_dampak": None,
        "skala_dampak": None,
        "nilai_probabilitas": None,
        "skala_probabilitas": None,
        "eksposur": None,
        "skor_risiko": None,
        "level_risiko": None,
        "effectiveness": "efektif",
        "effectiveness_note": "Sampai dengan Mei 2026 belum terdapat data kecelakaan kerja fatality. Data residual Q2 belum lengkap dan akan dilaporkan oleh Bidang K3L.",
    },
}

# III.B - 31 detail perlakuan dikelompokkan ke 10 risiko utama.
TREATMENT_DATA = {
    1: {
        "plans": [
            "Melakukan Penyusunan RKA dan penyusunan laporan realisasi penggunaan TJSL bulanan",
            "Melakukan monitoring dan evaluasi berkala atas pencapaian Maturity Level Sustainability yang akan dilakukan pertriwulan",
        ],
        "outputs": ["Laporan monitoring Penggunaan TJSL", "Asesmen dilakukan semesteran"],
        "cost": Decimal("9423869999"),
        "pics": ["MAN KOM"],
        "progress": Decimal("73.40614192"),
        "kri": "Realisasi Program Keterlibatan Masyarakat dalam Kegiatan Ketenagalistrikan sesuai Indikator Kinerja Maturity Level Sustainability",
        "june_threshold": "Kuning",
        "june_threshold_score": "70-92%",
        "note": "",
    },
    2: {
        "plans": [
            "Telah melakukan peningkatan kompetensi dan awareness GCG seluruh insan perusahaan melalui sosialisasi GCG Code dan Board Manual",
            "Telah melakukan peningkatan kompetensi pengelola GCG sesuai timeline April 2026",
            "Tahap finalisasi penilaian self assessment penerapan GCG tahun 2025",
            "Sedang berproses penilaian monitoring Maturity Level GCG setiap triwulan",
            "Telah dilakukan monitoring dan evaluasi berkala atas implementasi dan tindak lanjut rekomendasi GCG tahun 2024",
        ],
        "outputs": [
            "Daftar hadir dan paparan",
            "Hasil penilaian Self Assessment GCG tahun 2025 PT PLN Batam",
            "Laporan tindak lanjut AOI Triwulanan dan dilaporkan dalam Laporan Manajemen",
        ],
        "cost": Decimal("0"),
        "pics": ["MAN SEK"],
        "progress": Decimal("45.45454545"),
        "kri": "Skor maturity GCG tahunan",
        "june_threshold": "Merah",
        "june_threshold_score": "<2.0",
        "note": "",
    },
    3: {
        "plans": [
            "Belum ada kerjasama dengan konsultan hukum eksternal untuk kasus strategis/kompleks",
            "Dalam tahap proses penyusunan rencana peningkatan kompetensi SDM hukum (pelatihan & sertifikasi)",
            "Melakukan pemutakhiran regulasi secara berkala dan terdokumentasi sesuai usulan masing-masing unit/bidang",
        ],
        "outputs": ["Laporan jumlah Dokumen SK/SE yang telah update"],
        "cost": Decimal("0"),
        "pics": ["MAN KUM"],
        "progress": Decimal("16.66666667"),
        "kri": "Jumlah sengketa/temuan hukum yang terkait advis hukum",
        "june_threshold": "Hijau",
        "june_threshold_score": "0",
        "note": "",
    },
    4: {
        "plans": [
            "Belum dilakukan kerjasama dengan advokat/konsultan hukum berpengalaman untuk perkara berisiko tinggi",
            "Dalam proses penyusunan rencana peningkatan kompetensi SDM hukum litigasi dan non litigasi",
            "Membuat laporan berkala terkait pendampingan hukum",
        ],
        "outputs": ["Laporan bulanan pendampingan hukum dalam laporan sekretariat perusahaan"],
        "cost": Decimal("0"),
        "pics": ["MAN KUM"],
        "progress": Decimal("33.33333333"),
        "kri": "Penyelesaian Pendampingan",
        "june_threshold": "",
        "june_threshold_score": "",
        "note": "",
    },
    5: {
        "plans": [
            "Melakukan pelaksanaan FGD Pengelolaan Komunikasi dengan Media, target pelaksanaan bulan Juli 2026",
            "Belum melakukan update SK penetapan tim komunikasi krisis lintas fungsi",
            "Melaksanakan pelatihan komunikasi",
            "Belum melakukan update kebijakan komunikasi internal dan eksternal serta komunikasi krisis",
        ],
        "outputs": [
            "Sudah dilakukan FGD media dengan format media gathering",
            "Pelatihan dan sertifikasi komunikasi staf Komunikasi",
        ],
        "cost": Decimal("0"),
        "pics": ["MAN KOM"],
        "progress": None,
        "kri": "",
        "june_threshold": "Merah",
        "june_threshold_score": ">1%",
        "note": "",
    },
    6: {
        "plans": [
            "Telah melakukan monitoring anggaran operasi secara berkala s.d. Juni",
            "Telah melakukan penyampaian rencana bayar Bidang SETPER setiap triwulan kepada Bidang Keuangan",
        ],
        "outputs": [
            "Laporan realisasi AO sampai dengan Juni 2026",
            "Usulan rencana bayar SETPER Triwulan 2 tahun 2026",
        ],
        "cost": Decimal("0"),
        "pics": ["MAN KOM", "MAN KUM", "MAN SEK"],
        "progress": Decimal("29.16666667"),
        "kri": "Realisasi Penggunaan Anggaran dibandingkan dengan SKAO Terbit",
        "june_threshold": "Hijau",
        "june_threshold_score": "<90%",
        "note": "",
    },
    7: {
        "plans": [
            "Telah melakukan penyusunan profil risiko berbasis target KPI 2026",
            "Telah melaksanakan review profil risiko secara berkala",
        ],
        "outputs": [
            "Profil Risiko SETPER 2026",
            "Pelaporan risiko sampai dengan April belum menyertakan Bidang K3L",
        ],
        "cost": Decimal("0"),
        "pics": ["MAN KOM", "MAN KUM", "MAN SEK"],
        "progress": Decimal("25"),
        "kri": "Frekuensi perubahan atau penambahan risiko dalam risk register",
        "june_threshold": "Hijau",
        "june_threshold_score": "0",
        "note": "",
    },
    8: {
        "plans": [
            "Telah melakukan update SOP sesuai peraturan yang berlaku",
            "Melakukan monitoring dan evaluasi implementasi secara berkala serta menindaklanjuti hasil audit",
        ],
        "outputs": ["Draft SOP", "Laporan tindak lanjut hasil audit"],
        "cost": Decimal("0"),
        "pics": ["MAN KOM", "MAN KUM", "MAN SEK"],
        "progress": Decimal("100"),
        "kri": "Persentase penyelesaian rencana aksi perbaikan dari hasil audit",
        "june_threshold": "Hijau",
        "june_threshold_score": "100",
        "note": "",
    },
    9: {
        "plans": [
            "Melakukan sosialisasi Program 3R Limbah Padat Domestik",
            "Belum melakukan permintaan data Limbah Padat Domestik",
            "Belum melakukan monitoring penanganan limbah padat domestik",
        ],
        "outputs": ["Sosialisasi kertas kerja Maturity Level Sustainability"],
        "cost": Decimal("0"),
        "pics": ["MAN K3L"],
        "progress": None,
        "kri": "Unit yang memiliki Program Pengelolaan Limbah Padat Domestik",
        "june_threshold": "",
        "june_threshold_score": "",
        "note": "Dilaporkan Bidang K3L; data residual Q2 dan realisasi KRI Juni belum lengkap.",
    },
    10: {
        "plans": [
            "Membuat usulan KPI Improvement K3L",
            "Juknis Improvement K3L",
            "Belum melakukan sosialisasi Juknis Improvement K3L",
            "Belum meminta penyampaian realisasi dari Unit Bisnis terkait Data Monitoring K3L",
            "Belum melakukan Monitoring dan Evaluasi",
        ],
        "outputs": ["Usulan Cascading KPI Bidang Operasi Tahun 2026"],
        "cost": Decimal("0"),
        "pics": ["MAN K3L"],
        "progress": None,
        "kri": "Tindak lanjut temuan unsafe action",
        "june_threshold": "Merah",
        "june_threshold_score": "< 50",
        "note": "Dilaporkan Bidang K3L; data residual Q2 belum lengkap.",
    },
}


REALIZATION_FIELDS = {
    "realisasi_asumsi_dampak",
    "realisasi_nilai_dampak",
    "realisasi_skala_dampak",
    "realisasi_nilai_probabilitas",
    "realisasi_skala_probabilitas",
    "realisasi_eksposur",
    "realisasi_skor_risiko",
    "realisasi_level_risiko",
    "efektivitas_perlakuan_risiko",
    "realisasi_rencana_perlakuan",
    "realisasi_output_perlakuan",
    "realisasi_biaya_perlakuan",
    "persentase_serapan_biaya",
    "realisasi_pic",
    "status_rencana_perlakuan",
    "penjelasan_status_rencana",
    "progress_pelaksanaan_percent",
    "realisasi_threshold_kri",
    "realisasi_threshold_kri_skor",
    "trend",
    "issue_summary",
    "next_action",
    "escalation_note",
}


def fmt_num(value):
    if value is None:
        return "-"
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    return str(value)


def has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except FieldDoesNotExist:
        return False


def safe_assign(obj, field_name: str, value):
    """Assign sesuai tipe field; termasuk resolver ForeignKey master skala."""
    if not has_field(obj.__class__, field_name):
        return

    field = obj._meta.get_field(field_name)

    if value is None:
        if getattr(field, "null", False):
            setattr(obj, field_name, None)
        elif isinstance(field, (models.CharField, models.TextField)):
            setattr(obj, field_name, "")
        return

    # ForeignKey seperti MasterSkalaDampak / MasterSkalaProbabilitas.
    # Angka 1-5 pada sumber adalah nilai urutan skala, bukan object Django.
    if isinstance(field, models.ForeignKey):
        RelatedModel = field.related_model

        try:
            numeric_value = int(Decimal(str(value)))
        except (InvalidOperation, ValueError, TypeError):
            raise RuntimeError(
                f"Tidak dapat mengubah {field_name}={value!r} "
                f"menjadi referensi {RelatedModel._meta.label}."
            )

        related_field_names = {
            f.name for f in RelatedModel._meta.fields
        }

        related_obj = None

        # Prioritas: cari berdasarkan urutan master.
        if "urutan" in related_field_names:
            qs = RelatedModel.objects.filter(urutan=numeric_value)

            if "aktif" in related_field_names:
                active_qs = qs.filter(aktif=True)
                if active_qs.exists():
                    qs = active_qs

            related_obj = qs.order_by("pk").first()

        # Fallback aman ke PK bila model master tidak memiliki urutan
        # atau data urutan tidak ditemukan.
        if related_obj is None:
            related_obj = RelatedModel.objects.filter(
                pk=numeric_value
            ).first()

        if related_obj is None:
            raise RuntimeError(
                f"Master untuk {field_name} nilai {numeric_value} "
                f"tidak ditemukan pada {RelatedModel._meta.label}."
            )

        setattr(obj, field_name, related_obj)
        return

    if isinstance(field, models.DecimalField):
        try:
            setattr(obj, field_name, Decimal(str(value)))
        except (InvalidOperation, ValueError):
            return

    elif isinstance(
        field,
        (
            models.IntegerField,
            models.PositiveIntegerField,
            models.PositiveSmallIntegerField,
            models.SmallIntegerField,
        ),
    ):
        try:
            setattr(obj, field_name, int(Decimal(str(value))))
        except (InvalidOperation, ValueError):
            return

    elif isinstance(field, models.FloatField):
        try:
            setattr(obj, field_name, float(value))
        except (TypeError, ValueError):
            return

    elif isinstance(field, (models.CharField, models.TextField)):
        setattr(obj, field_name, str(value))

    else:
        setattr(obj, field_name, value)


def clone_kwargs(instance, *, exclude: set[str]) -> dict:
    result = {}
    for field in instance._meta.concrete_fields:
        if field.primary_key or field.auto_created:
            continue
        if field.name in exclude:
            continue
        if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
            continue
        result[field.name] = getattr(instance, field.name)
    return result


def backup_sqlite() -> Path | None:
    db_name = settings.DATABASES["default"].get("NAME")
    if not db_name:
        return None
    db_path = Path(str(db_name)).resolve()
    if not db_path.exists() or db_path.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        return None
    backup_dir = ROOT / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"db_before_sekper_june_v10_{stamp}.sqlite3"
    shutil.copy2(db_path, dest)
    return dest


def resolve_context():
    ReAssessmentSummary = MonthlyRiskReport._meta.get_field("reassessment").related_model
    profile = ReAssessmentSummary.objects.get(id=PROFILE_ID, tahun=YEAR)

    if str(profile.unit_bisnis).upper() != "SETPER":
        raise RuntimeError(
            f"Profile ID {PROFILE_ID} bukan unit SETPER: {profile.unit_bisnis}"
        )

    april = (
        MonthlyRiskReport.objects
        .select_related("reassessment", "periode")
        .get(reassessment=profile, kode=SOURCE_APRIL_CODE)
    )
    if april.items.count() != EXPECTED_ITEMS:
        raise RuntimeError(
            f"April source report items={april.items.count()}, expected={EXPECTED_ITEMS}."
        )

    june_candidates = (
        MonthlyRiskReport.objects
        .select_related("periode")
        .filter(
            periode__tanggal_mulai__year=YEAR,
            periode__tanggal_mulai__month=MONTH,
        )
        .order_by("id")
    )
    sample_june = june_candidates.first()
    if not sample_june:
        raise RuntimeError("Periode Juni 2026 tidak ditemukan dari MonthlyRiskReport lain.")
    june_period = sample_june.periode

    existing = list(
        MonthlyRiskReport.objects.filter(
            reassessment=profile,
            periode=june_period,
        ).order_by("id")
    )
    if len(existing) > 1:
        raise RuntimeError(
            "Lebih dari satu MonthlyRiskReport SEKPER untuk Juni ditemukan: "
            + ", ".join(str(x.id) for x in existing)
        )
    june = existing[0] if existing else None

    april_items = list(april.items.select_related("risk_event").order_by("risk_event__no_item", "id"))
    april_by_no = {}
    for item in april_items:
        no = int(item.risk_event.no_item)
        if no in april_by_no:
            raise RuntimeError(f"April report memiliki duplikat no_item {no}.")
        april_by_no[no] = item

    if sorted(april_by_no) != list(range(1, EXPECTED_ITEMS + 1)):
        raise RuntimeError(
            f"April no_item tidak 1..10: {sorted(april_by_no)}"
        )

    return profile, april, june_period, june, april_by_no


def clear_realization_fields(item):
    for field_name in REALIZATION_FIELDS:
        if not has_field(item.__class__, field_name):
            continue
        field = item._meta.get_field(field_name)
        if getattr(field, "null", False):
            setattr(item, field_name, None)
        elif isinstance(field, (models.CharField, models.TextField)):
            setattr(item, field_name, "")


def joined_lines(values):
    cleaned = [str(v).strip() for v in values if v and str(v).strip()]
    return "\n".join(f"{idx}. {text}" for idx, text in enumerate(cleaned, start=1))


def populate_item(item, no_item: int):
    risk = RISK_DATA[no_item]
    treatment = TREATMENT_DATA[no_item]

    clear_realization_fields(item)

    safe_assign(item, "realisasi_asumsi_dampak", risk["assumption"])
    safe_assign(item, "realisasi_nilai_dampak", risk["nilai_dampak"])
    safe_assign(item, "realisasi_skala_dampak", risk["skala_dampak"])
    safe_assign(item, "realisasi_nilai_probabilitas", risk["nilai_probabilitas"])
    safe_assign(item, "realisasi_skala_probabilitas", risk["skala_probabilitas"])
    safe_assign(item, "realisasi_eksposur", risk["eksposur"])
    safe_assign(item, "realisasi_skor_risiko", risk["skor_risiko"])
    safe_assign(item, "realisasi_level_risiko", risk["level_risiko"])
    safe_assign(item, "efektivitas_perlakuan_risiko", risk["effectiveness"])

    safe_assign(item, "realisasi_rencana_perlakuan", joined_lines(treatment["plans"]))
    safe_assign(item, "realisasi_output_perlakuan", joined_lines(treatment["outputs"]))
    safe_assign(item, "realisasi_biaya_perlakuan", treatment["cost"])
    safe_assign(item, "realisasi_pic", ", ".join(treatment["pics"]))
    safe_assign(item, "status_rencana_perlakuan", "continue")
    safe_assign(item, "progress_pelaksanaan_percent", treatment["progress"])
    safe_assign(item, "mitigation_progress_percent", treatment["progress"])

    explanation_parts = [
        risk["effectiveness_note"],
        treatment["note"],
    ]
    explanation = " ".join(x.strip() for x in explanation_parts if x and x.strip())
    safe_assign(item, "penjelasan_status_rencana", explanation)

    if treatment["june_threshold"]:
        safe_assign(item, "realisasi_threshold_kri", treatment["june_threshold"])
    if treatment["june_threshold_score"]:
        safe_assign(item, "realisasi_threshold_kri_skor", treatment["june_threshold_score"])

    if no_item in (9, 10):
        safe_assign(
            item,
            "issue_summary",
            "Data kuantifikasi residual Q2 belum lengkap pada Lampiran III.A; "
            "pelaporan lanjutan berada pada Bidang K3L.",
        )
        safe_assign(
            item,
            "next_action",
            "Lengkapi realisasi residual Q2 dan bukti monitoring K3L pada periode berikutnya.",
        )


def print_plan(profile, april, june_period, june, april_by_no):
    print("=" * 110)
    print("SEKPER JUNI 2026 - REPAIR/IMPORT V10")
    print("=" * 110)
    print("Profile         :", profile.id, "-", profile)
    print("Unit            :", profile.unit_bisnis)
    print("April template  :", april.id, "-", april.kode, "| items=", april.items.count())
    print("Periode Juni    :", june_period)
    print(
        "June report     :",
        f"id={june.id}, kode={june.kode}, items={june.items.count()}" if june else "BELUM ADA - AKAN DIBUAT",
    )
    print()
    print("MAPPING 10 RISIKO UTAMA:")
    for no in range(1, 11):
        src = april_by_no[no]
        risk = RISK_DATA[no]
        treatment = TREATMENT_DATA[no]
        print(
            f"{no:>2}. RE={src.risk_event_id} | {src.risk_event.peristiwa_risiko[:75]}"
        )
        print(
            f"    Residual Q2: exposure={fmt_num(risk['eksposur'])}, "
            f"score={fmt_num(risk['skor_risiko'])}, level={risk['level_risiko'] or '-'}"
        )
        print(
            f"    Treatment: {len(treatment['plans'])} detail | "
            f"cost={fmt_num(treatment['cost'])} | progress={fmt_num(treatment['progress'])}"
        )
    print("-" * 110)
    print("Total realisasi biaya III.B:", fmt_num(sum(x["cost"] for x in TREATMENT_DATA.values())))
    print("Risiko Q2 lengkap            : 8 dari 10")
    print("Risiko Q2 belum lengkap      : 9 dan 10 (K3L)")
    print("Target June items            : 10")


def create_or_get_june(profile, april, june_period, existing_june):
    if existing_june:
        if existing_june.kode != CANONICAL_JUNE_CODE:
            existing_june.kode = CANONICAL_JUNE_CODE
            existing_june.save(update_fields=["kode"])
        return existing_june, False

    exclude = {
        "id", "pk", "created_at", "updated_at",
        "periode", "reassessment", "kode",
        "reviewed_by", "reviewed_at", "approved_by", "approved_at",
        "submitted_at", "locked_at",
    }
    kwargs = clone_kwargs(april, exclude=exclude)
    kwargs["reassessment"] = profile
    kwargs["periode"] = june_period
    if has_field(MonthlyRiskReport, "kode"):
        kwargs["kode"] = CANONICAL_JUNE_CODE

    report = MonthlyRiskReport(**kwargs)

    # Reset workflow fields bila ada.
    for field_name in (
        "reviewed_by", "reviewed_at", "approved_by", "approved_at",
        "submitted_at", "locked_at",
    ):
        if has_field(MonthlyRiskReport, field_name):
            safe_assign(report, field_name, None)

    if has_field(MonthlyRiskReport, "status"):
        status_field = MonthlyRiskReport._meta.get_field("status")
        choices = {str(v) for v, _ in (status_field.choices or [])}
        if "draft" in choices:
            report.status = "draft"

    report.save()
    return report, True


def sync_items(june, april_by_no):
    ItemModel = june.items.model
    existing_items = list(june.items.select_related("risk_event").order_by("id"))

    if existing_items and len(existing_items) != EXPECTED_ITEMS:
        raise RuntimeError(
            f"June report sudah memiliki {len(existing_items)} items, expected 0 atau {EXPECTED_ITEMS}. "
            "Tidak ada item yang dihapus."
        )

    by_no = {}
    for item in existing_items:
        no = int(item.risk_event.no_item)
        if no in by_no:
            raise RuntimeError(f"June report memiliki duplikat no_item {no}.")
        by_no[no] = item

    created = 0
    updated = 0

    for no in range(1, 11):
        if no in by_no:
            item = by_no[no]
            # Pastikan representative risk_event sama seperti April.
            if item.risk_event_id != april_by_no[no].risk_event_id:
                raise RuntimeError(
                    f"June no_item {no} memakai RE {item.risk_event_id}, "
                    f"April canonical memakai RE {april_by_no[no].risk_event_id}."
                )
        else:
            source = april_by_no[no]
            exclude = {"id", "pk", "created_at", "updated_at", "report"}
            kwargs = clone_kwargs(source, exclude=exclude)
            kwargs["report"] = june
            item = ItemModel(**kwargs)
            created += 1

        populate_item(item, no)
        item.save()

        if no in by_no:
            updated += 1

    final_count = june.items.count()
    if final_count != EXPECTED_ITEMS:
        raise RuntimeError(
            f"Setelah sync jumlah June items={final_count}, expected={EXPECTED_ITEMS}."
        )

    return created, updated


def verify(june):
    items = list(june.items.select_related("risk_event").order_by("risk_event__no_item", "id"))
    if len(items) != 10:
        raise RuntimeError(f"VERIFY gagal: items={len(items)}")

    nos = [int(x.risk_event.no_item) for x in items]
    if nos != list(range(1, 11)):
        raise RuntimeError(f"VERIFY no_item gagal: {nos}")

    total_cost = Decimal("0")
    for item in items:
        value = getattr(item, "realisasi_biaya_perlakuan", None)
        if value is not None:
            total_cost += Decimal(value)

    if total_cost != Decimal("9423869999"):
        raise RuntimeError(
            f"VERIFY total realisasi biaya={total_cost}, expected=9423869999"
        )

    print("\nVERIFIKASI:")
    print("Report ID        :", june.id)
    print("Kode             :", june.kode)
    print("Items            :", len(items))
    print("No item          :", nos)
    print("Total biaya      :", total_cost)
    print(
        "Risiko 9/10 Q2   :",
        getattr(items[8], "realisasi_skor_risiko", None),
        "/",
        getattr(items[9], "realisasi_skor_risiko", None),
        "(expected kosong/None)",
    )


def main():
    parser = argparse.ArgumentParser(description="Repair/import SEKPER June 2026 V10")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    profile, april, june_period, june, april_by_no = resolve_context()
    print_plan(profile, april, june_period, june, april_by_no)

    if not args.apply:
        print("\nDRY RUN: tidak ada data yang diubah.")
        print(
            "Target apply: buat/update MRR-SEKPER-2026-06 dengan tepat 10 item; "
            "31 ReAssessmentItem profile tetap utuh."
        )
        return

    backup = backup_sqlite()
    if backup:
        print("\nBACKUP DB:", backup)
    else:
        print("\nPERINGATAN: backup SQLite otomatis tidak dibuat.")

    with transaction.atomic():
        june, report_created = create_or_get_june(
            profile, april, june_period, june
        )
        created, updated = sync_items(june, april_by_no)
        verify(june)

    print("\n" + "=" * 110)
    print("APPLY BERHASIL")
    print("=" * 110)
    print("June report created :", report_created)
    print("Items created       :", created)
    print("Items updated       :", updated)
    print("Report              :", june.id, "-", june.kode)
    print("Items final         :", june.items.count())
    print("Profil ID 13        : tetap dipakai")
    print("ReAssessmentItem    : tidak dihapus")
    print(
        "\nNEXT: jalankan finalizer SEKPER V9 DRY-RUN dahulu, jangan langsung --apply."
    )


if __name__ == "__main__":
    main()
