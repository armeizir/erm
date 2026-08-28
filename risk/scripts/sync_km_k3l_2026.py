import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "riskproject.settings.prod",
)

import django
django.setup()

from django.contrib.auth.models import Group
from django.db import transaction

from risk.models import (
    KontrakManajemen,
    BagianKontrakManajemen,
    ItemKontrakManajemen,
    MasterBagianKM,
    MasterTemplateKM,
)


UNIT_ID = 19
YEAR = 2026
TITLE = "VPK3L"
STATUS = "Final"
TEMPLATE_ID = 1


SECTIONS = {
    "A": "Nilai Ekonomi dan Sosial Untuk Indonesia",
    "B": "Inovasi Model Bisnis",
    "C": "Kepemimpinan Teknologi",
    "D": "Peningkatan Investasi",
    "E": "Pengembangan Talenta",
    "F": "Kepatuhan",
}


KPI_DATA = [
    {
        "no": 1,
        "bagian": "A",
        "indikator": "Optimalisasi Biaya Pemeliharaan",
        "formula": "Realisasi Optimalisasi Biaya Pemeliharaan K3L",
        "satuan": "%",
        "bobot": 10.0,
        "target": "95 - 100",
        "polaritas": "positif",
    },
    {
        "no": 2,
        "bagian": "A",
        "indikator": "Maturity Level Sustainability",
        "formula": "Hasil Asesmen Maturity Level Sustainability",
        "satuan": "Level",
        "bobot": 15.0,
        "target": "3,10",
        "polaritas": "positif",
    },
    {
        "no": 3,
        "bagian": "A",
        "indikator": "Kualitas Penerapan Manajemen Risiko (KPMR)",
        "formula": "Penerapan Manajemen Risiko (KPMR) di Bidang K3L",
        "satuan": "Skor",
        "bobot": 12.0,
        "target": "80",
        "polaritas": "positif",
    },
    {
        "no": 4,
        "bagian": "B",
        "indikator": "Implementasi Sistem Manajemen Terintegrasi",
        "formula": (
            "Prosentase Rata-rata Waktu Pemenuhan Eviden di tanggal "
            "30 September 2026:\n"
            "1. Maturity ISO 14001 Sistem Manajemen Lingkungan Level 3\n"
            "2. Maturity ISO 45001 Sistem Manajemen Keselamatan dan "
            "Kesehatan Kerja (K3) Level 3\n"
            "3. Maturity Perpol 7/2019 Sistem Manajemen Pengamanan Level 2\n"
            "4. Maturity PP50/2012 Kemnaker Sistem Manajemen Keselamatan "
            "dan Kesehatan Kerja (SMK3) Level 3"
        ),
        "satuan": "%",
        "bobot": 10.0,
        "target": "100",
        "polaritas": "positif",
    },
    {
        "no": 5,
        "bagian": "C",
        "indikator": (
            "Penguatan K3L pada Level Mitra Kerja: Mengidentifikasi "
            "Kondisi Bahaya Tempat Kerja/Aset di Area Proyek"
        ),
        "formula": (
            "Tersedianya Laporan Unsafe Action dan/atau Unsafe Condition "
            "di Lokasi Area Proyek RUPTL Beserta Rekomendasi Atas Temuan "
            "per-Semester"
        ),
        "satuan": "%",
        "bobot": 14.0,
        "target": "100",
        "polaritas": "positif",
    },
    {
        "no": 6,
        "bagian": "D",
        "indikator": "Penyelesaian Program Improvement K3L",
        "formula": (
            "Penyelesaian Program Improvement K3L sesuai Target x 100 %"
        ),
        "satuan": "%",
        "bobot": 12.0,
        "target": "100",
        "polaritas": "positif",
    },
    {
        "no": 7,
        "bagian": "E",
        "indikator": "Pengelolaan Human Capital",
        "formula": (
            "Rata-rata Pencapaian:\n"
            "1. Produktivitas Pegawai dan Penguatan Budaya\n"
            "2. Pengelolaan Human Capital Services"
        ),
        "satuan": "%",
        "bobot": 12.0,
        "target": "100",
        "polaritas": "positif",
    },
    {
        "no": 8,
        "bagian": "E",
        "indikator": "Pengelolaan Safety Culture",
        "formula": "Lost Time Injury Frequency Rate",
        "satuan": "Indeks",
        "bobot": 15.0,
        "target": "0,332 indeks (per 1 juta jam kerja)",
        "polaritas": "negatif",
    },
    {
        "no": 9,
        "bagian": "F",
        "indikator": "Compliance",
        "formula": (
            "Jumlah nilai pengurang dari unsur:\n"
            "- Maturity Level GCG\n"
            "- Kepatuhan pengelolaan HSSE\n"
            "- Tindak lanjut temuan SPI, BPK, dan Auditor lainnya\n"
            "- Keterlambatan Laporan Kinerja "
            "(termasuk laporan manajemen risiko)\n"
            "- Planning Accuracy Compliance Adjustment (PACA)"
        ),
        # Normalisasi mengikuti pola KM 2026 existing:
        # "Nilai Pengurang" ditempatkan pada satuan dan bobot numerik = 0.
        "satuan": "Nilai Pengurang",
        "bobot": 0.0,
        "target": "Max -10",
        "polaritas": "positif",
    },
]


