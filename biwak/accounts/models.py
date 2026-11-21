import datetime as dt
import hashlib
import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def verify_email(user):
    """The person's address as allauth's verified primary address: codes
    and invitations go there, so it's proven, and allauth only confirms
    who someone is (before adding a passkey) by codes to verified
    addresses; without one it answers 403 (no passwords here). A changed
    address replaces the old one: it doesn't log in anymore and can be
    given to somebody else"""
    from allauth.account.models import EmailAddress

    EmailAddress.objects.filter(user=user).exclude(email__iexact=user.email).delete()
    EmailAddress.objects.update_or_create(
        user=user,
        email__iexact=user.email,
        defaults={"email": user.email, "verified": True, "primary": True},
    )


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **kwargs):
        user = self.model(email=self.normalize_email(email), **kwargs)
        # No passwords (specs/access.md): codes by mail, passkeys, Google
        user.set_unusable_password()
        user.save()
        verify_email(user)
        return user

    def create_superuser(self, email, password=None, **kwargs):
        return self.create_user(email, password, is_admin=True, **kwargs)

    def active(self):
        return self.filter(is_active=True)


class NotificationLevel(models.TextChoices):
    """Which notifications somebody gets (specs/notifications.md)"""

    EVERYTHING = "everything", _("Everything")
    CONCERNS_ME = "concerns_me", _("Only what concerns me")
    NOTHING = "nothing", _("Nothing")


class MailDelivery(models.TextChoices):
    EACH = "each", _("A mail for each change")
    DIGEST = "digest", _("A daily digest")
    # In the lantern only (specs/lantern.md)
    NONE = "none", _("No mails")


class Theme(models.TextChoices):
    """The stored choice follows the person to other devices; AUTO is the
    system's (specs/keyboard.md)"""

    AUTO = "auto", _("As the system")
    LIGHT = "light", _("Light")
    DARK = "dark", _("Dark")


class Color(models.TextChoices):
    """The palette: the one list of names, stored as such (specs/keyboard.md,
    "The palette"); the tokens are ``--wb-palette-<name>-*`` in
    ``frontend/styles/main.css``. The accent colors and the project colors
    (specs/project-colors.md) are chosen from it. The clients' amber is
    reserved and not in the palette."""

    HEATHER = "heather", _("Heather")
    LAKE = "lake", _("Lake")
    FOREST = "forest", _("Forest")
    GLACIER = "glacier", _("Glacier")
    EMBER = "ember", _("Ember")
    ALPENGLOW = "alpenglow", _("Alpenglow")
    MOSS = "moss", _("Moss")
    SLATE = "slate", _("Slate")
    BARK = "bark", _("Bark")
    BERRY = "berry", _("Berry")


# The colors people may pick as their accent; the others are for projects only
ACCENT_NAMES = ["heather", "lake", "forest", "glacier", "ember", "alpenglow"]
Accent = models.TextChoices(
    "Accent", [(Color(name).name, (name, Color(name).label)) for name in ACCENT_NAMES]
)
Accent.__doc__ = "The accent colors people choose from, a part of ``Color``"
PALETTE = Color.values


def own_staff(prefix=""):
    """``Q()`` for the people who see all-access projects
    (``User.sees_all_access``); ``prefix`` for lookups through a relation,
    e.g. ``"user__"``"""
    return Q(**{f"{prefix}is_client": False}) & (
        Q(**{f"{prefix}organization__isnull": True})
        | Q(**{f"{prefix}organization__is_own": True})
    )


