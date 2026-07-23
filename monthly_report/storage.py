from django.conf import settings
from django.core.files.storage import FileSystemStorage
from os.path import abspath, ismount


class NasEvidenceStorage(FileSystemStorage):
    def _ensure_nas_available(self):
        if settings.NAS_EVIDENCE_REQUIRE_MOUNT and not ismount(
            settings.NAS_EVIDENCE_MOUNT_ROOT
        ):
            raise OSError(
                f"NAS eviden belum ter-mount pada {settings.NAS_EVIDENCE_MOUNT_ROOT}."
            )

    def _open(self, name, mode="rb"):
        self._ensure_nas_available()
        return super()._open(name, mode)

    def _save(self, name, content):
        self._ensure_nas_available()
        return super()._save(name, content)

    def exists(self, name):
        self._ensure_nas_available()
        return super().exists(name)

    @property
    def base_location(self):
        return str(settings.NAS_EVIDENCE_ROOT)

    @property
    def location(self):
        return abspath(self.base_location)

    @property
    def base_url(self):
        return settings.NAS_EVIDENCE_URL


def nas_evidence_storage():
    return NasEvidenceStorage()
