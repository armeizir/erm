from decimal import Decimal
from django.core.management.base import BaseCommand
from risk.models import RKAPItem


def d(value):
    if value in ("", "-", None):
        return None
    return Decimal(str(value).replace(".", "").replace(",", "."))


DATA = [
    ("1", "ASET TIDAK LANCAR", None, None, None, "Rp Jt", "Header"),
    ("1.1", "Aset Tetap Operasi (Netto)", "17324621", "18680994", "23090192", "Rp Jt", "Aset Tidak Lancar"),
    ("1.1.1", "Aset Tetap Operasi (Bruto)", "19268691", "18947676", "24144761", "Rp Jt", "Aset Tidak Lancar"),
    ("1.1.2", "Akumulasi Penyusutan", "-2266664", "-994534", "-2154783", "Rp Jt", "Aset Tidak Lancar"),
    ("1.1.3", "Pekerjaan Dalam Pelaksanaan", "322594", "727852", "1100215", "Rp Jt", "Aset Tidak Lancar"),
    ("1.2", "Aset Hak Guna", None, None, None, "Rp Jt", "Aset Tidak Lancar"),
    ("1.3", "Properti Investasi", None, None, None, "Rp Jt", "Aset Tidak Lancar"),
    ("1.4", "Investasi Pada Entitas Asosiasi", "409770", "413681", "462338", "Rp Jt", "Aset Tidak Lancar"),
    ("1.12", "Aset Tidak Lancar Lain", "63673", "1383763", "85410", "Rp Jt", "Aset Tidak Lancar"),
    ("1.T", "Jumlah Aset Tidak Lancar", "17798063", "20478439", "23637940", "Rp Jt", "Aset Tidak Lancar"),

    ("2", "ASET LANCAR", None, None, None, "Rp Jt", "Header"),
    ("2.1", "Kas dan Bank", "2109768", "1896988", "1618361", "Rp Jt", "Aset Lancar"),
    ("2.3", "Piutang", "523824", "565478", "653524", "Rp Jt", "Aset Lancar"),
    ("2.3.1", "Piutang Lancar", "523824", "565478", "653524", "Rp Jt", "Aset Lancar"),
    ("2.6", "Persediaan", "174203", "332218", "180810", "Rp Jt", "Aset Lancar"),
    ("2.6.1", "BBM", "19958", "40350", "9810", "Rp Jt", "Aset Lancar"),
    ("2.6.2", "Batu bara", "17818", "11861", "16833", "Rp Jt", "Aset Lancar"),
    ("2.6.5", "Persediaan Material Pemeliharaan", "136427", "280007", "154167", "Rp Jt", "Aset Lancar"),
    ("2.7", "Pajak Dibayar Di Muka", "42154", None, None, "Rp Jt", "Aset Lancar"),
    ("2.8", "Biaya Dibayar Di Muka dan Uang Muka", "35455", None, None, "Rp Jt", "Aset Lancar"),
    ("2.9", "Piutang Pihak Berelasi dan Aset Lancar Lainnya", "1234931", "2015051", "1042588", "Rp Jt", "Aset Lancar"),
    ("2.T", "Jumlah Aset Lancar", "4143443", "4809735", "3495284", "Rp Jt", "Aset Lancar"),
    ("A.T", "JUMLAH ASET", "21941506", "25288173", "27133224", "Rp Jt", "Total"),

    ("3", "EKUITAS", None, None, None, "Rp Jt", "Header"),
    ("3.1", "Modal Saham Ditempatkan dan Disetor", "2740608", "2740608", "2740608", "Rp Jt", "Ekuitas"),
    ("3.2", "Tambahan Modal Disetor", "40053", "40053", "40053", "Rp Jt", "Ekuitas"),
    ("3.3", "Saldo Laba / (Defisit)", "6555059", "7421699", "7959141", "Rp Jt", "Ekuitas"),
    ("3.4", "Komponen ekuitas lain", "3574894", "4961924", "4961924", "Rp Jt", "Ekuitas"),
    ("3.5", "Laba / (Rugi) tahun berjalan", "784415", "646255", "701320", "Rp Jt", "Ekuitas"),
    ("3.T", "Jumlah Ekuitas", "13695029", "15810540", "16403046", "Rp Jt", "Ekuitas"),

    ("4", "KEWAJIBAN JANGKA PANJANG", None, None, None, "Rp Jt", "Header"),
    ("4.2", "Pendapatan Ditangguhkan", "586188", "869365", "859834", "Rp Jt", "Kewajiban Jangka Panjang"),
    ("4.3", "Utang Jangka Panjang Interest Bearing Debt", "2249665", "1656678", "2799155", "Rp Jt", "Kewajiban Jangka Panjang"),
    ("4.4", "Kewajiban Imbalan Kerja", "312505", "292221", "318787", "Rp Jt", "Kewajiban Jangka Panjang"),
    ("4.5", "Kewajiban Jangka Panjang Lainnya", "460697", "423577", "441181", "Rp Jt", "Kewajiban Jangka Panjang"),
    ("4.T", "Jumlah Kewajiban Jangka Panjang", "4591729", "4726219", "5406997", "Rp Jt", "Kewajiban Jangka Panjang"),

    ("5", "KEWAJIBAN JANGKA PENDEK", None, None, None, "Rp Jt", "Header"),
    ("5.1", "Utang Usaha", "924694", "1625376", "1389826", "Rp Jt", "Kewajiban Jangka Pendek"),
    ("5.2", "Utang Pajak", "50337", "99127", "63954", "Rp Jt", "Kewajiban Jangka Pendek"),
    ("5.3", "Biaya masih harus dibayar", "315408", "432980", "453541", "Rp Jt", "Kewajiban Jangka Pendek"),
    ("5.4", "Uang Jaminan Langganan", "501186", "580409", "816978", "Rp Jt", "Kewajiban Jangka Pendek"),
    ("5.6", "Pendapatan Ditangguhkan", "156744", "174347", "145820", "Rp Jt", "Kewajiban Jangka Pendek"),
    ("5.7", "Utang Jangka Panjang Jatuh Tempo Interest Bearing Debt", "969976", "1376713", "1239201", "Rp Jt", "Kewajiban Jangka Pendek"),
    ("5.9", "Kewajiban Jangka Pendek Lainnya", "736402", "462461", "1213861", "Rp Jt", "Kewajiban Jangka Pendek"),
    ("5.T", "Jumlah Kewajiban Jangka Pendek", "3654748", "4751414", "5323181", "Rp Jt", "Kewajiban Jangka Pendek"),
    ("E.K.T", "EKUITAS DAN KEWAJIBAN", "21941506", "25288173", "27133224", "Rp Jt", "Total"),
]


class Command(BaseCommand):
    help = "Import RKAP Lampiran 2 Neraca Non ISAK RKAP 2026"

    def handle(self, *args, **options):
        tahun = 2026
        sumber = "BUKU RKAP 2026 PT PLN BATAM SIGN - Lampiran 2 Neraca Non ISAK"

        created = 0
        updated = 0

        for idx, (kode, sasaran, audited_2024, unaudited_2025, rkap_2026, satuan, kategori) in enumerate(DATA, start=1):
            obj, is_created = RKAPItem.objects.update_or_create(
                tahun=tahun,
                kode=kode,
                sasaran=sasaran,
                defaults={
                    "indikator": sasaran,
                    "kategori": kategori,
                    "subkategori": "Lampiran 2 Neraca Non ISAK",
                    "periode": "Lampiran",
                    "target": d(rkap_2026),
                    "satuan": satuan,
                    "nilai_audited_2024": d(audited_2024),
                    "nilai_unaudited_2025": d(unaudited_2025),
                    "sumber_dokumen": sumber,
                    "halaman_sumber": 190,
                    "urutan": idx,
                    "aktif": True,
                },
            )

            if is_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Import selesai. Created: {created}, Updated: {updated}"
        ))
