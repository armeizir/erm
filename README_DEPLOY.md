# Executive Risk Dashboard — Patch

Tujuan patch ini adalah menambah **halaman baru** untuk Direksi/TV digital signage tanpa mengubah `templates/dashboard.html` atau view RCC existing.

## File baru
- `risk/executive_signage.py` — view & data adapter Executive Risk Dashboard.
- `templates/executive_risk_dashboard.html` — layout 16:9 per risiko + TV signage.
- `risk/test_executive_signage.py` — smoke test halaman baru.
- `apply_executive_dashboard_patch.py` — menambah URL baru secara idempotent dan membackup `urls.py`.

## Instalasi di source project
Dari folder project yang berisi `manage.py`:

```bash
# 1. Backup project lebih dulu sesuai prosedur internal.
# 2. Copy folder risk/, templates/, dan apply_executive_dashboard_patch.py dari paket ini ke project root.
python apply_executive_dashboard_patch.py --project-root .

# 3. Validasi
python manage.py check
python manage.py test risk.test_executive_signage -v 2
```

Tidak ada migration database dan tidak perlu `collectstatic` karena CSS/JS berada di template baru.

## URL
- Normal: `/executive-risk/`
- Pilih risiko/tahun: `/executive-risk/?year=2026&risk=<ID_RISIKO>`
- TV signage: `/executive-risk/?tv=1`
- Interval rotasi 30 detik: `/executive-risk/?tv=1&seconds=30`

Mode TV otomatis berpindah ke risiko berikutnya dan reload data pada setiap perpindahan. Minimum interval 10 detik, maksimum 120 detik.

## Sumber data yang dipakai
1. Profil Risiko Korporat: judul, residual score/level/status.
2. Risk Metric + Metric History: posisi aktual, target RKAP dan driver/KPI.
3. KRI risiko unit yang sudah dipetakan ke risiko korporat: fallback driver bila Risk Metric belum tersedia.
4. KRI pada penyebab risiko korporat: fallback berikutnya.
5. Multi Metric Monte Carlo: forecast, worst case, potential loss.
6. Rencana Perlakuan Risiko Korporat: Management Decision.

Jika suatu sumber belum terisi, dashboard menampilkan `–` / pesan belum tersedia. Tidak ada angka contoh yang di-hard-code.

## Keamanan digital signage
Halaman tetap memakai login dan permission `risk.view_profilrisikokorporatitem`. Untuk TV, gunakan akun viewer/read-only khusus pada browser signage; jangan membuka endpoint secara public/anonymously.
