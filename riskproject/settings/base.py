import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key


BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=None):
    value = os.environ.get(name)
    if value is None:
        return list(default or [])
    return [item.strip() for item in value.split(",") if item.strip()]


def env_required(name):
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(f"Environment variable {name} is required.")
    return value


DEBUG = env_bool("DEBUG", default=False)
SECRET_KEY = os.environ.get("SECRET_KEY") or get_random_secret_key()
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", default=[])

# ReAssessmentSummary menggunakan inline formset yang dapat melampaui batas
# bawaan Django (1.000 field) saat satu profil memuat banyak item risiko.
# Batas tetap dibuat eksplisit dan terbatas agar proteksi TooManyFieldsSent aktif.
DATA_UPLOAD_MAX_NUMBER_FIELDS = int(
    os.environ.get("DATA_UPLOAD_MAX_NUMBER_FIELDS", "5000")
)
DATA_UPLOAD_MAX_MEMORY_SIZE = int(
    os.environ.get("DATA_UPLOAD_MAX_MEMORY_SIZE", str(30 * 1024 * 1024))
)


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "masterdata",
    "km",
    "reassessment.apps.ReassessmentConfig",
    "kpmr",
    "imports",
    "monthly_report",
    "awareness",
    "risk.apps.RiskConfig",
    "corporate_risk",
    "django_extensions",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "riskproject.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "riskproject.wsgi.application"

DATABASES = {}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = os.environ.get("STATIC_URL", "/static/")
STATIC_ROOT = os.environ.get("STATIC_ROOT", BASE_DIR / "staticfiles")
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = os.environ.get("MEDIA_URL", "/media/")
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", BASE_DIR / "media")
NAS_EVIDENCE_ROOT = os.environ.get("NAS_EVIDENCE_ROOT", "/mnt/nas_mrk/ERM")
NAS_EVIDENCE_URL = "/monthly-report/evidence/"
NAS_EVIDENCE_MOUNT_ROOT = os.environ.get("NAS_EVIDENCE_MOUNT_ROOT", "/mnt/nas_mrk")
NAS_EVIDENCE_REQUIRE_MOUNT = env_bool("NAS_EVIDENCE_REQUIRE_MOUNT", default=not DEBUG)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTHENTICATION_BACKENDS = [
    "risk.backends.PLNLDAPBackend",
    "risk.backends.SuperuserOnlyModelBackend",
]
LOGIN_URL = "/admin/login/"

LDAP_ENABLED = env_bool("LDAP_ENABLED", default=True)
LDAP_SERVER = os.environ.get("LDAP_SERVER", "")
LDAP_BASE_DN = os.environ.get("LDAP_BASE_DN", "")
LDAP_DOMAIN = os.environ.get("LDAP_DOMAIN", "")
LDAP_USER_FILTER = os.environ.get("LDAP_USER_FILTER", "(sAMAccountName={username})")
LDAP_EMAIL_DOMAIN = os.environ.get("LDAP_EMAIL_DOMAIN", "")
LDAP_DEBUG = env_bool("LDAP_DEBUG", default=False)
LDAP_SUPERUSER_USERNAMES = {value.lower() for value in env_list("LDAP_SUPERUSER_USERNAMES")}
LDAP_SUPERUSER_EMAILS = {value.lower() for value in env_list("LDAP_SUPERUSER_EMAILS")}

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", default=False)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "webmaster@localhost")

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