def stop(message):
    raise RuntimeError(f"SAFETY STOP: {message}")


def validate_source():
    regular = [
        row for row in KPI_DATA
        if row["bagian"] != "F"
    ]

    total = sum(row["bobot"] for row in regular)

    if total != 100.0:
        stop(
            f"Total bobot reguler={total}; expected 100."
        )

    if len(KPI_DATA) != 9:
        stop(
            f"Jumlah KPI={len(KPI_DATA)}; expected 9."
        )

    if [row["no"] for row in KPI_DATA] != list(range(1, 10)):
        stop("Nomor KPI tidak persis 1-9.")

    compliance = KPI_DATA[-1]

    if (
        compliance["indikator"] != "Compliance"
        or compliance["bobot"] != 0.0
        or compliance["target"] != "Max -10"
    ):
        stop("Konfigurasi Compliance tidak sesuai.")

    for row in KPI_DATA:
        if row["polaritas"] not in {
            "positif",
            "negatif",
        }:
            stop(
                f"Polaritas KPI {row['no']} tidak valid."
            )


def database_preflight():
    unit = Group.objects.filter(
        pk=UNIT_ID,
        name="BID K3L",
    ).first()

    if unit is None:
        stop("BID K3L ID=19 tidak ditemukan.")

    template = MasterTemplateKM.objects.filter(
        pk=TEMPLATE_ID
    ).first()

    if template is None:
        stop("Template KM ID=1 tidak ditemukan.")

    if getattr(template, "tahun", YEAR) != YEAR:
        stop("Template ID=1 bukan template tahun 2026.")

    masters = {
        x.kode_bagian: x
        for x in MasterBagianKM.objects.filter(
            template_id=TEMPLATE_ID,
            kode_bagian__in=SECTIONS,
        )
    }

    if set(masters) != set(SECTIONS):
        stop(
            "Master Bagian A-F tidak lengkap. "
            f"Ditemukan: {sorted(masters)}"
        )

    for code, expected_name in SECTIONS.items():
        actual = masters[code].nama_bagian.strip()

        if actual != expected_name:
            stop(
                f"Nama master bagian {code} berbeda: "
                f"{actual!r}"
            )

    existing = list(
        KontrakManajemen.objects.filter(
            unit_bisnis_id=UNIT_ID,
            tahun=YEAR,
        ).order_by("pk")
    )

    if len(existing) > 1:
        stop(
            "Terdapat lebih dari satu KM BID K3L 2026: "
            f"{[x.pk for x in existing]}"
        )

    if existing:
        km = existing[0]

        if km.judul != TITLE:
            stop(
                f"KM K3L existing ID={km.pk} memiliki judul "
                f"{km.judul!r}, bukan {TITLE!r}."
            )

        if km.template_id not in {
            None,
            TEMPLATE_ID,
        }:
            stop(
                f"KM existing menggunakan template "
                f"{km.template_id}."
            )

    return unit, template, masters, (
        existing[0] if existing else None
    )


def print_preview(existing):
    print("=" * 112)
    print(
        "SYNC KM BID K3L 2026"
        f" | {'UPDATE ID=' + str(existing.pk) if existing else 'CREATE NEW'}"
    )
    print("=" * 112)

    print()
    print("Unit     : BID K3L / ID=19")
    print("Judul    : VPK3L")
    print("Tahun    : 2026")
    print("Template : Bagian KM 2026 / ID=1")
    print("Status   : Final")
    print()

    for code, name in SECTIONS.items():
        rows = [
            x for x in KPI_DATA
            if x["bagian"] == code
        ]

        print(
            f"[{code}] {name}"
            f" | bobot={sum(x['bobot'] for x in rows):g}"
        )

        for row in rows:
            print(
                f"  {row['no']}. {row['indikator']}"
                f" | satuan={row['satuan']}"
                f" | bobot={row['bobot']:g}"
                f" | target={row['target']}"
                f" | polaritas={row['polaritas']}"
            )

    print()
    print(
        "TOTAL BOBOT REGULER:",
        sum(
            x["bobot"]
            for x in KPI_DATA
            if x["bagian"] != "F"
        ),
    )
    print(
        "COMPLIANCE:",
        "bobot=0 | target=Max -10 | nilai pengurang",
    )


