"""Private evidence storage. Files have no public MEDIA_URL."""
from pathlib import Path
from uuid import uuid4
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible

MAX_EVIDENCE_BYTES = 20 * 1024 * 1024
ALLOWED = {'.pdf', '.png', '.jpg', '.jpeg', '.xlsx', '.docx', '.csv', '.txt'}

@deconstructible
class PrivateEvidenceStorage(FileSystemStorage):
    def __init__(self):
        root = Path(getattr(settings, 'PRIVATE_EVIDENCE_ROOT', Path(settings.BASE_DIR) / 'private_evidence')).resolve()
        public = getattr(settings, 'MEDIA_ROOT', '')
        if public:
            media = Path(public).resolve()
            if root == media or media in root.parents:
                raise ImproperlyConfigured('PRIVATE_EVIDENCE_ROOT harus di luar MEDIA_ROOT publik.')
        super().__init__(location=str(root), base_url=None,
                         file_permissions_mode=0o600, directory_permissions_mode=0o700)

    def url(self, name):
        raise ValueError('Eviden privat hanya dapat diunduh melalui PRISMA.')

private_evidence_storage = PrivateEvidenceStorage()


def evidence_upload_path(instance, filename):
    return f'report_{instance.report_id}/{uuid4().hex}{Path(filename).suffix.lower()}'


def validate_evidence_file(value):
    import zipfile
    suffix = Path(value.name).suffix.lower()
    if suffix not in ALLOWED:
        raise ValidationError('Format diizinkan: PDF, PNG, JPG, XLSX, DOCX, CSV, TXT.')
    if not value.size or value.size > MAX_EVIDENCE_BYTES:
        raise ValidationError('Ukuran eviden harus lebih dari 0 dan maksimum 20 MB.')
    position = value.tell()
    try:
        value.seek(0)
        head = value.read(16)
        valid = True
        if suffix == '.pdf': valid = head.startswith(b'%PDF-')
        elif suffix == '.png': valid = head.startswith(b'\x89PNG\r\n\x1a\n')
        elif suffix in {'.jpg', '.jpeg'}: valid = head.startswith(b'\xff\xd8\xff')
        elif suffix in {'.xlsx', '.docx'}:
            try:
                value.seek(0)
                with zipfile.ZipFile(value) as archive:
                    expected = 'xl/workbook.xml' if suffix == '.xlsx' else 'word/document.xml'
                    valid = '[Content_Types].xml' in archive.namelist() and expected in archive.namelist()
            except (zipfile.BadZipFile, OSError):
                valid = False
        else:
            value.seek(0)
            try:
                text = value.read().decode('utf-8-sig')
                valid = '\x00' not in text
            except UnicodeDecodeError:
                valid = False
        if not valid:
            raise ValidationError('Isi file tidak sesuai ekstensi atau file tidak valid.')
    finally:
        value.seek(position)
