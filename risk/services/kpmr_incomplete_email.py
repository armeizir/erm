"""Targeted KPMR correction emails; preparing a message never sends it."""
from html import escape
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse
from risk.models import AppSetting, PenugasanUnitBisnis
from risk.services.profile_completeness import profile_mail_connection


def user_email(user):
    if user is None or not user.is_active:
        return ''
    address = (user.email or '').strip().casefold()
    try:
        validate_email(address)
    except ValidationError:
        return ''
    return address


def recipient_lists(assignments, reviewer=None, approver=None):
    groups = {'Risk Officer': [], 'Risk Champion': [], 'Pairing Officer': [], 'Approver': [approver]}
    roles = {'RISK_OFFICER': 'Risk Officer', 'RISK_CHAMPION': 'Risk Champion', 'PAIRING_OFFICER': 'Pairing Officer'}
    for assignment in assignments:
        if assignment.peran in roles:
            groups[roles[assignment.peran]].append(assignment.user)
    # Reviewed by is the report's recorded champion; active assignments also receive CC.
    groups['Risk Champion'].append(reviewer)
    warnings, valid = [], {}
    for role, users in groups.items():
        valid[role] = sorted({address for user in users if (address := user_email(user))})
        if not valid[role]:
            warnings.append(f'{role}: penerima aktif dengan email valid tidak tersedia.')
        for user in users:
            if user is not None and not user_email(user):
                warnings.append(f'{role}: user {user.pk} tidak aktif atau email tidak valid.')
    to = valid['Risk Officer']
    cc = sorted(set(valid['Risk Champion'] + valid['Pairing Officer'] + valid['Approver']) - set(to))
    return {'to': to, 'cc': cc, 'warnings': sorted(set(warnings))}


def prepare_notification(report, calculation, base_url=None):
    assignments = PenugasanUnitBisnis.objects.filter(
        unit_bisnis_id=report.reassessment.unit_bisnis_id,
        aktif=True, user__is_active=True,
    ).select_related('user').order_by('user__username', 'pk')
    recipients = recipient_lists(assignments, report.reviewed_by, report.approved_by)
    unit = report.reassessment.unit_bisnis.name
    period = str(report.periode)
    missing = [row for row in calculation.indicators if row.get('hasil') is None]
    lines = [f'Yth. Risk Officer {unit},',
        'Tembusan: Risk Champion, Approver, dan Pairing Officer', '',
        f'Laporan {period} berstatus {report.get_status_display()}, tetapi penilaian KPMR TW{calculation.quarter} belum lengkap.',
        f'Nilai sementara: {calculation.provisional_score}',
        f'Bobot tersedia: {calculation.assessed_weight}%', '', 'INDIKATOR YANG BELUM DINILAI:']
    for row in missing:
        lines.extend([f"- {row['kode']} — {row['nama']}", str(row.get('keterangan') or 'Periksa kelengkapan sumber penilaian.')])
    if not missing:
        lines.append('Periksa konsistensi bobot dan kelengkapan subindikator; hasil belum memenuhi status lengkap.')
    diagnostic = calculation.diagnostics or {}
    if any(row.get('kode') in {'I1', 'I4'} for row in missing):
        for row in diagnostic.get('rows', []):
            if row.get('missing'):
                lines.append(f"- Risiko {row['no_item']} — {row['event']} (item {row['item_id']}): " + ', '.join(row['missing']))
    details = '\n\n'.join(str(note) for note in calculation.notes if note)
    labels = {
        'aktual likelihood': 'Skala Probabilitas Aktual',
        'aktual impact': 'Skala Dampak Aktual',
        'aktual score/matrix cell': 'Skor risiko aktual (otomatis dari matriks)',
        'target likelihood': 'Skala Probabilitas Target',
        'target impact': 'Skala Dampak Target',
        'target score/matrix cell': 'Skor risiko target (otomatis dari matriks)',
    }
    for index, line in enumerate(lines):
        for old, new in labels.items():
            line = line.replace(old, new)
        lines[index] = line
    lines.extend(['', 'Rincian perhitungan tersedia pada lampiran diagnostik.'])
    url_root = (base_url or getattr(settings, 'APP_BASE_URL', '') or getattr(settings, 'SITE_URL', '')).rstrip('/')
    if not url_root.startswith(('https://', 'http://')):
        raise ValueError('Isi --base-url dengan alamat PRISMA lengkap, misalnya https://domain-perusahaan.')
    url = url_root + reverse('risk_admin:monthly_report_monthlyriskreport_change', args=[report.pk])
    lines.extend(['', f'Buka laporan: {url}', '',
        'Mohon periksa dokumen pendukung dan lengkapi data melalui alur perbaikan yang berwenang. '
        'Untuk laporan Approved/Locked, koordinasikan pembukaan revisi terlebih dahulu. '
        'Jangan mengisi angka perkiraan hanya untuk melengkapi penilaian.',
        'Notifikasi ini tidak mengubah data maupun status laporan.', '',
        'Bidang Manajemen Risiko & Kepatuhan', 'PT PLN Batam'])
    return {'subject': f'[PRISMA] Perbaikan Data KPMR Belum Lengkap – {unit} – {period}',
            'body': '\n'.join(lines),
            'html': render_notification_html(report, calculation, unit, period, lines, url),
            'diagnostic_attachment': details, **recipients}


