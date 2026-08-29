#!/usr/bin/env python3
"""
IMPORT RKM SETPER — JULI 2026 V1 SAFE

Sumber authoritative:
  Copy of Laporan KM SM II s.d Juli 2026_.xlsx
  Sheet: "3. RKM"
  Header: RENCANA KERJA MANAJEMEN (RKM) SEKPER/KSPI/VP/SM
  Tahun: 2026
  Source SHA256:
    98dc87d66fd904f2f788663741473e17254729a02af061cd91c94120821f8991

Tujuan:
- Membuat RKM SETPER periode Juli 2026 dari 16 baris KPI pada sheet "3. RKM".
- Menggunakan KM SETPER 2026 yang SUDAH ADA sebagai master.
- Tidak mengubah/relabel KMItem existing.
- KPI RKM yang tidak mempunyai anchor unik pada KM dibuat sebagai
  technical bridge ItemKontrakManajemen dengan bobot 0.
- Duplicate source KPI "Pengelolaan Komunikasi & TJSL" pada kategori B
  memakai bridge tersendiri agar constraint one-RKMItem-per-KMItem tetap valid.
- Kolom M:X (Rencana Realisasi Jan-Dec) pada source kosong; tidak diisi dengan tebakan.
- Kolom Jumlah, % Capaian, Realisasi Anggaran, Hasil Analisa juga kosong;
  tetap kosong.
- Anggaran diimpor sesuai angka source pada kolom "Anggaran (Rp Ribu)".
- Default = DRY RUN transactional rollback.
- --apply = backup SQLite lalu commit.

LOCAL:
  python risk/scripts/import_rkm_setper_juli_2026_v1_safe.py

PRODUCTION:
  PYTHONPATH=/home/adminsvr/erm \
  DJANGO_SETTINGS_MODULE=riskproject.settings.prod \
  python risk/scripts/import_rkm_setper_juli_2026_v1_safe.py

APPLY:
  ... import_rkm_setper_juli_2026_v1_safe.py --apply
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Local-first. Production can override this environment variable explicitly.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "riskproject.settings.dev")

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
RKM_TITLE = "RKM SETPER Juli 2026"
SOURCE_NAME = "Copy of Laporan KM SM II s.d Juli 2026_.xlsx"
SOURCE_SHEET = "3. RKM"
SOURCE_SHA256 = "98dc87d66fd904f2f788663741473e17254729a02af061cd91c94120821f8991"

# Candidate unit labels because legacy data sometimes uses SEKPER while newer
# documents use SETPER.
UNIT_ALIASES = (
    "SETPER",
    "SEKPER",
    "BID SETPER",
    "BID SEKPER",
    "BIDANG SETPER",
    "BIDANG SEKPER",
)

SECTION_NAMES = {
    "A": "Nilai Ekonomi dan Sosial Untuk Indonesia",
    "B": "Pelanggan",
    "C": "Bisnis Proses Internal",
    "D": "Pengembangan dan Lingkungan",
    "E": "Kepatuhan",
}


def D(value):
    if value in (None, ""):
        return None
    return Decimal(str(value))


SOURCE_ROWS = [
    # global_no, source_row, section, section_no, KPI, unit, target,
    # initiative, program, risk, mitigation, action, budget, target_accum,
    # target_accum_unit, PIC, mapping-key

    {
        "no": 1, "source_row": 8, "section": "A", "section_no": 1,
        "kpi": "Pengelolaan Komunikasi & TJSL",
        "unit": "%", "target": "SMT I = 52\nSMT II = 100",
        "initiative": """1. Optimalisasi alokasi biaya TJSL berdasarkan prioritas strategis (TPB) dan kebutuhan masyarakat.
2. Penerapan perencanaan dan penganggaran berbasis data.
3. Peningkatan kontrol dan transparansi penggunaan anggaran TJSL.
4. Integrasi program TJSL dengan program bisnis dan operasional PLN Batam (shared value).
5. Penguatan tata kelola, evaluasi, dan akuntabilitas pelaporan TJSL.""",
        "program": """1. Penyusunan RKA TJSL yang berbasis prioritas strategis dan TPB.
2. Digitalisasi proses perencanaan, verifikasi, dan pelaporan biaya TJSL.
3. Pemetaan kebutuhan masyarakat dan stakeholder engagement secara berkala.
4. Penilaian efektivitas dan dampak program melalui monitoring & evaluation (Monev).
5. Audit internal TJSL.
6. Kolaborasi dengan pemerintah daerah, lembaga pendidikan, UMKM, dan komunitas lokal.""",
        "risk": """1. Penyaluran Anggaran TJSL yang tidak tepat sasaran
2. Risiko pembengkakan biaya atau penggunaan anggaran tidak efisien
3. Risiko ketidaksesuaian dengan pedoman TJSL
4. Risiko rendahnya dampak program terhadap reputasi perusahaan
5. Risiko keterlambatan eksekusi dan realisasi anggaran""",
        "mitigation": """1. Penguatan SOP perencanaan dan verifikasi anggaran.
2. Review bulanan realisasi dan deviasi anggaran TJSL.
3. Penetapan kriteria ketat pemilihan program (selective program prioritization).
4. Mekanisme approval berjenjang dengan pengawasan fungsi keuangan & SPI.
5. Penyusunan dashboard kinerja TJSL untuk monitoring real time.
6. Audit berkala dan evaluasi dampak berbasis indikator output–outcome.""",
        "action": """1. Review RKA TJSL dan penentuan prioritas program
2. Penetapan KPI & baseline anggaran
3. Pemetaan kebutuhan (community needs assessment)
4. Penandatanganan MoU/PKS dengan mitra konsultan TJSL
5. Pelaksanaan program TJSL secara bertahap
6. Pengendalian biaya & verifikasi pembayaran.
7. Monitoring & evaluasi program
8. Audit internal anggaran TJSL.
9. Penyusunan laporan TJSL
10. Evaluasi KPI & penyusunan perbaikan untuk tahun berikutnya""",
        "budget": D("7500000"),
        "target_accum": "SMT I = 52\nSMT II = 100",
        "target_accum_unit": None,
        "pic": "MAN KOM",
        "mapping": "communication_tjsl",
    },
    {
        "no": 2, "source_row": 9, "section": "A", "section_no": 2,
        "kpi": "Optimalisasi Biaya Operasi",
        "unit": "%", "target": "100",
        "initiative": "Optimalisasi Biaya Operasi untuk menekan Biaya Pokok Penyediaan PT PLN Batam",
        "program": "Memastikan realisasi penggunaan anggaran operasi tidak melampaui target/pagu yang telah ditetapkan.",
        "risk": "Realisasi Biaya Operasi melampaui Pagu",
        "mitigation": """1. Memastikan penggunaan anggaran operasi sesuai dengan program kerja yang telah ditetapkan.
2. Melakukan monitoring penggunaan anggaran operasi setiap bulannya
3. Melakukan evaluasi atas rencana penggunaan anggaran operasi dengan memperhatikan tingkat urgensi""",
        "action": """1. Optimalisasi penggunaan Anggaran Operasi untuk pekerjaan pada sub bidang Hukum
2. Optimalisasi penggunaan Anggaran Operasi untuk pekerjaan pada sub bidang Sekretariat
3. Optimalisasi penggunaan Anggaran Operasi untuk pekerjaan pada sub bidang Komunikasi""",
        "budget": D("7655000"), "target_accum": "1",
        "target_accum_unit": None, "pic": "SEKPER",
        "mapping": "bridge",
    },

    {
        "no": 3, "source_row": 11, "section": "B", "section_no": 1,
        "kpi": "Pengelolaan Komunikasi & TJSL",
        "unit": "%", "target": "100",
        "initiative": """1. Membangun komunikasi korporat yang terpadu (integrated corporate communication) untuk memperkuat citra dan reputasi PLN Batam.
