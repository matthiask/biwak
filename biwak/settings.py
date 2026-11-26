import atexit
import shutil
import sys
import tempfile
from email.utils import parseaddr
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _
from speckenv import env
from speckenv_django import django_cache_url, django_database_url, django_mailer_url

from biwak.redis_url import channel_layer, channels_redis_url
from biwak.storage_url import storage_from_url


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
        # runserver serves the websockets of docs edited live too
        # (specs/collaboration.md); a development dependency
        "daphne" if DEBUG and not TESTING else "",
        "biwak",
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
        "django.contrib.humanize",
        "django.contrib.postgres",
        "django.forms",
        "canonical_domain",
        "allauth",
        "allauth.account",
        "allauth.mfa",
        "allauth.socialaccount",
        "allauth.socialaccount.providers.google",
        "allauth.socialaccount.providers.microsoft",
        "allauth.usersessions",
        "biwak.accounts",
        "biwak.organizations",
        "biwak.teams",
        "biwak.projects",
        "biwak.items",
        "biwak.activity",
        "biwak.files",
        "biwak.bookmarks",
        "biwak.public_links",
        "biwak.reactions",
        "biwak.checkins",
        "biwak.search",
        "biwak.palette",
        "biwak.inbound",
        "biwak.forwarding",
        "biwak.outbox",
        "biwak.importer",
        "biwak.audit",
        "channels",
        "biwak.collab",
        "biwak.live",
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
ACCOUNT_FORMS = {
    "login": "biwak.accounts.forms.SSOLoginForm",
    "request_login_code": "biwak.accounts.forms.SSORequestLoginCodeForm",
}
SOCIALACCOUNT_ADAPTER = "biwak.accounts.adapters.SocialAccountAdapter"
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGIN_BY_CODE_ENABLED = True
ACCOUNT_LOGIN_BY_CODE_TIMEOUT = 600
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True
ACCOUNT_PREVENT_ENUMERATION = True
# Passkeys are a way in, authenticator apps an optional second factor, no
# recovery codes: a reset instead (specs/two-factor.md)
MFA_ADAPTER = "biwak.accounts.adapters.MFAAdapter"
MFA_SUPPORTED_TYPES = ["webauthn", "totp"]
MFA_TOTP_ISSUER = "Biwak"
MFA_PASSKEY_LOGIN_ENABLED = True
# Confirming who one is with a passkey needs the PIN or fingerprint, as
# signing in does (decided 2026-11-22)
MFA_WEBAUTHN_USER_VERIFICATION = "required"
# Off: tracking writes the session's row on every request (decided
# 2026-11-21); the sessions list shows when each one signed in
USERSESSIONS_TRACK_ACTIVITY = False
# How many proxies in front of the app append to X-Forwarded-For (1 behind
# the HAProxy ingress). allauth takes the client's IP from there for its
# rate limits and the sessions' admin; 0 uses REMOTE_ADDR, the proxy's.
ALLAUTH_TRUSTED_PROXY_COUNT = env("ALLAUTH_TRUSTED_PROXY_COUNT", default=0)
MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN = DEBUG and not LIVE
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
# Single sign-on per organization (specs/sso.md): who may use which is
# decided by biwak.accounts.sso, these are the installation's app
# registrations (docs/sign-in.md)
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
        # The ID token says which Workspace manages the account (hd)
        "SCOPE": ["openid", "profile", "email"],
    },
    "microsoft": {
        "APPS": [
            {
                "client_id": env("MICROSOFT_CLIENT_ID", default=""),
                "secret": env("MICROSOFT_CLIENT_SECRET", default=""),
                # Work and school accounts of any tenant, no personal ones;
                # the organization's tenant is checked on signing in
                "settings": {"tenant": "organizations"},
            }
        ]
        if env("MICROSOFT_CLIENT_ID", default="")
        else [],
        "SCOPE": ["openid", "email", "profile", "User.Read"],
        "provider_class": "biwak.accounts.microsoft.provider.EntraProvider",
    },
}

