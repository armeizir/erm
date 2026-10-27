from pathlib import Path
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible

@deconstructible
class PrivateDocumentStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=getattr(settings, "SMT_DOCUMENT_ROOT", Path(settings.BASE_DIR) / "private_smt"))

    def url(self, name):
        raise ValueError("Dokumen SMT hanya dapat diunduh melalui akses terautentikasi.")