2. Optimalisasi media internal & eksternal untuk memastikan pesan perusahaan tersampaikan secara konsisten.
3. Memperkuat program TJSL yang tepat sasaran, berbasis kebutuhan masyarakat, dan selaras SDGs.
4. Mewujudkan transparansi dan akuntabilitas TJSL melalui pelaporan yang terukur dan sesuai ketentuan.
5. Strategi manajemen isu dan krisis untuk meminimalkan risiko reputasi secara real-time.
6. Kolaborasi lintas lembaga, pemerintah, stakeholder sosial, dan komunitas untuk memperluas dampak komunikasi dan TJSL.
7. Digitalisasi komunikasi dan TJSL (dashboard monitoring, social listening, pelaporan digital).""",
        "program": """A. Pengelolaan Komunikasi
1.Penyusunan Corporate Communication Plan 2026 (tema, prioritas narasi, kanal).
2. Pengelolaan media sosial korporat (Instagram, Facebook, TikTok, X).
3. Penyusunan press release, media briefing, dan hubungan dengan jurnalis.
4. Pengelolaan website & kanal informasi pelanggan.
5. Dokumentasi foto/video seluruh kegiatan PLN Batam.
6. Social listening & analisis sentimen publik.
7. Manajemen isu & komunikasi krisis (SOP + tim respon cepat).
8. Pengelolaan branding visual: spanduk, infografis, corporate design.""",
        "risk": """1. Isu negatif (gangguan listrik, tarif, pelayanan) menyebar cepat dan tidak tertangani.
2. Pemberitaan media tidak akurat akibat minimnya klarifikasi.
3. Engagement digital rendah karena konten tidak sesuai tren atau kebutuhan publik.
4. Keterbatasan SDM kreatif untuk produksi konten berkualitas.
5. Ketidakteraturan pesan komunikasi antar unit yang berdampak pada inkonsistensi informasi.""",
        "mitigation": """1. Menetapkan SOP manajemen isu & krisis dan tim respon cepat 24/7.
2. Memperkuat hubungan media melalui media gathering dan press update berkala.
3. Menyusun content planning tahunan + weekly insight review.
4. Pelatihan internal: copywriting, digital campaign, fotografi & videografi.
5. Penerapan satu pintu informasi agar semua pernyataan resmi terkoordinasi.""",
        "action": """1. Menyusun Corporate Communication Plan & Masterplan TJSL 2026
2. Menyusun kalender konten digital + narasi prioritas PLN Batam
3. Manajemen media sosial (IG, FB, TikTok, X) dan social listening
4. Media gathering & publikasi strategis
5. Penerapan SOP manajemen isu & krisis
6. Pelaksanaan program TJSL
7. Dokumentasi & publikasi program TJSL
8. Evaluasi indikator dampak TJSL (social impact assessment)
9. Penyusunan laporan tahunan TJSL sesuai POJK & SDGs
10. Evaluasi KPI komunikasi & TJSL""",
        "budget": D("9370000"), "target_accum": "1",
        "target_accum_unit": None, "pic": "MAN KOM",
        # Duplicate of source no.1 but a separate RKM row/category. Constraint
        # requires a distinct technical km_item.
        "mapping": "bridge",
    },
    {
        "no": 4, "source_row": 12, "section": "B", "section_no": 2,
        "kpi": "Koordinasi Antar Lembaga dan Stakeholder PLN Batam",
        "unit": "%", "target": "100",
        "initiative": """1. Penguatan hubungan kelembagaan dengan pemangku kepentingan strategis (Pemerintah Daerah, OPD, Otoritas KPBPB, DPRD, Keamanan, Media, Pelanggan besar).
2. Penyelarasan komunikasi korporat melalui kanal formal dan informal untuk memastikan informasi PLN Batam diterima konsisten.
3. Peningkatan efektivitas forum koordinasi lintas lembaga untuk mendukung kelancaran operasi, investasi, perizinan, serta isu-isu kelistrikan.
4. Digitalisasi manajemen stakeholder untuk pemetaan kepentingan, isu, dan respons korporat.
5. Penguatan peran Sekper sebagai gatekeeper koordinasi eksternal agar proses komunikasi perusahaan lebih terkendali, cepat, dan terstruktur.""",
        "program": """1. Penyusunan Stakeholder Engagement Plan (SEP) tahunan termasuk prioritas, rencana komunikasi, dan kebutuhan koordinasi.
2. Pelaksanaan pertemuan rutin dengan instansi strategis (triwulanan/bulanan sesuai kebutuhan).
3. Peningkatan sinergi regulasi dan perizinan dengan lembaga pemerintah melalui forum atau desk khusus.
4. Penyusunan dan penyebaran informasi korporat (press release, factsheet, QnA strategis, kompendium informasi).
5. Monitoring isu publik dan pemetaan risiko eksternal untuk mencegah krisis.
6. Pengelolaan event strategis (kunker, FGD, dialog publik, rapat koordinasi).
7. Implementasi sistem database stakeholder berbasis digital.
8. Pengelolaan hubungan dengan pelanggan prioritas melalui jalur komunikasi formal Sekper.""",
        "risk": """1. Informasi yang tidak tersampaikan atau tersampaikan tidak utuh, sehingga menimbulkan konflik pemahaman.
2. Perubahan kebijakan dari instansi eksternal yang berdampak pada operasi PLN Batam.
3. Isu publik atau pemberitaan negatif akibat kurangnya koordinasi.
4. Terhambatnya proses perizinan/kerjasama karena komunikasi lintas lembaga kurang efektif.
5. Stakeholder kunci tidak terlibat pada tahap penting pengambilan keputusan.
6. Ketergantungan pada hubungan personal, bukan sistem kelembagaan.
7. Minimnya dokumentasi koordinasi, sehingga sulit melakukan tracking.""",
        "mitigation": """1. Standarisasi alur koordinasi eksternal (SOP komunikasi, SOP surat-menyurat, SOP hubungan kelembagaan).
2. Penyediaan informasi formal yang terverifikasi agar pesan perusahaan konsisten.
3. Mapping & profiling stakeholder untuk menentukan strategi pendekatan.
4. Early Warning System monitoring isu publik dan regulasi.
5. Dokumentasi digital seluruh kegiatan koordinasi dan komunikasi.
6. Membangun komunikasi kelembagaan (institutional) bukan hanya personal.
7. Peningkatan kapasitas tim Sekper dalam diplomasi, negosiasi, dan manajemen isu.""",
        "action": """1. Menyusun Stakeholder Engagement Plan (SEP) 2025
2. Membuat database stakeholder prioritas (pemerintah, pelanggan besar, media, regulator)
3. Menyusun SOP koordinasi eksternal dan alur komunikasi
4. Melakukan kunjungan dan rapat koordinasi rutin (bulanan/triwulanan)
5. Menyusun kompendium informasi PLN Batam
6. Monitoring isu media dan kebijakan (mingguan).
7. Melakukan FGD atau forum sinergi dengan pemerintah daerah/regulator
8. Pengelolaan komunikasi pelanggan prioritas melalui jalur Sekper
9. Evaluasi efektivitas koordinasi antar lembaga""",
        "budget": D("495000"), "target_accum": "1",
        "target_accum_unit": "%", "pic": "MAN KOM",
        "mapping": "stakeholder",
    },
    {
        "no": 5, "source_row": 13, "section": "B", "section_no": 3,
        "kpi": "Social Engagement Media Coverage Instagram Tahun 2026",
        "unit": "%", "target": "10",
        "initiative": """1. Penguatan positioning digital PLN Batam sebagai lembaga yang informatif, responsif, dan dekat dengan masyarakat.