MIDDLEWARE = [
    m
    for m in [
        "canonical_domain.middleware.canonical_domain",
        "django.middleware.security.SecurityMiddleware" if LIVE else "",
        "debug_toolbar.middleware.DebugToolbarMiddleware" if DEBUG_TOOLBAR else "",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "biwak.accounts.middleware.language_middleware",
        "django.middleware.locale.LocaleMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        # Multipart PUT (PUT /api/v1/me/image/) fills request.FILES
        "ninja.compatibility.files.fix_request_files_middleware",
        "biwak.organizations.models.own_middleware",
        "biwak.modals.modal_middleware",
        "biwak.accounts.middleware.LoginRequired",
        "biwak.cli_version.cli_version_middleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
        "allauth.account.middleware.AccountMiddleware",
        "allauth.usersessions.middleware.UserSessionsMiddleware",
        # Sessions of organizations requiring single sign-on (specs/sso.md)
        "biwak.accounts.sso.session_middleware",
        # Organizations requiring a second factor: setting one up comes
        # first (specs/two-factor.md)
        "biwak.accounts.two_factor.setup_middleware",
        "biwak.accounts.middleware.user_middleware",
        "biwak.accounts.passkeys.passkey_offer_middleware",
    ]
    if m
]

ROOT_URLCONF = "biwak.urls"
WSGI_APPLICATION = "wsgi.application"
# Docs edited live (specs/collaboration.md): the websockets are served by
# asgi.py; the processes talk through Redis, required when deployed (the
# WSGI processes tell the editors about edits through the API too)
ASGI_APPLICATION = "asgi.application"
# The channel layer of live editing (specs/collaboration.md): the shared
# Redis of CACHE_URL, or REDIS_URL as an override; one of them required
# outside development and tests, since with several workers an in-memory
# layer would quietly keep editors on different workers apart
REDIS_URL = channels_redis_url(
    redis_url=env("REDIS_URL", default=""), cache_url=env("CACHE_URL", default="")
)
if not (REDIS_URL or DEBUG or TESTING):
    raise ImproperlyConfigured(
        "Set CACHE_URL (the shared Redis) or REDIS_URL for the channel layer."
    )
# Django's cache, e.g. the presigned URLs of files handed out
# (biwak/files/file_urls.py): the shared Redis of CACHE_URL, in memory
# without it (development, tests)
CACHES = {
    "default": django_cache_url(
        "locmem://" if TESTING else env("CACHE_URL", default="locmem://")
    )
}
CHANNEL_LAYERS = {
    "default": channel_layer(REDIS_URL)
    if REDIS_URL and not TESTING
    else {"BACKEND": "channels.layers.InMemoryChannelLayer"}
}

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
                "biwak.modals.context",
            ],
        },
    }
]
FORM_RENDERER = "biwak.forms.Renderer"
TEST_RUNNER = "biwak.test_runner.TestRunner"

LOCALE_PATHS = [BASE_DIR / "conf" / "locale"]

DATABASES = {"default": django_database_url(env("DATABASE_URL", required=True))}
DATABASES["default"] |= {
    "ATOMIC_REQUESTS": True,
    # Under ASGI (specs/collaboration.md) requests and websockets run in
    # short-lived threads; persistent connections would stay open in
    # ended threads until garbage-collected. pgbouncer pools instead.
    # The health checks only act on reused connections: kept for when
    # CONN_MAX_AGE goes up again.
    "CONN_HEALTH_CHECKS": True,
    "CONN_MAX_AGE": 0,
    "DISABLE_SERVER_SIDE_CURSORS": True,
}