def apply_sync(unit, template, masters, existing):
    with transaction.atomic():
        if existing is None:
            km = KontrakManajemen.objects.create(
                judul=TITLE,
                tahun=YEAR,
                unit_bisnis=unit,
                status=STATUS,
                template=template,
            )
        else:
            km = KontrakManajemen.objects.select_for_update().get(
                pk=existing.pk
            )

            km.judul = TITLE
            km.tahun = YEAR
            km.unit_bisnis = unit
            km.status = STATUS
            km.template = template

            km.save(
                update_fields=[
                    "judul",
                    "tahun",
                    "unit_bisnis",
                    "status",
                    "template",
                ]
            )

        bagian_map = {}

        for code, name in SECTIONS.items():
            bagian, _ = (
                BagianKontrakManajemen.objects
                .update_or_create(
                    kontrak=km,
                    kode_bagian=code,
                    defaults={
                        "nama_bagian": name,
                    },
                )
            )

            bagian_map[code] = bagian

        # Jika rerun terhadap KM hasil script ini, update berdasarkan no_urut.
        existing_numbers = set(
            ItemKontrakManajemen.objects.filter(
                kontrak=km
            ).values_list(
                "no_urut",
                flat=True,
            )
        )

        unexpected_numbers = (
            existing_numbers - set(range(1, 10))
        )

        if unexpected_numbers:
            stop(
                "KM existing mempunyai nomor KPI di luar 1-9: "
                f"{sorted(unexpected_numbers)}"
            )

        for row in KPI_DATA:
            ItemKontrakManajemen.objects.update_or_create(
                kontrak=km,
                no_urut=row["no"],
                defaults={
                    "bagian": bagian_map[row["bagian"]],
                    "master_bagian": masters[row["bagian"]],
                    "indikator_kinerja_kunci": row["indikator"],
                    "formula": row["formula"],
                    "satuan": row["satuan"],
                    "bobot": row["bobot"],
                    "target": row["target"],
                    "polaritas": row["polaritas"],
                },
            )

        # ----------------------------------------------------
        # HARD POST-CHECK
        # ----------------------------------------------------

        km.refresh_from_db()

        if km.judul != TITLE:
            stop("Judul KM post-check salah.")

        if km.unit_bisnis_id != UNIT_ID:
            stop("Unit KM post-check salah.")

        if km.tahun != YEAR:
            stop("Tahun KM post-check salah.")

        if km.template_id != TEMPLATE_ID:
            stop("Template KM post-check salah.")

        if km.status != STATUS:
            stop("Status KM post-check salah.")

        parts = BagianKontrakManajemen.objects.filter(
            kontrak=km
        )

        if parts.count() != 6:
            stop(
                f"Jumlah bagian={parts.count()}, expected 6."
            )

        items = (
            ItemKontrakManajemen.objects
            .filter(kontrak=km)
            .order_by("no_urut")
        )

        if items.count() != 9:
            stop(
                f"Jumlah KPI={items.count()}, expected 9."
            )

        if list(
            items.values_list(
                "no_urut",
                flat=True,
            )
        ) != list(range(1, 10)):
            stop("Nomor KPI post-check bukan 1-9.")

        total_regular = sum(
            x.bobot
            for x in items.exclude(
                master_bagian__kode_bagian="F"
            )
        )

        if total_regular != 100.0:
            stop(
                f"Total bobot reguler={total_regular}, "
                "expected 100."
            )

        compliance = items.get(no_urut=9)

        if (
            compliance.indikator_kinerja_kunci
            != "Compliance"
            or compliance.bobot != 0.0
            or compliance.target != "Max -10"
            or compliance.polaritas != "positif"
        ):
            stop("Compliance post-check tidak sesuai.")

        safety = items.get(no_urut=8)

        if safety.polaritas != "negatif":
            stop("Polaritas Safety Culture bukan negatif.")

        return km


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Simpan perubahan ke database.",
    )

    args = parser.parse_args()

    validate_source()

    unit, template, masters, existing = database_preflight()

    print_preview(existing)

    if not args.apply:
        print()
        print("=" * 112)
        print("DRY-RUN RESULT: CLEAN")
        print("DATABASE TIDAK DIUBAH")
        print("=" * 112)
        return

    km = apply_sync(
        unit,
        template,
        masters,
        existing,
    )

    print()
    print("=" * 112)
    print("APPLY SUCCESS")
    print(
        f"KM ID={km.pk}"
        f" | {km.judul}"
        f" | BID K3L"
        f" | KPI=9"
        f" | status={km.status}"
    )
    print("=" * 112)


if __name__ == "__main__":
    main()
