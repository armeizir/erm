from .base import *


DEBUG = env_bool("DEBUG", default=True)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]"])

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("SQLITE_NAME", BASE_DIR / "db.sqlite3"),
        "OPTIONS": {
            "timeout": int(os.environ.get("SQLITE_TIMEOUT", "30")),
        },
    }
}

CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", default=False)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", default=False)
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=False)