2. Optimalisasi konten berbasis insight pelanggan (data-driven content).
3. Peningkatan kualitas storytelling untuk membangun citra positif perusahaan.
4. Integrasi kampanye komunikasi 360° (IG, media online, press release, event).
5. Kolaborasi dengan stakeholder eksternal (komunitas, UMKM, lembaga pendidikan, instansi pemerintah).
6. Pemanfaatan fitur Instagram terbaru (Reels, Live, Guides, Collaboration Posts) untuk meningkatkan jangkauan.
7. Penguatan manajemen isu agar Instagram menjadi kanal klarifikasi tercepat.""",
        "program": """1. Penyusunan Social Media Strategy Plan 2026 (tema bulanan, target engagement, KPI konten).
2. Produksi konten reguler (Reels, carousel, infografis, edukasi layanan, kampanye keberlanjutan, TJSL).
3. Konten real-time & responsif untuk isu gangguan, pemeliharaan, atau klarifikasi publik.
4. Pelaksanaan kampanye digital tematik: listrik aman, EBT, layanan niaga, keselamatan ketenagalistrikan.
5. Kolaborasi konten dengan Pemerintah Daerah, komunitas energi, UMKM, sekolah, dan pelanggan besar.
6. Social listening & monitoring isu melalui analisis komentar, DM, trending topics lokal.
7. Pemanfaatan data insight Instagram untuk penyesuaian strategi bulanan.
8. Manajemen dokumentasi event untuk kebutuhan konten (foto/video).
9. Pelatihan internal (copywriting, public speaking untuk konten video, editing).""",
        "risk": """1. Engagement tidak tumbuh signifikan karena konten tidak sesuai preferensi audiens.
2. Pemberitaan negatif atau komentar sensitif yang memperburuk citra perusahaan.
3. Keterbatasan SDM kreatif untuk produksi konten berkualitas tinggi.
4. Ketidakkonsistenan frekuensi unggahan karena penumpukan pekerjaan operasional.
5. Perubahan algoritma Instagram yang memengaruhi jangkauan.
6. Keterlambatan klarifikasi isu sehingga menimbulkan spekulasi publik.
7. Kualitas visual atau pesan konten kurang menarik dibanding akun lembaga lain.""",
        "mitigation": """1. Penyusunan kalender konten tahunan (content calendar + bank konten).
2. Social media guideline untuk menjamin konsistensi visual, tone, dan respon.
3. Tim respon cepat (quick response team) untuk komentar pada situasi sensitif.
4. Penguatan koordinasi internal untuk mendapatkan bahan konten secara rutin.
5. Pelatihan dan peningkatan kapasitas tim kreatif (editing video, desain canva/photoshop, copywriting).
6. Benchmarking ke akun BUMN lain (Pertamina, PLN, Angkasa Pura, Pelindo).
7. Pemantauan insight mingguan untuk melihat tren dan penyesuaian strategi segera.""",
        "action": """1. Menyusun Social Media Strategy Plan & KPI Instagram 2026
2. Membuat kalender konten 12 bulan (tema, jadwal, format)
3. Produksi konten rutin (min. 4–6 posting/minggu)
4. Pelaksanaan kampanye tematik bulanan.
5. Peluncuran konten kolaborasi: komunitas/UMKM/instansi
6. Social listening mingguan & monitoring isu
7. Workshop internal content creation & creative writing
8. Evaluasi KPI Instagram 2026 & rekomendasi 2027""",
        "budget": D("495000"), "target_accum": "0.1",
        "target_accum_unit": "%", "pic": "MAN KOM",
        "mapping": "bridge",
    },

    {
        "no": 6, "source_row": 15, "section": "C", "section_no": 1,
        "kpi": "Penerapan Good Corporate Governance (GCG)",
        "unit": "Skor", "target": "94,95",
        "initiative": """1. Melakukan review dan pembaruan pedoman GCG dan Board Manual sesuai regulasi terbaru.
2. Menyusun roadmap implementasi GCG.
3. Mengembangkan mekanisme penegakan kepatuhan (compliance enforcement) terhadap kebijakan dan pedoman GCG
4. Menyusun Surat Keputusan Direksi terkait key governance officer di setiap unit untuk memastikan penerapan GCG berjalan sampai level operasional.
5. Pelaksanaan sosialisasi GCG Code untuk seluruh level pegawai.
6. Kampanye “GCG Culture” melalui media internal dan kegiatan internalisasi nilai-nilai integritas.
7. Melakukan self-assessment GCG tahunan menggunakan parameter Kementerian BUMN
8. Menetapkan Key Risk Indicator (KRI) terkait risiko tata kelola dan kepatuhan.""",
        "program": """1.Review dan pembaruan Pedoman GCG dan Board Manual sesuai regulasi dan praktik terbaik
2. Melakukan Self Assessment Penerapan GCG tahun 2025 PT PLN Batam sesuai pedoman Kementerian BUMN
3. Melaksanakan Refreshment pengelolaan GCG untuk semua level pegawai
4. Integrasi GCG dengan Manajemen Risiko dan Kepatuhan melalui forum GRC (GRC Integration)
6. Publikasi laporan GCG dan laporan keberlanjutan di situs resmi perusahaan
7. Penyusunan dan pelaksanaan action plan untuk memperbaiki area yang lemah AOI sesuai dengan hasil Assesment tahun sebelumnya""",
        "risk": """1.Informasi penting bagi pemangku kepentingan tidak diungkapkan secara lengkap, akurat, atau tepat waktu.
2. Lemahnya sistem pengendalian internal menyebabkan potensi fraud, penyalahgunaan wewenang, dan ketidakefisienan proses.
3. Peran dan tanggung jawab Direksi, Komisaris, Komite, dan unit tidak jelas sehingga menyebabkan ketidakefektifan pengambilan keputusan.
4. Pelanggaran kode etik atau tidak berjalannya budaya integritas.
5. Pegawai tidak memahami prinsip GCG dan perannya masing-masing.
6. Proses self-assessment atau scoring GCG tidak objektif.""",
        "mitigation": """1. Self Assesment GCG
2. Mensosialisasikan dan melakukan refresment terkait GCG code terbaru
3. Melaksanakan forum koordinasi GRC
4. Melakukan evaluasi kinerja tata kelola secara periodik untuk perbaikan berkelanjutan melalui perhitungan pelaksanaan pencapaian Maturity Level GCG setiap bulan.
5. Menyusun SOP operasional yang jelas, mudah diakses, dan diperbarui secara berkala.
6. Pembuatan Pakta Integritas Dekom, Direksi dan Pegawai setiap tahun""",
        "action": """a. Review pedoman GCG Code dan Board Manual
b. Menyesuaiakan GCG dan Board Manual dengan regulasi terbaru BUMN
c. Melakukan pengesahan dokumen baru oleh Direksi
d. Melakukan pemantauan roadmap penerapan GCG PT PLN Batam
e. Melaksanakan sosialisasi GCG bagi seluruh pegawai
f. Mengumpulkan eviden penerapan GCG seluruh unit.
i. Pelaksanaan self-assessment berdasarkan parameter BUMN.
j. Pelaksanaan monitoring triwulanan.
k. Pelaporan progres ke Direksi dan Dewan Komisaris.""",
        "budget": D("1120000"), "target_accum": "94,95",
        "target_accum_unit": "Skor", "pic": "MAN SEK, MAN KUM, MAN KOM",
        "mapping": "bridge",
    },
    {
        "no": 7, "source_row": 16, "section": "C", "section_no": 2,
        "kpi": "Implementasi Governance Risk Compliance (GRC)",
        "unit": "Hari kerja", "target": "5",
        "initiative": """1. Implementasi Governance Risk Compliance (GRC)
2. Penguatan Budaya Kepatuhan & Integritas melalui kebijakan, pelatihan, dan komunikasi perusahaan.
3. Penguatan Koordinasi dan sinergi antar fungsi""",
        "program": """1. Penyusunan Kebijakan & Pedoman GRC (Kebijakan Tata Kelola, Manajemen Risiko, Compliance, Anti Fraud, Anti Suap, Whistleblowing).
