import sys
from pathlib import Path

from django.utils.translation import gettext_lazy as _
from speckenv import env
from speckenv_django import django_database_url, django_mailer_url


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = env("SECRET_KEY", required=True)
DEBUG = env("DEBUG", default=bool({"runserver", "shell"}.intersection(sys.argv)))
TESTING = env("TESTING", default="test" in sys.argv)
LIVE = env("LIVE", default=False)
ALLOWED_HOSTS = env("ALLOWED_HOSTS", default=[])
# Redirects to the canonical domain (and to HTTPS), see django-canonical-domain
SECURE_SSL_HOST = env("SECURE_SSL_HOST", default=None)
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT", default=False)
ADMINS = MANAGERS = env("ADMINS", default=[])
DEFAULT_FROM_EMAIL = SERVER_EMAIL = env(
    "DEFAULT_FROM_EMAIL", default="biwak@example.org"
)

# Links in mails
BASE_URL = env("BASE_URL", default="http://127.0.0.1:8000")

DEBUG_TOOLBAR = DEBUG and not TESTING

INSTALLED_APPS = [
    a
    for a in [
        "biwak",
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
        "django.contrib.postgres",
        "django.forms",
        "canonical_domain",
        "allauth",
        "allauth.account",
        "allauth.mfa",
        "allauth.socialaccount",
        "allauth.socialaccount.providers.google",
        "allauth.usersessions",
        "biwak.accounts",
        "biwak.projects",
        "biwak.items",
        "biwak.activity",
        "debug_toolbar" if DEBUG_TOOLBAR else "",
    ]
    if a
]

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["allauth.account.auth_backends.AuthenticationBackend"]
# Login by a code sent by mail is the default way in (specs/access.md)
LOGIN_URL = "account_request_login_code"
LOGIN_REDIRECT_URL = "/"

# django-allauth (specs/access.md): no passwords, no sign up, codes by mail,
# passkeys, Google for those who want it; only existing, active people
ACCOUNT_ADAPTER = "biwak.accounts.adapters.AccountAdapter"
SOCIALACCOUNT_ADAPTER = "biwak.accounts.adapters.SocialAccountAdapter"
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGIN_BY_CODE_ENABLED = True
ACCOUNT_LOGIN_BY_CODE_TIMEOUT = 600
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True
ACCOUNT_PREVENT_ENUMERATION = True
MFA_SUPPORTED_TYPES = ["webauthn"]
MFA_PASSKEY_LOGIN_ENABLED = True
MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN = DEBUG and not LIVE
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APPS": [
            {
                "client_id": env("GOOGLE_CLIENT_ID", default=""),
                "secret": env("GOOGLE_CLIENT_SECRET", default=""),
            }
        ]
        if env("GOOGLE_CLIENT_ID", default="")
        else [],
        "SCOPE": ["profile", "email"],
    }
}

MIDDLEWARE = [
    m
    for m in [
        "canonical_domain.middleware.canonical_domain",
        "django.middleware.security.SecurityMiddleware" if LIVE else "",
        "debug_toolbar.middleware.DebugToolbarMiddleware" if DEBUG_TOOLBAR else "",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.locale.LocaleMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.auth.middleware.LoginRequiredMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
        "allauth.account.middleware.AccountMiddleware",
        "allauth.usersessions.middleware.UserSessionsMiddleware",
        "biwak.accounts.middleware.language_middleware",
    ]
    if m
]

ROOT_URLCONF = "biwak.urls"
WSGI_APPLICATION = "wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "biwak" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.i18n",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]
FORM_RENDERER = "biwak.forms.Renderer"

LOCALE_PATHS = [BASE_DIR / "conf" / "locale"]

DATABASES = {"default": django_database_url(env("DATABASE_URL", required=True))}
DATABASES["default"] |= {
    "ATOMIC_REQUESTS": True,
    "CONN_HEALTH_CHECKS": True,
    "CONN_MAX_AGE": 300,
    "DISABLE_SERVER_SIDE_CURSORS": True,
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "de"
LANGUAGES = [("de", _("German")), ("en", _("English"))]
TIME_ZONE = "Europe/Zurich"
USE_I18N = True
USE_TZ = True

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
        if LIVE
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Sessions last weeks (specs/access.md); in the database, so that people
# can see them and log out everywhere
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 30 * 86400
SESSION_SAVE_EVERY_REQUEST = True
MESSAGE_STORAGE = "django.contrib.messages.storage.cookie.CookieStorage"

if LIVE:  # pragma: no cover
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000

EMAIL_URL = env("EMAIL_URL", default="console:" if DEBUG else "smtp:")
MAILERS = {"default": django_mailer_url(EMAIL_URL)}

if DEBUG_TOOLBAR:  # pragma: no cover
    INTERNAL_IPS = ["127.0.0.1"]

if SENTRY_DSN := env("SENTRY_DSN"):  # pragma: no cover
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(dsn=SENTRY_DSN, integrations=[DjangoIntegration()])

if TESTING:
    # Tests check the English texts
    LANGUAGE_CODE = "en"
