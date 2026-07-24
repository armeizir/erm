# Security Hardening Phase 1 v2 — Encrypted AppSetting Secrets

Versi ini menggantikan patch Phase 1 sebelumnya untuk mekanisme AI/SMTP secret.

## Keputusan desain final

- AI API Key tetap dikelola melalui **Admin > Pengaturan Aplikasi**.
- SMTP Password tetap dikelola melalui **Admin > Pengaturan Aplikasi**.
- Nilai secret **tidak pernah ditampilkan kembali sebagai plaintext** saat halaman admin dibuka.
- Database menyimpan ciphertext Fernet (`fernet:v1:...`), bukan plaintext.
- Aplikasi mendekripsi secret hanya di memori saat integrasi AI/SMTP membutuhkannya.
- Hanya master key `APP_ENCRYPTION_KEY` yang disimpan di environment/secret manager server.

## Sebelum menerapkan patch

Backup source/repository terlebih dahulu. Jangan menghapus atau mengganti database produksi.

## Local — urutan penerapan

```bash
cd /Users/armeizir/risk_app/riskproject
source .venv/bin/activate

git status
git apply --check ~/Downloads/security_hardening_phase1_v2.patch
git apply ~/Downloads/security_hardening_phase1_v2.patch

# Hapus file legacy secara terpisah; sengaja tidak dimasukkan ke patch agar
# SECRET_KEY lama dari riskproject/settings.py tidak tersalin ke file patch.
git rm riskproject/settings.py \
  "risk/admin copy.py" \
  "corporate_risk/admin copy.py"

pip install -r requirements.txt
```

Generate satu master encryption key untuk local:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Masukkan hasilnya ke `.env` / environment local:

```bash
APP_ENCRYPTION_KEY=<hasil-key>
```

**Jangan mengganti key tersebut setelah secret terenkripsi kecuali melakukan prosedur rotasi khusus.**

Lalu:

```bash
./scripts/security_preflight.sh
python manage.py check
python manage.py showmigrations risk | tail -10
python manage.py migrate
python manage.py test risk.test_secret_encryption awareness.tests
```

Migration yang diharapkan:

```text
risk.0065_encrypt_integration_secrets
```

Migration ini:
1. memperbesar kolom secret menjadi `TextField`,
2. membaca AI API Key/SMTP Password lama yang masih plaintext,
3. mengenkripsinya dengan `APP_ENCRYPTION_KEY`,
4. menyimpan ciphertext kembali ke database tanpa mengubah konfigurasi non-secret.

## Perilaku Admin setelah hardening

Pada **Pengaturan Aplikasi**:

- Status hanya menampilkan `Sudah dikonfigurasi (terenkripsi)` atau `Belum dikonfigurasi`.
- Field `API Key AI Baru` dan `SMTP Password Baru` selalu kosong ketika halaman dibuka.
- Membiarkan field baru kosong mempertahankan secret yang sudah ada.
- Mengisi nilai baru mengganti secret dan langsung menyimpannya terenkripsi.
- Checkbox hapus tersedia jika secret memang ingin dihapus.

## Production — urutan aman

### 1. Generate master key production satu kali

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Simpan hasilnya sebagai environment/secret manager:

```bash
APP_ENCRYPTION_KEY=<production-master-key>
```

`riskproject.settings.prod` mewajibkan variable ini tersedia.

### 2. Deploy kode dan dependency

```bash
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
python manage.py check --settings=riskproject.settings.prod
```

### 3. Migration

Pastikan `APP_ENCRYPTION_KEY` sudah aktif **sebelum**:

```bash
python manage.py migrate --settings=riskproject.settings.prod
```

Jangan menjalankan migration 0065 tanpa key production yang sudah ditetapkan.

### 4. Restart aplikasi dan uji

Uji minimal:
- login,
- halaman Pengaturan Aplikasi,
- pengiriman email test,
- satu fungsi AI,
- pastikan secret lama tidak muncul dalam HTML/admin.

### 5. Rotate credential lama

Karena backup/database lama pernah menyimpan plaintext, tetap lakukan rotasi:
- AI API Key lama → revoke dan buat key baru,
- SMTP Password lama → ganti password,
- masukkan credential pengganti melalui Pengaturan Aplikasi.

Database baru akan menyimpan credential pengganti dalam bentuk ciphertext.

## Penting

`APP_ENCRYPTION_KEY` berbeda fungsi dengan Django `SECRET_KEY`. Keduanya harus disimpan aman dan tidak boleh dimasukkan ke repository atau source ZIP.

Clean ZIP yang disediakan tidak berisi database production, backup database, `.env`, `.git`, virtualenv, atau file backup source.