2. Pemetaan Risiko Perusahaan (Corporate Risk Register) dan Risk Owner di seluruh unit.
3. Peningkatan Kompetensi GRC melalui pelatihan risk awareness, anti fraud, anti suap, etika bisnis, dan compliance.
4. Penyusunan Laporan GRC
5. Penilaian Maturity Level GRC dan penyusunan roadmap peningkatan level.""",
        "risk": """1. Kurangnya Pengawasan Pengendalian Internal sehingga risiko fraud, kesalahan proses, dan ketidakpatuhan meningkat.
2. Tidak Efisiennya waktu pengambilan keputusan strategis
3. Terdapatnya data yang inkonsisten dalam pengambilan keputusan Manajemen""",
        "mitigation": """1. Pelaksanaan Rapat Rutin Tim GRC untuk pembahasan pelaksaan forum GRC
2. Pembuatan Laporan Implementasi GRC secara berkala
3. Pelaksanaan Workshop dan Refreshement terkait GRC untuk Tim GRC dan BPO
4. Pembuatan Time Line pelaksanaan forum GRC mulai dari Penyampaian Dokumen oleh BPO samapai dengan penerbitan ulasan""",
        "action": """1. Kickoff Meeting GRC & sosialisasi program.
2. Pelatihan GRC untuk Tim GRC
3. Sosialisasi/Refresment GRC kepada seluruh unit
4. Review menyeluruh pelaksanaan GRC.
5. Penyusunan Laporan Pelaksanaan GRC
6. Penetapan target maturity level berikutnya.""",
        "budget": D("0"), "target_accum": "5",
        "target_accum_unit": "hari", "pic": "MAN SEK",
        "mapping": "grc",
    },
    {
        "no": 8, "source_row": 17, "section": "C", "section_no": 3,
        "kpi": "Penerbitan Advis Hukum/Pendapat Hukum/Legal Opinion ",
        "unit": "Hari", "target": "10 hari sejak Dokumen Lengkap",
        "initiative": """1. Analisa isu hukum dengan peraturan perundang-undangan terkait.
2. Koordinasi denganUnit Bisnis/Bidang terkait untuk mengumpulkan informasi dan dokumen pendukung dalam penyusunan Legal Opinion.
3. Melakukan koordinasi dan penunjukan keapada APH, external lawyer, atau lembaga terkait untuk menyusun Legal Opinion atas isu/proyek strategis (apabila diperlukan)""",
        "program": "Menyusun Legal Opinion berdasarkan isu atau masalah hukum yang ditanyakan, untuk selanjutnya dijawab berdasarkan peraturan perundang-undangan yang berlaku, Anggaran Dasar PLN Batam, Peraturan Direksi maupun aturan lainnya yang berkaitan.",
        "risk": """1.apabila tidak ada advis hukum/pendapat atau berpotensi perusahaan mengambil kebijakan yang salah dan menimbulkan kerugian finasial atau reputasi.
2. interpretasi hukum yang salah, menyebabkan perusahaan terkena sanksi""",
        "mitigation": """1. Memastikan penyusunan Legal Opinion dilakukan secara komprehensif berdasarkan peraturan perundang-undagan yang ada dan regulasi lainnya yang berkaitan tanpa adanya intervensi atas kajian yang dilakukan.
2. Memastikan tersedianya peraturan perundang-undangan dan regulasi lainnya yang terupdate untuk memastikan LO yang disusun telah memenuhi seluruh aspek hukum positif.""",
        "action": "- Pengesahan dokumen baru oleh Direksi.",
        "budget": D("2200000"), "target_accum": "10",
        "target_accum_unit": "hari", "pic": "MAN KUM",
        "mapping": "legal_opinion",
    },
    {
        "no": 9, "source_row": 18, "section": "C", "section_no": 4,
        "kpi": "Reviu Draf Regulasi Internal dan Kontrak/Amandemen/HOA/MOU dari Unit Bisnis/Bidang",
        "unit": "Hari", "target": "5 hari sejak Dokumen Lengkap",
        "initiative": """1. identifikasi peraturan perundang-undangan terkait dan melakukan harmonisasi terhadap draft regulasi internal
2. Koordinasi dengan Unit Bisnis/Bidang terkait untuk menyelaraskan pemahaman atas draft perdir dan implementasi pelaksananaannya.""",
        "program": "Melakukan review terhadap draft regulasi internal PT PLN Batam dengan mengacu kepada peraturang perundang-undangan terkait dan peraturan internal PY PLN Batam lainnya yang terkait.",
        "risk": """1. risiko kegagalan kepatuhan regulasi pemerintah, menyebabkan sanksi, denda atau pencabutan izin. 2. perbedaan interpretasi dalam kontrak berakibat timbul sengketa/dispute dengan pihak lain.
3. kerugian finansial.""",
        "mitigation": """1. Mensinkronkan draft regulasi internal dengan seluruh peraturan perundang-undangan yang berlaku.
2. Koordinasi dengan Unit Bisnis/Bidang terkait untuk memastikan draft regulasi internal sudah mencakup seluruh kepentingan PT PLN Batam dan pihak lainnya (jika diwajibkan oleh peraturan perundang-undangan yang berlaku) dan dapat diimplementasikan.""",
        "action": """1. Mengumpulkan dan analisa seluruh peraturan perundang-undangan terkait dengan draft regulasi internal terkait.
2. koordinasi dengan Unit Bisnis/Bidang terkait""",
        "budget": D("385000"), "target_accum": "5",
        "target_accum_unit": "hari", "pic": "MAN KUM",
        "mapping": "bridge",
    },
    {
        "no": 10, "source_row": 19, "section": "C", "section_no": 5,
        "kpi": "Pendampingan Penyelesaian Permasalahan Hukum Litigasi/Non Litigasi",
        "unit": "%", "target": "100% dari jumlah permintah pendampingan",
        "initiative": """1. Penyusunan kronologis hukum
2. Pengumpulan dokumen pendukung/alat bukti dengan berkoordinasi dengan bidang terkait
3. Penunjukan penasihat/pendamping hukum (apabila diperlukan)
4. Penyusunan dokumen beracara sesuai ketentuan yang berlaku""",
        "program": """1. Mengidentifikasi isu masalah dengan berkoordinasi dengan Unit Bisnis/Bidang terkait
2. Melakukan sinkronisasi isu masalah hukum dengan peraturan perundang-undangan yang berlaku dan peraturan internal PT PLN Batam
3. Memilih alternatif penyelesaian sengketa
4. Melaksanakan pendampingan atas gugatan yang ditujukan kepada PT PLN Batam dan menyusun strategi penyelesaian perkara, atau
5. Melaksanakan pendampingan dalam pelaksanaan gugatan dimana PLN Batam sebagai Penggugat""",
        "risk": """1. perusahaan kalah sengketa perdata menyebabkan kerugian finansial atau reputasi.
2. biaya pendampingan hukum yang tidak terkendali dapat membebani perusahaan.""",
        "mitigation": """1. Pemenuhan peraturan perundang-undangan dalam proses bisnis PT PLN Batam
2. Pemenuhan hak dan kewajiban yang seimbang antara PT PLN Batam dengan penyedia atau mitra kerjasama dalam perjanjian
3. Review atas perjanjian secara komprehensif
4. Memastikan harmonisasi antara peraturan perundang-undangan yang berlaku dengan peraturan internal di PT PLN Batam""",
        "action": """1. Review kontrak
2. review peraturan/regulasi internal PLN Batam
3. Penyusunan LO GRC atas rencana bisnis
4. Pendampingan hukum dalam pelaksanaan proses bisnis""",
        "budget": D("1100000"), "target_accum": "100",
        "target_accum_unit": "persen", "pic": "MAN KUM",
        "mapping": "bridge",
    },
    {
        "no": 11, "source_row": 20, "section": "C", "section_no": 6,
        "kpi": "Reviu Draf  Kontrak/Amandemen/HOA/MOU dari Unit Bisnis/Bidang",
        "unit": "Hari", "target": "5 hari sejak Dokumen Lengkap",
        "initiative": """1. Analisa dan review latar belakang/dasar pelaksanaan kontrak
