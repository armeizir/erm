# Pengingat Otomatis Laporan Risiko Bulanan

## Aturan

- Dieksekusi setiap hari pukul 07.00 WIB.
- Periode target adalah bulan sebelumnya.
  - Eksekusi Agustus 2026 memeriksa laporan Juli 2026.
  - Eksekusi September 2026 memeriksa laporan Agustus 2026.
- Hanya versi terbaru per Profil Risiko yang diproses.
- Laporan berstatus `approved` atau `locked` tidak dikirim.
- Tahap dan penerima mengikuti konfigurasi notifikasi yang sudah ada.
- Pengiriman berhenti otomatis setelah laporan Approved.

## Uji tanpa mengirim

```bash
python manage.py send_monthly_report_daily_reminders \
  --date 2026-08-03 \
  --dry-run \
  --base-url https://erm.plnbatam.com
```

## Uji ke satu email

```bash
python manage.py send_monthly_report_daily_reminders \
  --date 2026-08-03 \
  --report-id 58 \
  --test-email armeizir@plnbatam.com \
  --base-url https://erm.plnbatam.com
```

## Pasang timer produksi

```bash
sudo cp deploy/systemd/erm-monthly-reminder.service \
  /etc/systemd/system/

sudo cp deploy/systemd/erm-monthly-reminder.timer \
  /etc/systemd/system/

sudo systemctl daemon-reload

systemd-analyze calendar \
  '*-*-* 07:00:00 Asia/Jakarta'

sudo systemctl enable --now erm-monthly-reminder.timer

systemctl list-timers \
  erm-monthly-reminder.timer \
  --all
```

## Periksa log

```bash
sudo systemctl status erm-monthly-reminder.timer --no-pager -l

sudo journalctl \
  -u erm-monthly-reminder.service \
  -n 200 \
  --no-pager -l
```
