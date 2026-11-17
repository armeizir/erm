"""Explicit user-supplied history for the single Draft MRK-02 revision 06."""
from datetime import date, datetime
from pathlib import Path
import sqlite3
from django.db import connection, transaction
from django.utils import timezone
from smt.models import Document, DocumentRevisionEntry

notes = [
    ("05", date(2023, 8, 23), "Penetapan awal prosedur evaluasi kinerja manajemen risiko korporat (Kode Dokumen: PI-bright-CORP-PRM-02)."),
    ("06", None, "1. Pemutakhiran pengkodean dokumen dari PI-bright-CORP-PRM-02 menjadi PI-bright-CORP-MRK-02.\n\n"
     "2. Restrukturisasi Bab 4 (Tanggung Jawab) dengan penjelasan peranan spesifik: Pemilik Risiko, Risk Officer, Risk Champion/Pejabat Pemeriksa, Pairing Officer, Fungsi Manajemen Risiko & Kepatuhan, serta Pejabat Berwenang.\n\n"
     "3. Penjabaran tujuan terstruktur menjadi 5 poin utama (1.1–1.5).\n\n"
     "4. Pengelolaan lampiran dan formulir kerja secara terpisah melalui sistem SMT di PRISMA untuk menjamin fleksibilitas operasional."),
]
qs = Document.objects.filter(jenis="PI", nomor="PI-bright-CORP-MRK-02", revisi="06")
if qs.count() != 1:
    raise SystemExit("STOP: dokumen PI-bright-CORP-MRK-02 revisi 06 tidak ditemukan secara unik.")
doc = qs.get()
if doc.status != "draft":
    raise SystemExit("STOP: pengisian awal hanya untuk dokumen Draft.")
if doc.daftar_perubahan.exists():
    raise SystemExit("STOP: riwayat sudah berisi data. Periksa melalui form; tidak ditimpa.")
connection.ensure_connection()
if connection.vendor != "sqlite":
    raise SystemExit("STOP: backup ini khusus SQLite lokal.")
folder = Path("backups") / ("before_seed_smt_history_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
folder.mkdir(parents=True)
backup = sqlite3.connect(folder / "database.sqlite3")
try:
    connection.connection.backup(backup)
finally:
    backup.close()
with transaction.atomic():
    doc = qs.select_for_update().get()
    if doc.status != "draft" or doc.daftar_perubahan.exists():
        raise SystemExit("STOP: dokumen berubah; tidak ada data ditambahkan.")
    for index, (rev, day, note) in enumerate(notes, 1):
        entry = DocumentRevisionEntry(document=doc, revisi=rev, tanggal_berlaku=day, uraian=note, urutan=index)
        entry.full_clean()
        entry.save()
    qs.update(verifikator_tanggal=None, pengesah_tanggal=None, diperbarui_pada=timezone.now())
print("BACKUP DATABASE:", folder.resolve())
print("PASS: revisi 05 dan 06 ditambahkan sebagai dua baris.")
print("Catatan Revisi lama, tanggal berlaku dokumen, bab lain, dan lampiran tetap tersimpan.")
