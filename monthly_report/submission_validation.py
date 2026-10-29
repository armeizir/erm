"""Shared, read-only monitoring validation for submit and admin guidance."""
from decimal import Decimal, InvalidOperation
from risk.services.kpmr_owner import residual_owner_items


def blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def required_monitoring_fields(item, owner=True):
    fields = [
        ('status_rencana_perlakuan', 'status mitigasi'),
        ('progress_pelaksanaan_percent', 'progres mitigasi'),
        ('realisasi_rencana_perlakuan', 'realisasi perlakuan (tulis belum dilaksanakan bila belum berjalan)'),
        ('realisasi_output_perlakuan', 'realisasi output (tulis belum ada bila belum tersedia)'),
        ('realisasi_biaya_perlakuan', 'realisasi biaya (isi 0 jika tanpa biaya)'),
    ]
    if owner:
        fields = [('risk_event', 'risiko')] + fields
        risk = getattr(item, 'risk_event', None)
        if getattr(risk, 'jenis_risiko', None) == 'kuantitatif':
            fields += [('realisasi_nilai_dampak', 'nilai dampak aktual'),
                       ('realisasi_nilai_probabilitas', 'probabilitas aktual (%)')]
        fields += [('realisasi_skala_dampak', 'skala dampak'),
                   ('realisasi_skala_probabilitas', 'skala probabilitas')]
    return fields


def item_monitoring_issues(item, owner=True):
    issues = []
    def add(name, label):
        if not any(x['name'] == name for x in issues):
            issues.append({'name': name, 'label': label, 'derived': False})
    for name, label in required_monitoring_fields(item, owner):
        if blank(getattr(item, name, None)):
            add(name, label)
    if blank(getattr(item, 'realisasi_pic', None)) and not getattr(item, 'realisasi_pic_organization_unit_id', None):
        add('realisasi_pic', 'PIC pelaksanaan')
    if getattr(item, 'status_rencana_perlakuan', None) in ('revisi', 'discontinue', 'revise') and blank(getattr(item, 'penjelasan_status_rencana', None)):
        add('penjelasan_status_rencana', 'penjelasan perubahan/status mitigasi')

    checks = [('progress_pelaksanaan_percent', 'progres mitigasi 0–100%', Decimal('100')),
              ('realisasi_biaya_perlakuan', 'biaya non-negatif', None)]
    risk = getattr(item, 'risk_event', None)
    kind = getattr(risk, 'jenis_risiko', None)
    if owner:
        if kind not in ('kuantitatif', 'kualitatif'):
            add('risk_event', 'jenis risiko pada profil belum ditetapkan')
        if kind == 'kuantitatif':
            checks += [('realisasi_nilai_dampak', 'dampak non-negatif', None),
                       ('realisasi_nilai_probabilitas', 'probabilitas 0–100%', Decimal('100'))]
    for name, label, maximum in checks:
        value = getattr(item, name, None)
        if blank(value):
            continue
        try:
            value = Decimal(str(value))
            valid = value.is_finite() and value >= 0 and (maximum is None or value <= maximum)
        except (InvalidOperation, ValueError, TypeError):
            valid = False
        if not valid:
            add(name, label + ' tidak valid')

    if owner:
        impact = getattr(item, 'realisasi_skala_dampak', None)
        probability = getattr(item, 'realisasi_skala_probabilitas', None)
        if impact is not None and probability is not None:
            matrix = item._get_active_matrix()
            cell = matrix.get_cell(impact, probability) if matrix else None
            if cell is None or getattr(cell, 'skor', None) is None:
                add('realisasi_skala_dampak', 'kombinasi skala tidak memiliki sel matriks risiko')
        if risk and not blank(getattr(risk, 'key_risk_indicators', None)):
            numeric = getattr(item, 'realisasi_nilai_kri', None)
            text = getattr(item, 'realisasi_kri_text', None)
            if blank(numeric) and blank(text):
                add('realisasi_kri_text', 'realisasi KRI (angka atau teks/komposit)')
            elif not blank(numeric) and not blank(text):
                add('realisasi_kri_text', 'pilih satu realisasi KRI: angka atau teks/komposit')
            if not blank(numeric):
                try:
                    valid = Decimal(str(numeric)).is_finite()
                except (InvalidOperation, ValueError, TypeError):
                    valid = False
                if not valid:
                    add('realisasi_nilai_kri', 'nilai realisasi KRI tidak valid')
            if blank(getattr(item, 'realisasi_threshold_kri', None)):
                add('realisasi_kri_text', 'status threshold KRI belum tersedia; periksa nilai dan threshold')
    return issues


def report_submission_issues(report):
    items = list(report.items.select_related('risk_event', 'risk_event__summary').all())
    if not items:
        return ['Laporan belum memiliki item risiko.']
    owners = {item.pk for item in residual_owner_items(items)}
    issues = []
    for item in items:
        risk = getattr(item, 'risk_event', None)
        number = getattr(risk, 'no_item', None) or getattr(risk, 'no_risiko', None) or '?'
        cause = getattr(risk, 'no_penyebab_risiko', None) or '-'
        missing = item_monitoring_issues(item, item.pk in owners)
        if missing:
            issues.append(f"Risiko {number}, penyebab {cause} (item {item.pk}): " + ', '.join(x['label'] for x in missing) + '.')
    return issues


def assert_report_submission_complete(report):
    from django.core.exceptions import ValidationError
    issues = report_submission_issues(report)
    if issues:
        raise ValidationError(['Laporan belum dapat disubmit. Lengkapi dan simpan data berikut:'] + issues)