# English until the German translation at the end (SPEC.md); otherwise
# allauth and Django speak German beside our English texts
LANGUAGE_CODE = "en"
LANGUAGES = [("de", _("German")), ("en", _("English"))]
TIME_ZONE = "Europe/Zurich"
# Dates per language: biwak/formats/<language>/formats.py
FORMAT_MODULE_PATH = ["biwak.formats"]
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
# Files (specs/files.md): STORAGE_URL, on local disk by default, served
# at MEDIA_URL with DEBUG only (biwak/urls.py); an s3:// URL for an
# S3-compatible bucket, private, pages and downloads through presigned
# URLs (biwak/files/file_urls.py)
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"
if TESTING:
    MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="biwak-test-media-"))
    atexit.register(shutil.rmtree, MEDIA_ROOT, ignore_errors=True)
else:
    STORAGES["default"] = storage_from_url(
        env("STORAGE_URL", default="file:./media/"), base_dir=BASE_DIR
    )

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

# Replying by mail (specs/notifications.md, stage 2) through Resend: the
# receiving subdomain (its MX at Resend), an API key which can read
# received mails, the webhook's signing secret (whsec_...). Without all
# three replying is off and mails carry no Reply-To.
REPLY_DOMAIN = env("REPLY_DOMAIN", default="")
RESEND_API_KEY = env("RESEND_API_KEY", default="")
RESEND_WEBHOOK_SECRET = env("RESEND_WEBHOOK_SECRET", default="")

# Push notifications (specs/web-push.md): the VAPID key pair signing our
# requests to the browsers' push services, made once with ``uvx --from
# py-vapid vapid --gen`` (the public key as the application server key,
# base64url; the private key as base64url or PEM). Without both, nothing is
# offered or sent.
WEBPUSH_VAPID_PUBLIC_KEY = env("WEBPUSH_VAPID_PUBLIC_KEY", default="")
WEBPUSH_VAPID_PRIVATE_KEY = env("WEBPUSH_VAPID_PRIVATE_KEY", default="")
WEBPUSH_SUBJECT = env(
    "WEBPUSH_SUBJECT", default=f"mailto:{parseaddr(DEFAULT_FROM_EMAIL)[1]}"
)

# Stale to-dos warned, then marked obsolete by fairy_tasks
# (specs/stale-todos.md); off until `./manage.py stale_todos` looked right
STALE_TODOS = env("STALE_TODOS", default=False)

# Sending (specs/mail-sending.md): the app's mails go through the outbox
# (biwak.outbox), which sends them with the default mailer; mail_admins
# uses it directly. ``EMAIL_URL=resend:`` sends through Resend's API with
# RESEND_API_KEY (anymail); otherwise any Django mailer URL: ``console:``
# in development, tests use Django's locmem.
EMAIL_URL = env("EMAIL_URL", default="console:" if DEBUG else "smtp:")
# Any spelling of the scheme ("resend:", "resend://") means Resend
if EMAIL_URL.strip().lower().split(":", 1)[0] == "resend":  # pragma: no cover
    if not RESEND_API_KEY:
        raise ImproperlyConfigured("EMAIL_URL=resend: needs RESEND_API_KEY.")
    MAILERS = {
        "default": {
            "BACKEND": "biwak.outbox.resend.EmailBackend",
            # One short attempt: what fails is retried by send_mails
            "OPTIONS": {"api_key": RESEND_API_KEY, "timeout": 10},
        }
    }
else:
    MAILERS = {"default": django_mailer_url(EMAIL_URL)}

if DEBUG_TOOLBAR:  # pragma: no cover
    INTERNAL_IPS = ["127.0.0.1"]

# Biwak's own log lines (specs/auditing.md, decided 2026-11-24): info and
# up to the console, the pod's output; errors also reach Sentry through its
# logging integration. Django's own loggers keep their defaults.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "loggers": {
        # Tests print warnings only, as before
        "biwak": {"handlers": ["console"], "level": "WARNING" if TESTING else "INFO"},
    },
}

if SENTRY_DSN := env("SENTRY_DSN"):  # pragma: no cover
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(dsn=SENTRY_DSN, integrations=[DjangoIntegration()])
