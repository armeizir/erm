# PROD Deploy 2026-05-25

## Prinsip

Jangan replace database PROD dengan `db.sqlite3` lokal. Deploy kode lewat git, lalu apply migration dan data terpilih setelah backup database PROD.

## Urutan Aman di Server PROD

1. Backup database PROD.
2. Pull kode terbaru.
3. Aktifkan virtualenv.
4. Jalankan migration dan check:

```bash
python manage.py migrate
python manage.py check
```

5. Update user dan pairing risk officer/champion/pairing:

```bash
python manage.py shell -c "from risk.scripts.seed_risk_users_2026 import run; run()"
```

6. Jika data lokal perlu dipindahkan, copy isi `prod_exports_20260525.tar.gz` ke server, extract, lalu load fixture berurutan:

```bash
tar -xzf prod_exports_20260525.tar.gz
python manage.py loaddata prod_exports/01_masterdata_settings_20260525.json
python manage.py loaddata prod_exports/02_pairing_assignments_20260525.json
python manage.py loaddata prod_exports/03_rkm_monthly_reports_20260525.json
```

7. Copy logo ke media PROD:

```bash
mkdir -p media/system/logo
cp prod_exports/pln_batam_logo.png media/system/logo/pln_batam_logo.png
```

8. Restart service aplikasi.

## Catatan

Fixture `03_rkm_monthly_reports_20260525.json` membutuhkan data kontrak manajemen, profil risiko, dan user referensi yang sesuai dengan database lokal. Jika `loaddata` gagal karena foreign key, jangan dipaksa; backup tetap aman, lalu sinkronkan data master/referensi yang kurang terlebih dahulu.
