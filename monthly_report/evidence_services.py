"""Evidence validation shared by submit entry points; no network link fetching."""
import hashlib
from django.core.exceptions import ValidationError


def assert_report_evidence_complete(report):
    records = list(report.evidences.exclude(document='').exclude(document__isnull=True))
    if not records:
        raise ValidationError('Unggah minimal satu Dokumen Eviden ke PRISMA sebelum submit. Link eksternal hanya referensi tambahan.')
    issues = []
    for record in records:
        digest = hashlib.sha256()
        size = 0
        try:
            with record.document.storage.open(record.document.name, 'rb') as file:
                while True:
                    chunk = file.read(1024 * 1024)
                    if not chunk: break
                    size += len(chunk); digest.update(chunk)
        except (OSError, ValueError):
            issues.append(f'Eviden {record.pk} ({record.title}) tidak dapat dibaca dari penyimpanan.')
            continue
        if size != record.file_size or digest.hexdigest() != record.sha256:
            issues.append(f'Integritas eviden {record.pk} ({record.title}) tidak sesuai arsip unggahan.')
    if issues:
        raise ValidationError(issues)
