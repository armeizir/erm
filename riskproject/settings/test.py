from .dev import *

# Test client menggunakan HTTP internal dan tidak perlu diarahkan ke HTTPS.
SECURE_SSL_REDIRECT = False
SECURE_PROXY_SSL_HEADER = None
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Jangan pernah mengirim email sungguhan saat test.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Host bawaan Django test client.
ALLOWED_HOSTS = list(
    dict.fromkeys([
        *globals().get("ALLOWED_HOSTS", []),
        "testserver",
        "localhost",
        "127.0.0.1",
    ])
)

# Mempercepat test tanpa memengaruhi production.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
