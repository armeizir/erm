"""Targeted KPMR correction emails; preparing a message never sends it."""
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
    # Include exact calculation notes, including nominal exposure and zero-target errors.
    lines.extend(['', 'RINCIAN HASIL PEMERIKSAAN PRISMA:'])
    lines.extend(str(note) for note in calculation.notes if note)
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
            'body': '\n'.join(lines), **recipients}


def send_notification(prepared):
    if not prepared['to']:
        raise ValueError('Risk Officer dengan email valid tidak tersedia; email tidak dikirim.')
    app = AppSetting.objects.first()
    message = EmailMultiAlternatives(
        subject=prepared['subject'], body=prepared['body'],
        from_email=getattr(app, 'default_from_email', '') or settings.DEFAULT_FROM_EMAIL,
        to=prepared['to'], cc=prepared['cc'], connection=profile_mail_connection(),
    )
    if message.send(fail_silently=False) != 1:
        raise RuntimeError('Backend tidak melaporkan keberhasilan pengiriman email.')
