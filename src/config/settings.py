import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from config.sso import validate_authelia_email_header
from config.webpush_keys import WebPushKeyError, load_webpush_keys

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent

DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")
if not DEBUG and (SECRET_KEY == "dev-only-change-me" or len(SECRET_KEY) < 50):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must contain at least 50 characters when DJANGO_DEBUG=0.")

default_hosts = "localhost,127.0.0.1" if DEBUG else ""
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", default_hosts).split(",") if host.strip()]
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be configured when DJANGO_DEBUG=0.")
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]

HTTPS_ENABLED = os.getenv("DJANGO_HTTPS", "0") == "1"
SECURE_SSL_REDIRECT = HTTPS_ENABLED
SESSION_COOKIE_SECURE = HTTPS_ENABLED
CSRF_COOKIE_SECURE = HTTPS_ENABLED
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_HSTS_SECONDS", "0")) if HTTPS_ENABLED else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = HTTPS_ENABLED and os.getenv("DJANGO_HSTS_INCLUDE_SUBDOMAINS", "0") == "1"
SECURE_HSTS_PRELOAD = HTTPS_ENABLED and os.getenv("DJANGO_HSTS_PRELOAD", "0") == "1"
if os.getenv("DJANGO_TRUST_PROXY_SSL_HEADER", "0") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

AUTHELIA_SSO_ENABLED = os.getenv("AUTHELIA_SSO_ENABLED", "0") == "1"
_authelia_sso_email_header = os.getenv("AUTHELIA_SSO_EMAIL_HEADER", "Remote-Email")
AUTHELIA_SSO_EMAIL_HEADER = (
    validate_authelia_email_header(_authelia_sso_email_header)
    if AUTHELIA_SSO_ENABLED
    else _authelia_sso_email_header.strip()
)

PASSKEY_ENABLED = os.getenv("PASSKEY_ENABLED", "0") == "1"
PASSKEY_RP_ID = os.getenv("PASSKEY_RP_ID", "").strip()
PASSKEY_RP_NAME = os.getenv("PASSKEY_RP_NAME", "Fliegerlager-Abrechnung").strip()
PASSKEY_ORIGIN = os.getenv("PASSKEY_ORIGIN", "").strip()
PASSKEY_CHALLENGE_TTL_SECONDS = 300

WEB_PUSH_ENABLED = os.getenv("WEB_PUSH_ENABLED", "0") == "1"
WEB_PUSH_KEY_DIR = Path(os.getenv("WEB_PUSH_KEY_DIR", "/run/secrets/webpush"))
try:
    _web_push_keys = load_webpush_keys(os.environ, WEB_PUSH_KEY_DIR) if WEB_PUSH_ENABLED else None
except WebPushKeyError as error:
    raise ImproperlyConfigured(str(error)) from error
WEB_PUSH_VAPID_PUBLIC_KEY = _web_push_keys.public_key if _web_push_keys else ""
WEB_PUSH_VAPID_PRIVATE_KEY = _web_push_keys.private_key if _web_push_keys else ""
WEB_PUSH_VAPID_SUBJECT = os.getenv("WEB_PUSH_VAPID_SUBJECT", "mailto:admin@example.invalid").strip()
WEB_PUSH_WORKER_INTERVAL_SECONDS = int(os.getenv("WEB_PUSH_WORKER_INTERVAL_SECONDS", "60"))
if WEB_PUSH_ENABLED and not (WEB_PUSH_VAPID_PUBLIC_KEY and WEB_PUSH_VAPID_PRIVATE_KEY and WEB_PUSH_VAPID_SUBJECT):
    raise ImproperlyConfigured(
        "WEB_PUSH_VAPID_PUBLIC_KEY, WEB_PUSH_VAPID_PRIVATE_KEY and WEB_PUSH_VAPID_SUBJECT are required."
    )

DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.SecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "config.middleware.AutheliaSSOMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.optional_authentication_features",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "billing.auth.EmailOrUsernameBackend",
    "billing.auth.AutheliaEmailBackend",
    "django.contrib.auth.backends.ModelBackend",
]

LANGUAGE_CODE = "de-de"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
# Static assets are served from the application origin. WhiteNoise defaults to a
# wildcard CORS header for CDN use, which is unnecessary here and weakens the
# same-origin policy enforced by SecurityHeadersMiddleware.
WHITENOISE_ALLOW_ALL_ORIGINS = False
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "camp-list"
LOGOUT_REDIRECT_URL = "login"

UPDATE_AGENT_URL = os.getenv("UPDATE_AGENT_URL", "").rstrip("/")
UPDATE_AGENT_TOKEN = os.getenv("UPDATE_AGENT_TOKEN", "")
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", str(ROOT_DIR / "backups")))
DAILY_SETTLEMENT_BACKUP_INTERVAL_SECONDS = int(os.getenv("DAILY_SETTLEMENT_BACKUP_INTERVAL_SECONDS", "300"))
APP_VERSION = os.getenv("APP_VERSION", "development")
APP_REVISION = os.getenv("APP_REVISION", "unknown")
APP_BUILD_DATE = os.getenv("APP_BUILD_DATE", "unknown")
APP_CHANGE = os.getenv("APP_CHANGE", "Lokaler Entwicklungsstand")
