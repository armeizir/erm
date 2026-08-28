from .base import *


DEBUG = False
SECRET_KEY = env_required("SECRET_KEY")
# Required in production because AppSetting stores AI/SMTP secrets encrypted in DB.
APP_ENCRYPTION_KEY = env_required("APP_ENCRYPTION_KEY")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must be set explicitly in production.")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# BEGIN ERM HTTPS PROXY SETTINGS
# Request publik menggunakan HTTPS, sedangkan Nginx meneruskannya
# ke Gunicorn melalui HTTP lokal.
SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([
    *globals().get("CSRF_TRUSTED_ORIGINS", []),
    "https://erm.plnbatam.com",
]))
# END ERM HTTPS PROXY SETTINGS


# TEMP_DJANGO_ERROR_LOGGING_20260807
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console_error": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django.request": {
            "handlers": ["console_error"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console_error"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
