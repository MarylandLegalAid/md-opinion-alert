"""
Django settings for the MD Opinion Alert project.

12-factor configuration via environment variables (django-environ).
See .env.example for the full list of variables.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
)

# Read a local .env file if present (development convenience; not used on Render).
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-only-key")
DEBUG = env("DEBUG")

if not DEBUG and SECRET_KEY == "insecure-dev-only-key":
    raise environ.ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set when DEBUG is false."
    )
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# Render injects the external hostname; trust it automatically.
RENDER_EXTERNAL_HOSTNAME = env("RENDER_EXTERNAL_HOSTNAME", default=None)
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# --- Entra OIDC -------------------------------------------------------------
# OIDC is considered configured when a client id is present. DEV_LOGIN_ENABLED
# (default: DEBUG) additionally enables Django's ModelBackend so local
# development works before the Entra app registration exists.
OIDC_RP_CLIENT_ID = env("OIDC_RP_CLIENT_ID", default="")
OIDC_RP_CLIENT_SECRET = env("OIDC_RP_CLIENT_SECRET", default="")
ENTRA_TENANT_ID = env("ENTRA_TENANT_ID", default="")
ADMIN_APP_ROLE = env("ADMIN_APP_ROLE", default="Admin")

OIDC_ENABLED = env.bool("OIDC_ENABLED", default=bool(OIDC_RP_CLIENT_ID))
DEV_LOGIN_ENABLED = env.bool("DEV_LOGIN_ENABLED", default=DEBUG)

_ENTRA_BASE = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID or 'common'}"
OIDC_OP_AUTHORIZATION_ENDPOINT = env(
    "OIDC_OP_AUTHORIZATION_ENDPOINT", default=f"{_ENTRA_BASE}/oauth2/v2.0/authorize"
)
OIDC_OP_TOKEN_ENDPOINT = env(
    "OIDC_OP_TOKEN_ENDPOINT", default=f"{_ENTRA_BASE}/oauth2/v2.0/token"
)
OIDC_OP_USER_ENDPOINT = env(
    "OIDC_OP_USER_ENDPOINT", default="https://graph.microsoft.com/oidc/userinfo"
)
OIDC_OP_JWKS_ENDPOINT = env(
    "OIDC_OP_JWKS_ENDPOINT", default=f"{_ENTRA_BASE}/discovery/v2.0/keys"
)
OIDC_RP_SIGN_ALGO = "RS256"
OIDC_RP_SCOPES = "openid profile email"
OIDC_CREATE_USER = True
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
LOGIN_URL = "/oidc/authenticate/" if OIDC_ENABLED else "/admin/login/"

# --- Apps / middleware ------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "mozilla_django_oidc",
    "accounts",
    "core",
    "ingestion",
    "keywords",
    "matching",
    "alerts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

AUTHENTICATION_BACKENDS = []
if OIDC_ENABLED:
    AUTHENTICATION_BACKENDS.append("accounts.auth.EntraOIDCBackend")
if DEV_LOGIN_ENABLED or not OIDC_ENABLED:
    # Password login for local development and the Django admin before the
    # Entra app registration is wired up.
    AUTHENTICATION_BACKENDS.append("django.contrib.auth.backends.ModelBackend")

AUTH_USER_MODEL = "accounts.User"

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"

# --- Database ---------------------------------------------------------------

DATABASES = {
    "default": env.db(
        "DATABASE_URL", default="postgres://mdoa:mdoa@localhost:5432/mdoa"
    )
}
DATABASES["default"]["CONN_MAX_AGE"] = 60

# --- Auth / i18n / static ---------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Security ---------------------------------------------------------------
# Render terminates TLS at its proxy.

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    # Render's health probe must not be bounced to https.
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# --- Scraper ------------------------------------------------------

SCRAPER_CONTACT_EMAIL = env("SCRAPER_CONTACT_EMAIL", default="contact@example.org")
SCRAPER_USER_AGENT = env(
    "SCRAPER_USER_AGENT",
    default=f"MD-Opinion-Alert/1.0 (appellate opinion monitor; +mailto:{SCRAPER_CONTACT_EMAIL})",
)
BACKFILL_START_YEAR = env.int("BACKFILL_START_YEAR", default=2024)
INGEST_PDF_DELAY_SECONDS = env.float("INGEST_PDF_DELAY_SECONDS", default=2.0)
ANOMALY_PDF_FAILURE_THRESHOLD = env.float("ANOMALY_PDF_FAILURE_THRESHOLD", default=0.2)

# --- Email ----------------------------------------------------------
# One config switch selects the transport. ACS is the production default once
# its env vars exist; console keeps local dev and pre-IT deployments harmless.

EMAIL_BACKEND_CHOICE = env("EMAIL_BACKEND_CHOICE", default="console")
EMAIL_BACKEND = {
    "console": "django.core.mail.backends.console.EmailBackend",
    "smtp": "django.core.mail.backends.smtp.EmailBackend",
    "acs": "alerts.email_backends.ACSEmailBackend",
    "graph": "alerts.email_backends.GraphEmailBackend",
}[EMAIL_BACKEND_CHOICE]
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="alerts@example.org")

# ACS (service principal via DefaultAzureCredential: AZURE_CLIENT_ID /
# AZURE_TENANT_ID / AZURE_CLIENT_SECRET are read from env by the SDK itself)
ACS_ENDPOINT = env("ACS_ENDPOINT", default="")
ACS_SENDER_ADDRESS = env("ACS_SENDER_ADDRESS", default="")

# Graph alternative (shared mailbox, application Mail.Send)
AZURE_TENANT_ID = env("AZURE_TENANT_ID", default="")
AZURE_CLIENT_ID = env("AZURE_CLIENT_ID", default="")
AZURE_CLIENT_SECRET = env("AZURE_CLIENT_SECRET", default="")
GRAPH_SENDER_ADDRESS = env("GRAPH_SENDER_ADDRESS", default="")

# Absolute links in emails
SITE_URL = env(
    "SITE_URL",
    default=(
        f"https://{RENDER_EXTERNAL_HOSTNAME}"
        if RENDER_EXTERNAL_HOSTNAME
        else "http://localhost:8000"
    ),
)

# --- Logging ----------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "accounts": {"level": "INFO"},
        "mozilla_django_oidc": {"level": "INFO"},
    },
}