def send_notification(prepared):
    if not prepared['to']:
        raise ValueError('Risk Officer dengan email valid tidak tersedia; email tidak dikirim.')
    app = AppSetting.objects.first()
    message = EmailMultiAlternatives(
        subject=prepared['subject'], body=prepared['body'],
        from_email=getattr(app, 'default_from_email', '') or settings.DEFAULT_FROM_EMAIL,
        to=prepared['to'], cc=prepared['cc'], connection=profile_mail_connection(),
    )
    if prepared.get('html'):
        message.attach_alternative(prepared['html'], 'text/html')
    if prepared.get('diagnostic_attachment'):
        message.attach('Rincian_Diagnostik_KPMR.txt', prepared['diagnostic_attachment'], 'text/plain')
    if message.send(fail_silently=False) != 1:
        raise RuntimeError('Backend tidak melaporkan keberhasilan pengiriman email.')


def render_notification_html(report, calculation, unit, period, lines, url):
    """Table layout and inline styles for common desktop/mobile mail clients."""
    e = lambda value: escape(str(value), quote=True)
    start = lines.index('INDIKATOR YANG BELUM DINILAI:') + 1
    stop = lines.index('Rincian perhitungan tersedia pada lampiran diagnostik.')
    findings = ''.join(
        '<p style="margin:0 0 12px;line-height:1.6;overflow-wrap:anywhere">' + e(line) + '</p>'
        for line in lines[start:stop] if line.strip()
    )
    return f'''<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#eef3f7;color:#243746;font-family:Arial,Helvetica,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eef3f7"><tr><td align="center" style="padding:24px 10px">
<table role="presentation" width="640" cellspacing="0" cellpadding="0" style="width:100%;max-width:640px;background:#ffffff;border:1px solid #dbe4ec">
<tr><td style="padding:24px 28px;background:#075b75;color:#ffffff">
<div style="font-size:24px;font-weight:bold;letter-spacing:2px">PRISMA</div>
<div style="font-size:12px;margin-top:6px;color:#d4ebf1">PT PLN BATAM · MANAJEMEN RISIKO &amp; KEPATUHAN</div>
<h1 style="font-size:23px;line-height:1.3;margin:22px 0 8px">Tindak Lanjut Kelengkapan KPMR</h1>
<div style="font-size:14px">{e(unit)} · {e(period)} · TW{e(calculation.quarter)}</div></td></tr>
<tr><td style="padding:24px 28px 12px;font-size:14px;line-height:1.6">
<p style="margin:0 0 8px">Yth. Risk Officer <strong>{e(unit)}</strong>,</p>
<p style="margin:0 0 20px;font-size:12px;color:#607587">Tembusan: Risk Champion, Approver, dan Pairing Officer</p>
<div style="padding:14px 16px;border-left:4px solid #d99618;background:#fff7e5;color:#77530d">
<strong>Penilaian belum lengkap</strong><br>Laporan berstatus {e(report.get_status_display())}. Masih ada data yang perlu ditindaklanjuti sebelum penilaian KPMR dapat diselesaikan.</div>
</td></tr>
<tr><td style="padding:8px 28px 20px"><table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>
<td width="50%" style="background:#edf6fa;padding:16px;border-right:4px solid #ffffff"><div style="font-size:12px;color:#536c7d">NILAI SEMENTARA</div><div style="font-size:30px;font-weight:bold;color:#075b75;margin-top:6px">{e(calculation.provisional_score)}</div></td>
<td width="50%" style="background:#edf6fa;padding:16px"><div style="font-size:12px;color:#536c7d">BOBOT TERSEDIA</div><div style="font-size:30px;font-weight:bold;color:#075b75;margin-top:6px">{e(calculation.assessed_weight)}%</div></td>
</tr></table></td></tr>
<tr><td style="padding:0 28px 18px;font-size:14px"><h2 style="font-size:17px;margin:0 0 14px;color:#173e51">Data yang perlu diperbaiki</h2>{findings}</td></tr>
<tr><td style="padding:0 28px 24px;font-size:14px;line-height:1.6">
<h2 style="font-size:17px;color:#173e51;margin:0 0 10px">Langkah tindak lanjut</h2>
<ol style="padding-left:20px;margin:0 0 22px"><li>Koordinasikan pembukaan revisi jika laporan sudah Approved/Locked.</li><li>Lengkapi data di atas sesuai dokumen pendukung.</li><li>Simpan dan ajukan kembali melalui proses review dan approval.</li></ol>
<table role="presentation" cellspacing="0" cellpadding="0"><tr><td bgcolor="#087f91" style="padding:13px 24px"><a href="{e(url)}" style="display:inline-block;color:#ffffff;text-decoration:none;font-size:15px;font-weight:bold">Buka Laporan di PRISMA →</a></td></tr></table>
<p style="font-size:12px;color:#607587;margin:14px 0 0;overflow-wrap:anywhere">Jika tombol tidak dapat dibuka, gunakan tautan:<br><a href="{e(url)}" style="color:#075b75;word-break:break-all">{e(url)}</a></p>
</td></tr>
<tr><td style="padding:16px 28px;background:#f5f8fa;border-top:1px solid #dbe4ec;font-size:12px;line-height:1.6;color:#607587">Rincian perhitungan tersedia pada lampiran diagnostik. Nilai ini masih sementara. Email ini tidak mengubah data atau status laporan.<br><br><strong>Bidang Manajemen Risiko &amp; Kepatuhan</strong><br>PT PLN Batam</td></tr>
</table></td></tr></table></body></html>'''