class User(AbstractBaseUser):
    """Staff or client (specs/access.md). Everybody can belong to an
    organization (specs/organizations.md); staff of an organization other
    than the installation's own are partners."""

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"

    email = models.EmailField(_("email"), max_length=254, unique=True)
    full_name = models.CharField(_("full name"), max_length=200, blank=True)
    short_name = models.CharField(_("short name"), max_length=30, blank=True)
    language = models.CharField(
        _("language"), max_length=10, choices=settings.LANGUAGES, blank=True
    )
    is_active = models.BooleanField(_("is active"), default=True)
    is_admin = models.BooleanField(_("is admin"), default=False)
    is_client = models.BooleanField(
        _("is client"),
        default=False,
        help_text=_(
            "Clients only see projects they're members of, and in them only"
            " what is visible to clients."
        ),
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="people",
        verbose_name=_("organization"),
        null=True,
        blank=True,
    )
    # Overridable per project and item (biwak.activity.models.LevelOverride)
    notification_level = models.CharField(
        _("notifications"),
        max_length=20,
        choices=NotificationLevel,
        default=NotificationLevel.EVERYTHING,
    )
    mail_delivery = models.CharField(
        _("mail delivery"),
        max_length=20,
        choices=MailDelivery,
        default=MailDelivery.EACH,
    )
    # A dot on the tab's icon while there are unread notifications
    # (specs/lantern.md),
    # on by default (decided 2026-11-21)
    lantern_in_favicon = models.BooleanField(
        _("unread notifications on the tab's icon"), default=True
    )

    # The offer to add a passkey after logging in by code (specs/access.md)
    # stops for good once the person dismissed it or added a passkey
    passkey_offer_done = models.BooleanField(_("passkey offer done"), default=False)

    class ProjectOrder(models.TextChoices):
        ACTIVITY = "activity", _("Activity")
        NAME = "name", _("A–Z")

    project_order = models.CharField(
        _("order of projects"),
        max_length=10,
        choices=ProjectOrder,
        default=ProjectOrder.ACTIVITY,
    )

    # Single-key shortcuts, on by default (decided 2026-11-21); Ctrl+K
    # always works
    keyboard_shortcuts = models.BooleanField(_("keyboard shortcuts"), default=True)
    theme = models.CharField(
        _("theme"), max_length=10, choices=Theme, default=Theme.AUTO
    )
    accent = models.CharField(
        _("accent color"), max_length=10, choices=Accent, default=Accent.HEATHER
    )

    objects = UserManager()

    class Meta:
        ordering = [Lower("full_name"), "email"]
        verbose_name = _("person")
        verbose_name_plural = _("people")

    def __str__(self):
        return self.full_name or self.email

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        fields = kwargs.get("update_fields")
        if fields is None or "email" in fields:
            # A changed address (the Django admin) stays allauth's verified one
            verify_email(self)

    def clean(self):
        super().clean()
        if self.is_admin and self.is_partner:
            # Admins are the installation's own staff (decided 2026-11-21)
            raise ValidationError(
                _(
                    "Admins belong to the installation's own organization, a"
                    " partner can't be an admin: move them into it first."
                )
            )

    def get_full_name(self):
        return str(self)

    def get_short_name(self):
        return (
            self.short_name or self.full_name.split(" ")[0] or self.email.split("@")[0]
        )

    @property
    def is_partner(self):
        """Staff of an organization other than the installation's own
        (freelancers, partner agencies): they see only the projects they're
        members of. Staff without an organization are the installation's
        own, so that nothing changes before organizations are set up."""
        return (
            not self.is_client
            and self.organization_id is not None
            and not self.organization.is_own
        )

    @property
    def sees_all_access(self):
        """Opens all-access projects without being a member: the
        installation's own staff (``own_staff()`` for querysets)"""
        return not self.is_client and not self.is_partner

    @property
    def organization_name(self):
        return self.organization.name if self.organization_id else ""

    @property
    def display_name(self):
        """With the organization for clients and partners: "Ada, Example
        Ltd"; the installation's own staff without it"""
        if self.organization_id and not self.sees_all_access:
            return f"{self}, {self.organization.name}"
        return str(self)

    @property
    def is_staff(self):
        """Django's admin, not the staff/client distinction"""
        return self.is_admin

    def has_perm(self, perm, obj=None):
        return self.is_active and self.is_admin

    def has_module_perms(self, app_label):
        return self.is_active and self.is_admin


# Created on the API tokens page or by `biwak login` (/cli-login/), which
# asks for a new one through the browser when the old one expired. Each use
# extends it: a token in use stays valid, one nobody uses expires.
API_TOKEN_LIFETIME = dt.timedelta(days=30)


def _api_token_expiry():
    return timezone.now() + API_TOKEN_LIFETIME


def _hash_api_token(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


class APITokenQuerySet(models.QuerySet):
    def for_secret(self, secret):
        """The valid token of an active person, or None"""
        return (
            self
            .filter(
                key_hash=_hash_api_token(secret),
                expires_at__gt=timezone.now(),
                user__is_active=True,
            )
            .select_related("user")
            .first()
        )

    def extend(self, token):
        """Each use extends the token"""
        now = timezone.now()
        self.filter(pk=token.pk).update(
            last_used_at=now, expires_at=now + API_TOKEN_LIFETIME
        )


class APIToken(models.Model):
    """Personal API tokens (specs/api-cli.md), only their hash is stored. A
    client's token sees what the client sees."""

    class Access(models.TextChoices):
        READ = "read", _("read only")
        WRITE = "write", _("read and write")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
        verbose_name=_("person"),
    )
    title = models.CharField(_("title"), max_length=100)
    # No default: people decide which access their tools get
    access = models.CharField(_("access"), max_length=10, choices=Access)
    key_hash = models.CharField(
        _("key hash"), max_length=64, unique=True, editable=False
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)
    last_used_at = models.DateTimeField(_("last used at"), blank=True, null=True)
    expires_at = models.DateTimeField(_("expires at"), default=_api_token_expiry)

    objects = APITokenQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("API token")
        verbose_name_plural = _("API tokens")

    def __str__(self):
        return self.title

    @classmethod
    def create_for(cls, *, user, title, access):
        """Creates a token and returns it with its secret, which can't be
        shown again. Expired tokens of the person are removed."""
        cls.objects.filter(user=user, expires_at__lte=timezone.now()).delete()
        secret = f"biwak_{secrets.token_urlsafe(32)}"
        token = cls.objects.create(
            user=user,
            title=title,
            access=cls.Access(access),
            key_hash=_hash_api_token(secret),
        )
        return token, secret


def prune_api_tokens():
    """Expired tokens go after another lifetime (fairy_tasks)"""
    return APIToken.objects.filter(
        expires_at__lte=timezone.now() - API_TOKEN_LIFETIME
    ).delete()


class CalendarToken(models.Model):
    """The secret in a person's iCal feed URL (specs/todos.md). Stored as is,
    the page shows the link again; "Make a new link" replaces it and the old
    one stops working. Not in the audit log, which would repeat the secret."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="calendar_token",
        verbose_name=_("person"),
    )
    token = models.CharField(_("token"), max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    class Meta:
        verbose_name = _("calendar link")
        verbose_name_plural = _("calendar links")

    def __str__(self):
        return f"{self.user}"

    @classmethod
    def renew(cls, user):
        """A new link for the person; the old one stops working"""
        cls.objects.filter(user=user).delete()
        return cls.objects.create(user=user, token=secrets.token_urlsafe(32))
