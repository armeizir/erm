from __future__ import annotations

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from risk.models import RKAPItem

YEAR = 2026
SRC_TARGET = "Target RKAP.pdf"
SRC_LR = "LR RKAP.pdf"

TARGET_SECTIONS = [('TGT.MAKRO', 'Makro Ekonomi', [('TGT.MAKRO.01', 'Pertumbuhan Ekonomi', '5.40', '%', 'NETRAL'), ('TGT.MAKRO.02', 'Inflasi (YoY)', '2.50', '%', 'NETRAL'), ('TGT.MAKRO.03', 'Volume Penjualan', '5.75', 'TWh', 'POSITIF'), ('TGT.MAKRO.04', 'Nilai Tukar', '16500', 'Rp/USD', 'NETRAL'), ('TGT.MAKRO.05', 'Harga Batubara Rata-rata', '1049', 'Rp/kg', 'NEGATIF')]), ('TGT.POSTUR', 'Asumsi Postur RKAP 2026', [('TGT.POSTUR.01', 'Kurs USD', '16500', 'Rp/USD', 'NETRAL'), ('TGT.POSTUR.02', 'Harga Jual Tertimbang Batam-Bintan', '1640', 'Rp/kWh', 'POSITIF'), ('TGT.POSTUR.03', 'Harga Gas Tertimbang', '7.47', 'USD/MMBTU', 'NEGATIF'), ('TGT.POSTUR.04', 'Harga Batu Bara', '1049000', 'Rp/Mton', 'NEGATIF'), ('TGT.POSTUR.05', 'Harga BBM HSD', '11927', 'Rp/Liter', 'NEGATIF'), ('TGT.POSTUR.06', 'Harga BBM MFO', '7537', 'Rp/Liter', 'NEGATIF'), ('TGT.POSTUR.07', 'Pertumbuhan Penjualan Batam', '15.67', '%', 'POSITIF'), ('TGT.POSTUR.08', 'Biaya Operasi', '10106709000000', 'Rp', 'NEGATIF'), ('TGT.POSTUR.09', 'Susut Jaringan (T&D)', '2.90', '%', 'NEGATIF'), ('TGT.POSTUR.10', 'Pertumbuhan Penjualan Batam - Bintan', '6.12', '%', 'POSITIF'), ('TGT.POSTUR.11', 'Penambahan Pelanggan', '13055', 'Pelanggan', 'POSITIF'), ('TGT.POSTUR.12', 'Penambahan KVA Tersambung', '203582', 'kVA', 'POSITIF'), ('TGT.POSTUR.13', 'Disburse Investasi', '3113975000000', 'Rp', 'NETRAL'), ('TGT.POSTUR.14', 'Dana Internal PLN Batam', '1964629000000', 'Rp', 'NETRAL'), ('TGT.POSTUR.15', 'Pendanaan SHL/Lainnya', '1149346000000', 'Rp', 'NETRAL')]), ('TGT.PARAM', 'Parameter Internal', [('TGT.PARAM.01', 'MWh Jual Batam', '4574164', 'MWh', 'POSITIF'), ('TGT.PARAM.02', 'MWh Jual Interkoneksi', '781161', 'MWh', 'POSITIF'), ('TGT.PARAM.03', 'MWh Jual off grid', '3408534', 'MWh', 'POSITIF'), ('TGT.PARAM.04', 'MWh Jual Listrik MPP', '846463', 'MWh', 'POSITIF'), ('TGT.PARAM.05', 'Pendapatan Penjualan Tenaga Listrik Batam', '7101526000000', 'Rp', 'POSITIF'), ('TGT.PARAM.06', 'Pendapatan Penjualan Interkoneksi', '1406090000000', 'Rp', 'POSITIF'), ('TGT.PARAM.07', 'Pendapatan Penjualan MPP', '1437406000000', 'Rp', 'POSITIF')]), ('TGT.PEND', 'Pendapatan Penjualan Tenaga Listrik', [('TGT.PEND.01', 'Pendapatan Penjualan Tenaga Listrik Batam', '7951210000000', 'Rp', 'POSITIF'), ('TGT.PEND.02', 'Pendapatan Penjualan Tenaga Listrik Interkoneksi', '1476759000000', 'Rp', 'POSITIF'), ('TGT.PEND.03', 'Pendapatan Penjualan MPP', '1346855000000', 'Rp', 'POSITIF'), ('TGT.PEND.04', 'Total Pendapatan', '10774824000000', 'Rp', 'POSITIF')]), ('TGT.BEYOND', 'Pendapatan Usaha Lainnya (Beyond kWh)', [('TGT.BEYOND.01', 'Pendapatan Usaha Lainnya (Beyond kWh)', '149613000000', 'Rp', 'POSITIF'), ('TGT.BEYOND.02', 'Pendapatan Usaha Lainnya (Internal)', '104896000000', 'Rp', 'POSITIF'), ('TGT.BEYOND.03', 'Drups Lirik', '39858000000', 'Rp', 'POSITIF'), ('TGT.BEYOND.04', 'OM PK52, Maleo, EPCI', '65038000000', 'Rp', 'POSITIF'), ('TGT.BEYOND.05', 'Pendapatan Usaha Lainnya (Eksternal)', '44717000000', 'Rp', 'POSITIF'), ('TGT.BEYOND.06', 'Beyond kWh', '44717000000', 'Rp', 'POSITIF')]), ('TGT.FIN', 'Postur Keuangan', [('TGT.FIN.01', 'Pendapatan Usaha', '10977367000000', 'Rp', 'POSITIF'), ('TGT.FIN.02', 'Beban Usaha', '10106709000000', 'Rp', 'NEGATIF'), ('TGT.FIN.03', 'L/R Usaha', '870658000000', 'Rp', 'POSITIF')]), ('TGT.RATIO', 'Rasio Keuangan', [('TGT.RATIO.01', 'ROA', '2.58', '%', 'POSITIF'), ('TGT.RATIO.02', 'ROE', '4.28', '%', 'POSITIF'), ('TGT.RATIO.03', 'EBITDA Margin', '13.81', '%', 'POSITIF'), ('TGT.RATIO.04', 'Current Ratio', '66.00', '%', 'POSITIF'), ('TGT.RATIO.05', 'Profit Margin', '6.39', '%', 'POSITIF')]), ('TGT.INV.AIAKI', 'AI AKI', [('TGT.INV.AIAKI.01', 'KIT', '8799064', 'Rp Jt', 'NETRAL'), ('TGT.INV.AIAKI.02', 'TRANS & GI', '1677585', 'Rp Jt', 'NETRAL'), ('TGT.INV.AIAKI.03', 'Dist', '975561', 'Rp Jt', 'NETRAL'), ('TGT.INV.AIAKI.04', 'Sarana & lainnya', '2393', 'Rp Jt', 'NETRAL'), ('TGT.INV.AIAKI.05', 'Total AI AKI', '11454603', 'Rp Jt', 'NETRAL')]), ('TGT.INV', 'Investasi', [('TGT.INV.01', 'KIT', '1809775', 'Rp Jt', 'NETRAL'), ('TGT.INV.02', 'TRANS & GI', '652357', 'Rp Jt', 'NETRAL'), ('TGT.INV.03', 'Dist', '615086', 'Rp Jt', 'NETRAL'), ('TGT.INV.04', 'Sarana & lainnya', '36757', 'Rp Jt', 'NETRAL'), ('TGT.INV.05', 'Total Investasi', '3113975', 'Rp Jt', 'NETRAL')]), ('TGT.BEBANLAIN', 'Beban Lain', [('TGT.BEBANLAIN.01', 'Penghasilan Bunga', '48767000000', 'Rp', 'POSITIF'), ('TGT.BEBANLAIN.02', 'Beban Bunga Financial Leased', '-41258000000', 'Rp', 'NEGATIF'), ('TGT.BEBANLAIN.03', 'Beban Bunga Debt Financing - SHL', '-68287000000', 'Rp', 'NEGATIF'), ('TGT.BEBANLAIN.04', 'Lain-lain bersih', '41088000000', 'Rp', 'POSITIF'), ('TGT.BEBANLAIN.05', 'Beban Selisih Kurs', None, 'Rp', 'NEGATIF')]), ('TGT.BIOP', 'Biaya Operasi', [('TGT.BIOP.01', 'Biaya Gas', '5183960000000', 'Rp', 'NEGATIF'), ('TGT.BIOP.02', 'Biaya Batubara', '564519000000', 'Rp', 'NEGATIF'), ('TGT.BIOP.03', 'Biaya BBM', '5771000000', 'Rp', 'NEGATIF'), ('TGT.BIOP.04', 'Biaya Pelumas', '5354000000', 'Rp', 'NEGATIF'), ('TGT.BIOP.05', 'Biaya Pembelian Tenaga Listrik', '2102086000000', 'Rp', 'NEGATIF'), ('TGT.BIOP.06', 'Biaya Sewa Non AHG', '8520000000', 'Rp', 'NEGATIF'), ('TGT.BIOP.07', 'Sewa IMBT', '48248000000', 'Rp', 'NEGATIF'), ('TGT.BIOP.09', 'Biaya Administrasi', '170613000000', 'Rp', 'NEGATIF'), ('TGT.BIOP.10', 'Biaya Kepegawaian', '370200000000', 'Rp', 'NEGATIF'), ('TGT.BIOP.11', 'Beban Manfaat Pekerja Perusahaan (PSAK 24)', '50154000000', 'Rp', 'NEGATIF'), ('TGT.BIOP.12', 'Biaya Produksi', '239597000000', 'Rp', 'NEGATIF'), ('TGT.BIOP.13', 'Pajak', None, 'Rp', 'NEGATIF'), ('TGT.BIOP.14', 'Beban Emisi', '6761000000', 'Rp', 'NEGATIF'), ('TGT.BIOP.15', 'Penyusutan aset hak guna', '54011000000', 'Rp', 'NEGATIF'), ('TGT.BIOP.16', 'Penyusutan aset tetap', '170613000000', 'Rp', 'NEGATIF'), ('TGT.BIOP.17', 'Biaya Produksi (Khusus AP & Pusat-Pusat)', '239597000000', 'Rp', 'NEGATIF')]), ('TGT.PRIMER', 'Energi Primer', [('TGT.PRIMER.01', 'Biaya Batubara', '564519000000', 'Rp', 'NEGATIF'), ('TGT.PRIMER.02', 'Volume Batubara', '538149', 'Mton', 'NETRAL'), ('TGT.PRIMER.03', 'Harga Batubara', '1049001.30', 'Rp/Mton', 'NEGATIF'), ('TGT.PRIMER.04', 'Biaya Gas', '5183960000000', 'Rp', 'NEGATIF'), ('TGT.PRIMER.05', 'Harga Tertimbang Gas', '7.47', 'USD/MMBTU', 'NEGATIF'), ('TGT.PRIMER.06', 'Volume Gas', '42082', 'BBTU', 'NETRAL'), ('TGT.PRIMER.07', 'Volume Gas', '42082000', 'MMBTU', 'NETRAL'), ('TGT.PRIMER.08', 'Biaya Pembelian Tenaga Listrik', '2102086000000', 'Rp', 'NEGATIF')]), ('TGT.IKU', 'Indikator Kinerja Utama (RKM PLNB)', [('TGT.IKU.01', 'EBIT', '893.77', 'Rp M', 'POSITIF'), ('TGT.IKU.02', 'BPP non MPP', '1489.16', 'Rp/kWh', 'NEGATIF'), ('TGT.IKU.03', 'SFC', '8943.07', 'BTU/kWh', 'NEGATIF'), ('TGT.IKU.04', 'EAF', None, '%', 'POSITIF'), ('TGT.IKU.05', 'EFOR', None, '%', 'NEGATIF'), ('TGT.IKU.06', 'Optimalisasi Kesiapan Pasokan Pembangkit', '85.62', '%', 'POSITIF'), ('TGT.IKU.07', 'SAIDI', '130.24', 'Menit/plg', 'NEGATIF'), ('TGT.IKU.08', 'SAIFI', '2.45', 'Kali/plg', 'NEGATIF'), ('TGT.IKU.09', 'Matlev Sustainability', '3.10', 'Level', 'POSITIF'), ('TGT.IKU.10', 'Electricity Losses', '3.35', '%', 'NEGATIF'), ('TGT.IKU.11', 'Produktivitas Pegawai dan Penguatan Budaya', '100', '%', 'POSITIF'), ('TGT.IKU.12', 'Lost Time Injury Frequency Rate', '0.33', 'Indeks/1 juta jam kerja', 'NEGATIF'), ('TGT.IKU.13', 'EAF MPP', None, '%', 'POSITIF'), ('TGT.IKU.14', 'EFOR MPP', None, '%', 'NEGATIF'), ('TGT.IKU.15', 'Pendapatan MPP', '1346855000000', 'Rp', 'POSITIF')])]
LR_SECTIONS = [('LR.1', 'Produksi dan Penjualan', [('LR.1.1', 'GWH Loko Sentral (Bruto Production)', '4432', '5044', '5654', 'GWh', 'POSITIF', 'DATA'), ('LR.1.2', 'GWH Penjualan Tenaga Listrik', '4276', '5047', '5748', 'GWh', 'POSITIF', 'DATA'), ('LR.1.3', 'Pertumbuhan Penjualan', '12', '18', '14.0', '%', 'POSITIF', 'DATA'), ('LR.1.4', 'Susut Jaringan', '2.75', '2.59', '2.90', '%', 'NEGATIF', 'DATA'), ('LR.1.5', 'Harga Jual Rata-rata', '1517', '1611', '1640', 'Rp/kWh', 'POSITIF', 'DATA'), ('LR.1.6', 'BPP', '1529', '1616', '1589', 'Rp/kWh', 'NEGATIF', 'DATA')]), ('LR.2', 'Pendapatan Usaha', [('LR.2.0', 'Pendapatan Usaha', '8707506', '10418383', '10977367', 'Rp Jt', 'POSITIF', 'SUBTOTAL'), ('LR.2.1', 'Penjualan Tenaga Listrik', '5246697', '6685935', '7951210', 'Rp Jt', 'POSITIF', 'DATA'), ('LR.2.2', 'Subsidi Listrik Pemerintah', None, None, None, 'Rp Jt', 'NETRAL', 'DATA'), ('LR.2.3', 'Penyambungan Pelanggan', '30286', '45475', '52929', 'Rp Jt', 'POSITIF', 'DATA'), ('LR.2.4', 'Pendapatan Kompensasi', None, None, None, 'Rp Jt', 'NETRAL', 'DATA'), ('LR.2.5', 'Lain-Lain', '3430523', '3686973', '2973228', 'Rp Jt', 'POSITIF', 'SUBTOTAL'), ('LR.2.5.1', 'Pendapatan Internal', '3390708', '3630221', '2928511', 'Rp Jt', 'POSITIF', 'DATA'), ('LR.2.5.2', 'Pendapatan External (Beyond kWh)', '39815', '56752', '44717', 'Rp Jt', 'POSITIF', 'DATA')]), ('LR.3', 'Biaya Usaha', [('LR.3.0', 'Biaya Usaha', '7644385', '9610700', '10106708', 'Rp Jt', 'NEGATIF', 'SUBTOTAL'), ('LR.3.1', 'Bahan Bakar dan Pelumas', '3622444', '4776306', '5759604', 'Rp Jt', 'NEGATIF', 'SUBTOTAL'), ('LR.3.1.1', 'Bahan Bakar Minyak dan Bahan Bakar Nabati', '17317', '13145', '5771', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.1.2', 'Minyak Pelumas', '4527', '3204', '5354', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.1.3', 'Gas Alam', '3040064', '4128561', '5183960', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.1.4', 'Batu bara & Gasifikasi Batu Bara', '560536', '631396', '564519', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.1.5', 'Panas Bumi & Alternatif', None, None, None, 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.1.6', 'Air', None, None, None, 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.1.7', 'Biomass', None, None, None, 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.2', 'Pembelian Tenaga Listrik & Sewa Pembangkit', '1780481', '2032463', '2102086', 'Rp Jt', 'NEGATIF', 'SUBTOTAL'), ('LR.3.2.1', 'Pembelian Tenaga Listrik IPP dan Excess Power', '1780481', '2032463', '2102086', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.2.2', 'Pembelian Transfer Tenaga Listrik', None, None, None, 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.3', 'Sewa', '210424', '413947', '56768', 'Rp Jt', 'NEGATIF', 'SUBTOTAL'), ('LR.3.3.1', 'Sewa Pembangkit', '210424', '409839', '48248', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.3.2', 'Sewa Non Hak Aset Guna', None, '4108', '8520', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.4', 'Beban Emisi', None, None, '6761', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.5', 'Biaya KWH Import (Untuk Anak Perusahaan)', None, None, None, 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.6', 'Pemeliharaan', '605761', '898594', '784229', 'Rp Jt', 'NEGATIF', 'SUBTOTAL'), ('LR.3.6.1', 'Material', '163144', '180999', '115630', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.6.2', 'Jasa Borongan', '442617', '717595', '668599', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.7', 'Kepegawaian', '356735', '384637', '370200', 'Rp Jt', 'NEGATIF', 'SUBTOTAL'), ('LR.3.7.1', 'Dalam Bentuk Kompensasi Pegawai', '196063', '209935', '191808', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.7.2', 'Dalam Bentuk Manfaat Pegawai', '148234', '164589', '164686', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.7.3', 'Dalam Bentuk Diklat dan Lainnya', '12438', '10113', '13706', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.8', 'Penyusutan Aset Tetap', '497207', '582126', '562839', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.9', 'Penyusutan Aset Hak Guna', '33965', '40801', '54011', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.10', 'Administrasi', '152112', '179852', '170613', 'Rp Jt', 'NEGATIF', 'SUBTOTAL'), ('LR.3.10.1', 'Administrasi Niaga', '31192', '35769', '42805', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.10.2', 'Administrasi Umum', '120920', '144083', '127808', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.3.11', 'Biaya Produksi (Khusus AP & Pusat-Pusat)', '385256', '301974', '239597', 'Rp Jt', 'NEGATIF', 'DATA')]), ('LR.4', 'Laba (Rugi) Usaha', [('LR.4.0', 'Laba (Rugi) Usaha', '1063121', '807683', '870659', 'Rp Jt', 'POSITIF', 'SUBTOTAL')]), ('LR.5', 'Penghasilan (Beban) Lain-Lain', [('LR.5.0', 'Penghasilan (Beban) Lain-Lain', '-54136', '35689', '28470', 'Rp Jt', 'POSITIF', 'SUBTOTAL'), ('LR.5.1', 'Pendapatan Bunga', '85642', '88281', '74501', 'Rp Jt', 'POSITIF', 'DATA'), ('LR.5.2', 'Beban Bunga dan Keuangan', '-164743', '-149996', '-109545', 'Rp Jt', 'NEGATIF', 'SUBTOTAL'), ('LR.5.2.1', 'Beban Bunga dan Keuangan', '-103087', '-99776', '-68287', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.5.2.2', 'Beban Bunga Sewa Aset Hak Guna', '-61656', '-50220', '-41258', 'Rp Jt', 'NEGATIF', 'DATA'), ('LR.5.3', 'Laba (Rugi) Kurs Mata Uang Asing - Bersih', '-85522', '-67897', '0', 'Rp Jt', 'POSITIF', 'DATA'), ('LR.5.4', 'Lain-lain bersih', '110487', '165301', '63514', 'Rp Jt', 'POSITIF', 'DATA')]), ('LR.6', 'Laba (Rugi) Sebelum Pajak', [('LR.6.0', 'Laba (Rugi) Sebelum Pajak', '1008985', '843372', '899129', 'Rp Jt', 'POSITIF', 'SUBTOTAL')]), ('LR.7', 'Pajak Tangguhan dan Pajak Kini AP', [('LR.7.0', 'Pajak Tangguhan dan Pajak Kini AP', '-197810', '-197809', '-197808', 'Rp Jt', 'NEGATIF', 'DATA')]), ('LR.8', 'Laba (Rugi) Setelah Pajak', [('LR.8.0', 'Laba (Rugi) Setelah Pajak', '811175', '645563', '701321', 'Rp Jt', 'POSITIF', 'SUBTOTAL')]), ('LR.9', 'Laba (Rugi) Luar Biasa', [('LR.9.0', 'Laba (Rugi) Luar Biasa', None, None, None, 'Rp Jt', 'NETRAL', 'DATA')]), ('LR.10', 'Laba (Rugi) Bersih', [('LR.10.0', 'Laba (Rugi) Bersih', '811175', '645563', '701321', 'Rp Jt', 'POSITIF', 'SUBTOTAL')])]

AMBIGUOUS_TARGET_NOTES = [
    "Biaya HAR pada Target RKAP menampilkan dua angka: Rp783.230.000.000 dan Rp784.230.000.000; belum diimpor sebagai target tunggal.",
    "Target EAF, EFOR, EAF MPP, dan EFOR MPP kosong pada sumber; item dibuat dengan target kosong.",
]

def D(value):
    if value in (None, "", "-"):
        return None
    return Decimal(str(value))

def ensure_root(kode, sasaran, jenis_rkap, source, order):
    obj, created = RKAPItem.objects.update_or_create(
        tahun=YEAR, kode=kode, sasaran=sasaran,
        defaults={
            "jenis_rkap": jenis_rkap,
            "tipe_baris": "GROUP",
            "polaritas": "NETRAL",
            "parent": None,
            "indikator": sasaran,
            "kategori": sasaran,
            "subkategori": "",
            "periode": "Tahunan" if jenis_rkap == "TARGET" else "Lampiran",
            "bulan": None,
            "target": None,
            "satuan": None,
            "nilai_audited_2024": None,
            "nilai_unaudited_2025": None,
            "sumber_dokumen": source,
            "urutan": order,
            "aktif": True,
        },
    )
    return obj, created

def upsert_target(parent, row, order):
    kode, sasaran, target, satuan, polaritas = row
    return RKAPItem.objects.update_or_create(
        tahun=YEAR, kode=kode, sasaran=sasaran,
        defaults={
            "jenis_rkap": "TARGET", "tipe_baris": "DATA", "polaritas": polaritas,
            "parent": parent, "indikator": sasaran, "kategori": parent.sasaran,
            "subkategori": "", "periode": "Tahunan", "bulan": None,
            "target": D(target), "satuan": satuan,
            "nilai_audited_2024": None, "nilai_unaudited_2025": None,
            "sumber_dokumen": SRC_TARGET, "urutan": order, "aktif": True,
        },
    )

def upsert_lr(parent, row, order):
    kode, sasaran, audited, unaudited, target, satuan, polaritas, tipe_baris = row
    candidate_parent = parent
    parts = kode.split(".")
    if len(parts) > 2:
        for cut in range(len(parts)-1, 1, -1):
            pcode = ".".join(parts[:cut])
            p = RKAPItem.objects.filter(tahun=YEAR, jenis_rkap="LABA_RUGI", kode=pcode).order_by("id").first()
            if p:
                candidate_parent = p
                break
    return RKAPItem.objects.update_or_create(
        tahun=YEAR, kode=kode, sasaran=sasaran,
        defaults={
            "jenis_rkap": "LABA_RUGI", "tipe_baris": tipe_baris, "polaritas": polaritas,
            "parent": candidate_parent, "indikator": sasaran, "kategori": parent.sasaran,
            "subkategori": candidate_parent.sasaran if candidate_parent != parent else "",
            "periode": "Lampiran", "bulan": None, "target": D(target), "satuan": satuan,
            "nilai_audited_2024": D(audited), "nilai_unaudited_2025": D(unaudited),
            "sumber_dokumen": SRC_LR, "urutan": order, "aktif": True,
        },
    )

class Command(BaseCommand):
    help = "Import Phase 2 RKAP 2026 (Target/Parameter + Laba Rugi). Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument("--scope", choices=["all","target","lr"], default="all")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--relink-price-metric", action="store_true")

    def handle(self, *args, **options):
        scope = options["scope"]
        apply_changes = options["apply"]
        relink = options["relink_price_metric"]
        created = updated = relinked = 0

        with transaction.atomic():
            if scope in {"all","target"}:
                for sec_order, (root_code, root_name, rows) in enumerate(TARGET_SECTIONS, start=1):
                    root, is_created = ensure_root(root_code, root_name, "TARGET", SRC_TARGET, sec_order*1000)
                    created += int(is_created); updated += int(not is_created)
                    for row_order, row in enumerate(rows, start=1):
                        _, is_created = upsert_target(root, row, sec_order*1000 + row_order)
                        created += int(is_created); updated += int(not is_created)

            if scope in {"all","lr"}:
                for sec_order, (root_code, root_name, rows) in enumerate(LR_SECTIONS, start=1):
                    root, is_created = ensure_root(root_code, root_name, "LABA_RUGI", SRC_LR, 20000 + sec_order*1000)
                    created += int(is_created); updated += int(not is_created)
                    for row_order, row in enumerate(rows, start=1):
                        _, is_created = upsert_lr(root, row, 20000 + sec_order*1000 + row_order)
                        created += int(is_created); updated += int(not is_created)

            if relink:
                from corporate_risk.models import RiskMetric
                target_item = RKAPItem.objects.filter(
                    tahun=YEAR, jenis_rkap="LABA_RUGI", kode="LR.1.5",
                    sasaran="Harga Jual Rata-rata"
                ).first()
                if target_item:
                    metrics = RiskMetric.objects.filter(name__iexact="Realisasi Harga Jual Rata-rata")
                    relinked = metrics.count()
                    metrics.update(rkap_item=target_item)
                    self.stdout.write(
                        f"RiskMetric Harga Jual Rata-rata -> RKAP ID {target_item.id} "
                        f"({target_item.target} {target_item.satuan}); rows={relinked}"
                    )
                else:
                    self.stdout.write(self.style.WARNING("Relink dilewati: LR.1.5 belum tersedia."))

            if not apply_changes:
                transaction.set_rollback(True)

        mode = "APPLY" if apply_changes else "DRY-RUN/ROLLBACK"
        self.stdout.write(self.style.SUCCESS(
            f"{mode}: scope={scope}; created={created}; updated={updated}; relinked={relinked}"
        ))
        if scope in {"all","target"}:
            for note in AMBIGUOUS_TARGET_NOTES:
                self.stdout.write(self.style.WARNING(note))
