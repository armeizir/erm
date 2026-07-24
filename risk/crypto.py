"""Application-layer encryption helpers for secrets stored in the database.

Only the master key (APP_ENCRYPTION_KEY) belongs in the server environment.
Individual integration credentials remain manageable from Django Admin and are
stored as Fernet ciphertext in the database.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

ENCRYPTED_PREFIX = "fernet:v1:"


def _fernet() -> Fernet:
    key = (getattr(settings, "APP_ENCRYPTION_KEY", "") or "").strip()
    if not key:
        raise ImproperlyConfigured(
            "APP_ENCRYPTION_KEY belum dikonfigurasi. Buat satu Fernet key dan "
            "simpan hanya di environment server sebelum menyimpan/memigrasikan secret."
        )
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ImproperlyConfigured(
            "APP_ENCRYPTION_KEY tidak valid. Gunakan Fernet key urlsafe-base64 32-byte."
        ) from exc


def is_encrypted_secret(value: str | None) -> bool:
    return bool(value) and str(value).startswith(ENCRYPTED_PREFIX)


def encrypt_secret(value: str | None) -> str:
    """Encrypt plaintext, while leaving an already-encrypted value untouched."""
    if value in (None, ""):
        return ""
    value = str(value)
    if is_encrypted_secret(value):
        return value
    token = _fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return f"{ENCRYPTED_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str:
    """Decrypt ciphertext.

    Legacy plaintext is returned unchanged only to support the controlled
    deployment window before migration 0065 encrypts existing rows.
    """
    if value in (None, ""):
        return ""
    value = str(value)
    if not is_encrypted_secret(value):
        return value

    token = value[len(ENCRYPTED_PREFIX) :]
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ImproperlyConfigured(
            "Secret database tidak dapat didekripsi. Periksa APP_ENCRYPTION_KEY; "
            "jangan mengganti master key tanpa proses rotasi yang benar."
        ) from exc