2. Sinkronisasi draft perjanjian dengan peraturan perundang-undangan terkait untuk memastikan kepatuhan terhadap regulasi.
3. Berkoordinasi dengan Unit Bisnis/Bidang terkait untuk memastikan pemenuhan seluruh aspek perjanjian dengan benar dan optimal.""",
        "program": """1. Memastikan dasar pelaksanaan perjanjian sudah benar dan sesuai.
2. Mensinkronkan dokumen pendukung dengan draft perjanjian yang diajukan.""",
        "risk": """1. perbedaan interpretasi dalam kontrak berakibat timbul sengketa/dispute dengan pihak lain.
2. kerugian finansial.""",
        "mitigation": """1. Memastikan dasar pelaksanaan perjanjian sudah sesuai dengan aturan yang ada
2.Memastikan sinkronisasi seluruh klausul perjanjian dengan dokumen pendukung yang ada
2. Memastikan pemenuhan hak dan kewajiban bagi para pihak secara berimbang dan jelas
3. Memastikan klausul kepatuhan atas peraturan perundang-undangan, peraturan internal PLN Batam terakomodir di dalam perjanjian.""",
        "action": """1. cek kelengkapan dasar pelaksanaan perjanjian
2. Koordinasi dengan Unit Bisnis/Bidang terkait dan juga penyedia (jika dibutuhkan)untuk melaksanakan review bersama untuk menyamakan pemahaman atas setiap klausul perjanjian.""",
        "budget": D("0"), "target_accum": "5",
        "target_accum_unit": "hari", "pic": "MAN KUM",
        "mapping": "contract_review",
    },

    {
        "no": 12, "source_row": 22, "section": "D", "section_no": 1,
        "kpi": "Implementasi Roadmap Perbaikan Penerapan Manajemen Risiko SH/AP",
        "unit": "%", "target": "100",
        "initiative": """1.Peningkatan Kapabilitas Risk Owner & Risk Champion agar mitigasi risiko berjalan efektif.
2. Integrasi Manajemen Risiko dalam Proses Bisnis termasuk perencanaan KPI
3. Penguatan Pengawasan dan Assurance melalui monitoring, review, dan pelaporan risiko berkala.""",
        "program": """1. Pelatihan dan Sertifikasi Risiko untuk Risk Officer, Risk Owner, dan Manager.
2. Penyusunan dan Monitoring Rencana Mitigasi Risiko
3. Risk Review Triwulanan dan integrasi ke laporan Risiko
4. Penilaian Maturity Level Manajemen Risiko Bulanan""",
        "risk": """1. Komitmen manajemen tidak konsisten dalam melaksanakan manajemen risiko.
2. Kapasitas Risk Officer & Risk Owner tidak memadai.
3. Identifikasi risiko kurang lengkap dan tidak berbasis data.
4. Keterlambatan pelaporan.""",
        "mitigation": """1. Top Management Commitment melalui KPI risiko untuk Direksi, Sekper, VP
2. Pelatihan dan Sertifikasi Risiko
3. Program Coaching & Mentoring untuk Risk Owner dan Risk Champion.
4. Review bulanan pencapaian roadmap risiko""",
        "action": """1. Finalisasi Roadmap Perbaikan Manajemen Risiko sesuai arahan.
2. Pelatihan manajemen risiko
3. Risk review triwulanan dengan penilaian efektivitas mitigasi.
4. Monitoring pelaksanaan mitigasi tiap bulan.""",
        "budget": D("0"), "target_accum": "100",
        "target_accum_unit": "%", "pic": "MAN SEK, MAN KUM, MAN KOM",
        "mapping": "kpmr",
    },
    {
        "no": 13, "source_row": 23, "section": "D", "section_no": 2,
        "kpi": "Maturity Level Sustainability",
        "unit": "%", "target": "100",
        "initiative": """1. Membentuk komite keberlanjutan lintas fungsi yang bertanggung jawab pada perencanaan, implementasi, monitoring, dan pelaporan kinerja ESG.
2. Penetapan KPI keberlanjutan pada level Direksi hingga pelaksana, termasuk target dekarbonisasi, efisiensi energi, dan tanggung jawab sosial.
3. Program tanggung jawab sosial berbasis dampak (impact-based CSR) yang terfokus pada isu-isu prioritas energi, pendidikan vokasi, dan pemberdayaan UMKM.
4. Program pelatihan ESG untuk seluruh level pegawai, mulai dari pemahaman dasar sampai pengelolaan data dan standar global.
5. Review dan evaluasi tahunan maturity level untuk memetakan gap dan rencana perbaikan.""",
        "program": """1. Penguatan Tata Kelola & Sistem Keberlanjutan (Governance)
2. Penguatan Manajemen K3 & Aspek Sosial (Social Responsibility)""",
        "risk": """1. Kebijakan keberlanjutan tidak diterapkan secara konsisten di seluruh unit.
2. Data ESG tidak akurat, tidak lengkap, atau tidak terstandardisasi.
3. Keterlambatan pembentukan struktur organisasi keberlanjutan.
4. Program TJSL tidak berdampak (non-impactful) dan tidak sesuai kebutuhan masyarakat.""",
        "mitigation": """1. Pembersihan data (data cleansing) dan pembangunan sistem data ESG terintegrasi
2. Sosialisasi kebijakan dan SOP keberlanjutan ke seluruh unit.
3. Penetapan mandat formal melalui SK Direksi.
4.Penyusunan CSR Impact Assessment.""",
        "action": """1. Menyusun & mengesahkan Kebijakan Keberlanjutan dan ESG Framework.
2. Membentuk Komite Keberlanjutan lintas fungsi serta tim pengelola data ESG.
3. Mengembangkan dashboard pelaporan ESG berbasis digital.
4. Menetapkan KPI ESG untuk Direksi, senior leader, dan unit pelaksana.
5. Penyusunan RKA Tahunan""",
        "budget": D("0"), "target_accum": "100",
        "target_accum_unit": "%", "pic": "MAN KOM, MAN SEK, MAN KUM",
        "mapping": "sustainability",
    },
    {
        "no": 14, "source_row": 24, "section": "D", "section_no": 3,
        "kpi": "Maturity Level Tata Kelola Perusahaan",
        "unit": "Skor", "target": "2,1",
        "initiative": """1. Menyusun roadmap implementasi GCG yang terintegrasi dengan strategi bisnis perusahaan.
2. Monitor Pelaksanaan Roadmap Implementasi GCG setiap bulannya""",
        "program": """1.Mengusulkan Roadmap tahapan implementasi GCG jangka menengah
2. Pelaksanaan Kegiatan pemantauan GCG sesuai Roadmap yang di usulkan
3. Melakukan penilaian mandiri pencapaian roadmap GCG
4. Melakukan evaluasi terhadap pencapaian Roadmap GCG
5. Melakukan Koordinasi Pencapaian Roadmap dengan PT PLN Persero""",
        "risk": """1. Kebijakan tata kelola tidak lengkap, tidak mutakhir, atau tidak selaras dengan regulasi.
2. Evaluasi GCG tidak dilakukan secara berkala.
3. Kurangnya kompetensi pegawai dan pimpinan dalam tata kelola, risiko, dan kepatuhan.""",
        "mitigation": """1. Membuat pelaporan realisasi Roadmap bulanan
2. Early Warnig terkait target roadmap yang belum tercapai
3. Pelaksanaan Diklat atau CBP Roadmap GCG""",
        "action": """1. Menyusun Time Line pencapaian roadmap maturity level tata kelola perusahaan secara bulanan
2. Melakukan evaluasi terkait pencapaian roadmap maturity level tata kelola perusahaan secara bulanan
3. Membuat daftar kendala dan hal-hal yang harus ditindaklanjuti""",
        "budget": D("0"), "target_accum": "2,1",
        "target_accum_unit": "Poin", "pic": "MAN SEK",
        "mapping": "governance_maturity",
    },
    {
        "no": 15, "source_row": 25, "section": "D", "section_no": 4,
        "kpi": "Human Capital Readiness (HCR) & Organizational Capital Readiness (OCR) dan Produktivitas Pegawai",
        "unit": "%", "target": "100",
        "initiative": "Pemetaan dan penataan kebutuhan SDM untuk mendukung transformasi bisnis.",
        "program": """1. Penyusunan Workforce Planning dan Manpower Requirement.
2. Talent mapping dan penyusunan individual development plan.""",
        "risk": """1. Kompetensi SDM tidak sesuai kebutuhan bisnis.
2. Proses suksesi tidak berjalan.""",
        "mitigation": "Pelatihan berbasis gap kompetensi dan prioritas bisnis.",
        "action": "Pemetaan kebutuhan SDM, penyusunan kurikulum pelatihan, dan talent mapping.",
        "budget": D("0"), "target_accum": "100",
        "target_accum_unit": "%", "pic": "MAN KOM, MAN SEK, MAN KUM",
        "mapping": "human_capital",
    },

    {
        "no": 16, "source_row": 27, "section": "E", "section_no": 1,
        "kpi": "Compliance (GCG, Zero Fatality, Kepatuhan K3L, SPI, Reporting, Busdev Alignment)",
        "unit": "Nilai Pengurang", "target": None,
        "initiative": None, "program": None, "risk": None,
        "mitigation": None, "action": None,
        "budget": None, "target_accum": None,
        "target_accum_unit": None, "pic": None,
        "mapping": "compliance",
    },
]


# Existing KM anchors expected from the signed/current SETPER KM.
ANCHOR_ALIASES = {
    "communication_tjsl": (
        "Pengelolaan Komunikasi & TJSL",
    ),
    "stakeholder": (
        "Koordinasi Antar Lembaga dan Stakeholder PLN Batam",
    ),
    "grc": (
        "Implementasi Governance Risk Compliance (GRC)",
        "Implementasi Sistem Manajemen Terintegritas",
        "Implementasi Sistem Manajemen Terintegrasi",
    ),
    "legal_opinion": (
        "Penerbitan Advis Hukum/Pendapat Hukum/Legal Opinion",
    ),
    "contract_review": (
        "Reviu Draf Kontrak/Amandemen/HOA/MOU dari Unit Bisnis/Bidang",
    ),
    "kpmr": (
        "Kualitas Penerapan Manajemen Risiko (KPMR)",
    ),
    "sustainability": (
        "Maturity Level Sustainability",
    ),
    "governance_maturity": (
        "Maturity Level Tata Kelola Perusahaan",
    ),
    "human_capital": (
        "Pengelolaan Human Capital",
    ),
    "compliance": (
        "Compliance",
    ),
}


class DryRunRollback(Exception):
    pass


def banner(title):
    print("\n" + "=" * 142)
    print(title)
    print("=" * 142)


def normalize(value):
    value = str(value or "").casefold().replace("\xa0", " ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def backup_sqlite():
    engine = settings.DATABASES["default"]["ENGINE"]
    if "sqlite3" not in engine:
        raise RuntimeError(
            f"STOP: backup otomatis V1 hanya mendukung SQLite; engine={engine!r}"
        )

    source = Path(str(settings.DATABASES["default"]["NAME"])).expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"STOP: file DB tidak ditemukan: {source}")

    backup_dir = PROJECT_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"db_before_rkm_setper_juli_2026_{stamp}.sqlite3"

    shutil.copy2(source, target)
    print("BACKUP DB:", target)
    return target


def source_audit():
    banner("SOURCE AUDIT — EMBEDDED FROM WORKBOOK")
    print("Source :", SOURCE_NAME)
    print("Sheet  :", SOURCE_SHEET)
    print("SHA256 :", SOURCE_SHA256)
    print("Tahun  :", YEAR)
    print("KPI    :", len(SOURCE_ROWS))
    print("Rencana Realisasi Jan-Dec : BLANK 16/16")
    print("Jumlah / % Capaian        : BLANK 16/16")
    print()

    by_section = {}
    budget = Decimal("0")
    for src in SOURCE_ROWS:
        by_section[src["section"]] = by_section.get(src["section"], 0) + 1
        budget += src["budget"] or Decimal("0")
        print(
            f"{src['no']:02d}. source row={src['source_row']} "
            f"| {src['section']}.{src['section_no']} "
            f"| {src['kpi']!r} | target={src['target']!r} "
            f"| anggaran={src['budget']!r} | PIC={src['pic']!r}"
        )

    print()
    print("Per bagian :", ", ".join(f"{k}={v}" for k, v in sorted(by_section.items())))
    print("Total KPI  :", sum(by_section.values()))
    print("Total Anggaran source (Rp Ribu):", budget)

    if len(SOURCE_ROWS) != 16:
        raise RuntimeError("STOP: source embedded bukan 16 KPI.")
    if [x["no"] for x in SOURCE_ROWS] != list(range(1, 17)):
        raise RuntimeError("STOP: global no_item source bukan 1..16.")


def resolve_unit():
    normalized_aliases = {normalize(x) for x in UNIT_ALIASES}
    candidates = [
        g for g in Group.objects.order_by("pk")
        if normalize(g.name) in normalized_aliases
    ]

    banner("UNIT PREFLIGHT")
    for g in candidates:
        print(f"candidate Group={g.pk} | {g.name!r}")

    if len(candidates) == 1:
        unit = candidates[0]
        print(f"SELECTED: Group={unit.pk} | {unit.name!r}")
        return unit

    if not candidates:
        fuzzy = [
            g for g in Group.objects.order_by("pk")
            if "setper" in normalize(g.name) or "sekper" in normalize(g.name)
        ]
        for g in fuzzy:
            print(f"fuzzy Group={g.pk} | {g.name!r}")
        if len(fuzzy) == 1:
            print(f"SELECTED FUZZY: Group={fuzzy[0].pk} | {fuzzy[0].name!r}")
            return fuzzy[0]
        raise RuntimeError(
            "STOP: unit SETPER/SEKPER tidak dapat ditentukan unik. "
            "Review daftar Group di atas."
        )

    raise RuntimeError(
        "STOP: lebih dari satu Group SETPER/SEKPER cocok. "
        "Importer tidak menebak unit."
    )


def resolve_km(unit):
    qs = KontrakManajemen.objects.filter(
        tahun=YEAR,
        unit_bisnis=unit,
    ).order_by("pk")

    banner("KM PREFLIGHT")
    for km in qs:
        print(
            f"candidate KM={km.pk} | judul={km.judul!r} | "
            f"status={km.status!r} | items="
            f"{ItemKontrakManajemen.objects.filter(kontrak=km).count()}"
        )

    if qs.count() == 1:
        km = qs.first()
    else:
        preferred = [
            km for km in qs
            if "setper" in normalize(km.judul)
            or "sekper" in normalize(km.judul)
        ]
        if len(preferred) == 1:
            km = preferred[0]
        else:
            raise RuntimeError(
                "STOP: KM SETPER 2026 tidak dapat ditentukan unik. "
                "Importer tidak membuat/mengganti KM master."
            )

    print(
        f"SELECTED KM={km.pk} | judul={km.judul!r} | "
        f"tahun={km.tahun} | status={km.status!r}"
    )
    return km


def resolve_anchor(km, key):
    aliases = tuple(normalize(x) for x in ANCHOR_ALIASES[key])
    items = list(
        ItemKontrakManajemen.objects.filter(kontrak=km)
        .select_related("master_bagian")
        .order_by("pk")
    )

    exact = [
        x for x in items
        if normalize(x.indikator_kinerja_kunci) in aliases
    ]

    # Compliance can be stored as a longer label in legacy KM.
    if not exact and key == "compliance":
        exact = [
            x for x in items
            if normalize(x.indikator_kinerja_kunci).startswith("compliance")
        ]

    if len(exact) != 1:
        print(f"\nANCHOR {key!r} expected aliases={ANCHOR_ALIASES[key]!r}")
        for x in items:
            score = any(a in normalize(x.indikator_kinerja_kunci) for a in aliases)
            if score or key in {"human_capital", "compliance"}:
                print(
                    f"  KMItem={x.pk} no={x.no_urut} "
                    f"| {x.indikator_kinerja_kunci!r}"
                )
        raise RuntimeError(
            f"STOP: anchor {key!r} tidak unique; ditemukan {len(exact)}."
        )

    return exact[0]


def build_existing_anchors(km):
    banner("CANONICAL KM ANCHORS")
    anchors = {}
    for key in ANCHOR_ALIASES:
        obj = resolve_anchor(km, key)
        anchors[key] = obj
        print(
            f"{key:<20} -> KMItem={obj.pk:<4} no={obj.no_urut:<3} "
            f"| {obj.indikator_kinerja_kunci!r}"
        )

    if len({x.pk for x in anchors.values()}) != len(anchors):
        raise RuntimeError("STOP: anchor canonical tidak unique.")
    return anchors


def next_free_no_urut(km, reserved):
    used = set(
        ItemKontrakManajemen.objects
        .filter(kontrak=km)
        .values_list("no_urut", flat=True)
    )
    used |= set(reserved)
    n = max(used or {0}) + 1
    while n in used:
        n += 1
    return n


def bridge_identity(src):
    # Deliberately distinct from canonical KPI labels.
    return f"[RKM SETPER {src['section']}.{src['section_no']}] {src['kpi']}"


def get_or_create_bridge(km, src, anchor_template, reserved):
    label = bridge_identity(src)
    qs = ItemKontrakManajemen.objects.filter(
        kontrak=km,
        indikator_kinerja_kunci=label,
    ).order_by("pk")

    if qs.count() > 1:
        raise RuntimeError(
            f"STOP: duplicate technical bridge untuk source {src['no']}: "
            f"{list(qs.values_list('pk', flat=True))}"
        )

    if qs.exists():
        obj = qs.get()
        print(
            f"BRIDGE REUSE  source={src['no']:02d} -> KMItem={obj.pk} "
            f"| {label!r}"
        )
        return obj, False

    no_urut = next_free_no_urut(km, reserved)
    reserved.add(no_urut)

    obj = ItemKontrakManajemen(
        kontrak=km,
        bagian=None,
        master_bagian=anchor_template.master_bagian,
        no_urut=no_urut,
        indikator_kinerja_kunci=label,
        formula="Technical FK anchor untuk RKM SETPER 2026; bukan KPI berbobot KM.",
        satuan=src["unit"] or "",
        bobot=0,
        target=src["target"] or "",
        polaritas="positif",
    )
    obj.full_clean()
    obj.save()

    print(
        f"BRIDGE CREATE source={src['no']:02d} -> KMItem={obj.pk} "
        f"| no_urut={obj.no_urut} | {label!r}"
    )
    return obj, True


def build_mapping(km, anchors):
    banner("MAPPING RKM SOURCE -> KM ITEM")
    mapping = {}
    bridge_count = 0
    reserved = set()

    # A neutral template for technical bridges. It is only used to satisfy the
    # existing FK to master_bagian; bridge bobot remains 0.
    anchor_template = anchors["communication_tjsl"]
    if not anchor_template.master_bagian_id:
        raise RuntimeError(
            "STOP: canonical Pengelolaan Komunikasi & TJSL tidak punya master_bagian."
        )

    for src in SOURCE_ROWS:
        spec = src["mapping"]
        if spec == "bridge":
            obj, created = get_or_create_bridge(
                km, src, anchor_template, reserved
            )
            bridge_count += int(created)
        else:
            obj = anchors[spec]

        mapping[src["no"]] = obj
        print(
            f"{src['no']:02d}. {src['section']}.{src['section_no']} "
            f"| source={src['kpi']!r} "
            f"| KMItem={obj.pk} / no={obj.no_urut}"
        )

    ids = [mapping[n].pk for n in range(1, 17)]
    if len(ids) != 16 or len(set(ids)) != 16:
        raise RuntimeError(
            f"STOP: mapping km_item tidak unique 16/16: {ids}"
        )

    print("MAPPING UNIQUE: 16/16 OK")
    print("Technical bridge created in this transaction:", bridge_count)
    return mapping, bridge_count


def ensure_no_existing_rkm(unit, km):
    qs = RKMSummary.objects.filter(
        tahun=YEAR,
        bulan=MONTH,
        unit_bisnis=unit,
        kontrak_manajemen=km,
    ).order_by("pk")

    banner("RKM BASELINE")
    for x in qs:
        print(
            f"FOUND RKM={x.pk} | judul={x.judul!r} | "
            f"status={x.status!r} | items={RKMItem.objects.filter(summary=x).count()}"
        )

    if qs.exists():
        raise RuntimeError(
            "STOP: RKM SETPER Juli 2026 untuk unit+KM ini sudah ada. "
            "V1 tidak overwrite RKM existing."
        )

    print("MISSING — RKM SETPER Juli 2026 akan dibuat.")


def create_summary(unit, km):
    summary = RKMSummary(
        judul=RKM_TITLE,
        tahun=YEAR,
        bulan=MONTH,
        unit_bisnis=unit,
        kontrak_manajemen=km,
        tanggal_mulai=date(YEAR, MONTH, 1),
        tanggal_selesai=date(YEAR, MONTH, 31),
        status="Draft",
        status_pengajuan="Belum",
        pic="SETPER",
    )
    summary.full_clean()
    summary.save()
    print(
        f"CREATE SUMMARY id={summary.pk} | {summary.judul!r} "
        f"| status={summary.status!r}"
    )
    return summary


def item_kwargs(summary, src, km_item):
    keterangan = (
        f"Sumber: {SOURCE_NAME} | sheet {SOURCE_SHEET} | "
        f"Excel row {src['source_row']} | source no {src['section']}.{src['section_no']}."
    )

    return {
        "summary": summary,
        "no_item": src["no"],
        "km_item": km_item,
        "kategori_rkm": src["section"],
        "sasaran": SECTION_NAMES[src["section"]],
        "kpi_indikator": src["kpi"],
        "kpi_satuan": src["unit"],
        "kpi_target": src["target"],
        "inisiatif_strategis": src["initiative"],
        "program_kerja_utama": src["program"],
        "risiko": src["risk"],
        "mitigasi_risiko": src["mitigation"],
        "rencana_aksi": src["action"],
        "anggaran_rp_ribu": src["budget"],
        "target_akumulasi": src["target_accum"],
        "target_akumulasi_satuan": src["target_accum_unit"],

        # Source "3. RKM" tidak memiliki nilai pada M:X.
        "target_januari": None,
        "target_februari": None,
        "target_maret": None,
        "target_april": None,
        "target_mei": None,
        "target_juni": None,
        "target_juli": None,
        "target_agustus": None,
        "target_september": None,
        "target_oktober": None,
        "target_november": None,
        "target_desember": None,

        # Source juga tidak menyediakan realisasi bulanan.
        "realisasi_januari": None,
        "realisasi_februari": None,
        "realisasi_maret": None,
        "realisasi_april": None,
        "realisasi_mei": None,
        "realisasi_juni": None,
        "realisasi_juli": None,
        "realisasi_agustus": None,
        "realisasi_september": None,
        "realisasi_oktober": None,
        "realisasi_november": None,
        "realisasi_desember": None,

        "jumlah_realisasi": None,
        "persen_capaian": None,
        "realisasi_anggaran": None,
        "pic_rkm": src["pic"],
        "hasil_analisa_program_kerja": None,

        # Generic legacy display fields remain source-faithful.
        "target_bulanan": None,
        "realisasi": None,
        "deviasi": None,
        "keterangan": keterangan,
    }


def create_items(summary, mapping):
    banner("CREATE 16 RKM ITEMS")
    created = []

    for src in SOURCE_ROWS:
        item = RKMItem(**item_kwargs(summary, src, mapping[src["no"]]))
        item.full_clean()
        item.save()

        # The model may calculate monthly aggregate fields on save().
        # Source explicitly has blanks, so ensure no synthetic result is kept.
        RKMItem.objects.filter(pk=item.pk).update(
            jumlah_realisasi=None,
            persen_capaian=None,
            realisasi_anggaran=None,
        )
        item.refresh_from_db()

        if item.jumlah_realisasi is not None or item.persen_capaian is not None:
            raise RuntimeError(
                f"STOP: source result blank tetapi item {src['no']} "
                f"menghasilkan jumlah={item.jumlah_realisasi!r}, "
                f"capaian={item.persen_capaian!r}"
            )

        created.append(item)
        print(
            f"{src['no']:02d}. RKMItem={item.pk:<4} "
            f"| km_item={item.km_item_id:<4} "
            f"| kategori={item.kategori_rkm} "
            f"| KPI={item.kpi_indikator!r}"
        )

    if len(created) != 16:
        raise RuntimeError(
            f"STOP: RKMItem created={len(created)}, expected=16"
        )
    return created


def verify(summary, km_before_labels):
    banner("VERIFY IN TRANSACTION")

    summary.refresh_from_db()
    items = list(
        RKMItem.objects.filter(summary=summary)
        .select_related("km_item")
        .order_by("no_item", "pk")
    )

    if len(items) != 16:
        raise RuntimeError(
            f"STOP: verify RKMItem={len(items)}, expected=16"
        )

    if [x.no_item for x in items] != list(range(1, 17)):
        raise RuntimeError(
            f"STOP: no_item bukan 1..16: {[x.no_item for x in items]}"
        )

    if len({x.km_item_id for x in items}) != 16:
        raise RuntimeError("STOP: km_item tidak unique 16/16.")

    for src, item in zip(SOURCE_ROWS, items):
        expected_kpi_target = src["target"]

        # Jika target pada source RKM kosong, model RKMItem secara canonical
        # mewarisi target dari KM master. Contoh: Compliance -> "Max -10".
        if expected_kpi_target in (None, ""):
            expected_kpi_target = item.km_item.target or None

        checks = {
            "kategori_rkm": src["section"],
            "sasaran": SECTION_NAMES[src["section"]],
            "kpi_indikator": src["kpi"],
            "kpi_satuan": src["unit"],
            "kpi_target": expected_kpi_target,
            "target_akumulasi": src["target_accum"],
            "target_akumulasi_satuan": src["target_accum_unit"],
            "pic_rkm": src["pic"],
        }
        for field, expected in checks.items():
            actual = getattr(item, field)
            if actual != expected:
                raise RuntimeError(
                    f"STOP: source mismatch item={src['no']} field={field}: "
                    f"expected={expected!r} actual={actual!r}"
                )

        db_budget = item.anggaran_rp_ribu
        expected_budget = src["budget"]
        if db_budget != expected_budget:
            raise RuntimeError(
                f"STOP: anggaran mismatch item={src['no']}: "
                f"expected={expected_budget!r} actual={db_budget!r}"
            )

        for month in (
            "januari", "februari", "maret", "april", "mei", "juni",
            "juli", "agustus", "september", "oktober", "november", "desember"
        ):
            if getattr(item, f"target_{month}") is not None:
                raise RuntimeError(
                    f"STOP: source target {month} blank, tetapi DB item "
                    f"{src['no']} berisi {getattr(item, f'target_{month}')!r}"
                )
            if getattr(item, f"realisasi_{month}") is not None:
                raise RuntimeError(
                    f"STOP: source realisasi {month} blank, tetapi DB item "
                    f"{src['no']} berisi {getattr(item, f'realisasi_{month}')!r}"
                )

    # Existing canonical KM labels must remain unchanged.
    current = {
        x.pk: x.indikator_kinerja_kunci
        for x in ItemKontrakManajemen.objects.filter(pk__in=km_before_labels)
    }
    if current != km_before_labels:
        raise RuntimeError(
            "STOP: label canonical KM existing berubah. Transaction rollback."
        )

    print(
        f"RKM id={summary.pk} | unit={summary.unit_bisnis_id} | "
        f"KM={summary.kontrak_manajemen_id} | items={len(items)}"
    )
    print("Source preservation : 16/16 OK")
    print("Monthly blank fields : 16/16 OK")
    print("Canonical KM labels  : UNTOUCHED OK")
    print("VERIFY 16/16 OK")


def execute(apply):
    source_audit()
    unit = resolve_unit()
    km = resolve_km(unit)
    anchors = build_existing_anchors(km)
    ensure_no_existing_rkm(unit, km)

    # Snapshot every existing KM label. Technical bridges may be added, but no
    # current/signed KM item may be relabelled.
    km_before_labels = {
        x.pk: x.indikator_kinerja_kunci
        for x in ItemKontrakManajemen.objects.filter(kontrak=km)
    }

    if apply:
        backup_sqlite()

    bridge_count = None
    summary_id = None

    try:
        with transaction.atomic():
            km_locked = KontrakManajemen.objects.select_for_update().get(pk=km.pk)

            # Re-resolve anchors after lock so mapping is guaranteed current.
            anchors_locked = build_existing_anchors(km_locked)
            mapping, bridge_count = build_mapping(km_locked, anchors_locked)
            summary = create_summary(unit, km_locked)
            summary_id = summary.pk
            create_items(summary, mapping)
            verify(summary, km_before_labels)

            if not apply:
                raise DryRunRollback()

    except DryRunRollback:
        banner("RINGKASAN DRY RUN")
        print(f"Unit                 : {unit.pk} {unit.name!r}")
        print(f"KM                   : {km.pk} {km.judul!r}")
        print("Source RKM items     : 16")
        print("Canonical anchors    : 10")
        print("Technical bridges    : 6 (ROLLBACK)")
        print("RKM Summary          : 1 (ROLLBACK)")
        print("RKM Items            : 16 (ROLLBACK)")
        print("Existing KM relabel  : 0")
        print("Monthly target/actual: source blank, tetap blank")
        print("Database             : TIDAK BERUBAH")
        print("\nDRY RUN SELESAI — transaction rollback berhasil.")
        return

    banner("APPLY BERHASIL — RKM SETPER JULI 2026")
    summary = RKMSummary.objects.get(pk=summary_id)
    items = list(
        RKMItem.objects.filter(summary=summary)
        .select_related("km_item")
        .order_by("no_item")
    )

    print(
        f"RKM id={summary.pk} | {summary.judul} "
        f"| unit={summary.unit_bisnis} | KM={summary.kontrak_manajemen_id}"
    )
    print("Items              :", len(items))
    print("Technical bridges  :", bridge_count)
    print("Status             :", summary.status)
    print("Status pengajuan   :", getattr(summary, "status_pengajuan", None))
    print("Monthly realization: BLANK sesuai source")
    print("VERIFY             : 16/16 OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit perubahan. Default adalah dry-run transactional rollback.",
    )
    args = parser.parse_args()

    banner("IMPORT RKM SETPER — JULI 2026 V1 SAFE")
    print("Mode:", "APPLY" if args.apply else "DRY RUN")
    print("Settings:", os.environ.get("DJANGO_SETTINGS_MODULE"))

    try:
        execute(args.apply)
    except (RuntimeError, ValidationError) as exc:
        print(f"\nSTOP: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
