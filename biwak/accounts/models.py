import datetime as dt
import hashlib
import json
import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.contrib.postgres.fields import ArrayField
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
        """Admins are own staff (decided 2026-11-21)"""
        from biwak.organizations.models import Organization

        kwargs.setdefault("organization", Organization.objects.own())
        return self.create_user(email, password, is_admin=True, **kwargs)

    def active(self):
        return self.filter(is_active=True)

    def invited(self):
        """Invitations (specs/activation.md, "Inviting"): active people who were
        invited and have never signed in, the oldest invitation first"""
        return self.filter(
            is_active=True, invited_at__isnull=False, last_login__isnull=True
        ).order_by("invited_at", "pk")


class NotificationLevel(models.TextChoices):
    """Which notifications somebody gets (specs/notifications.md)"""

    EVERYTHING = "everything", _("Everything")
    CONCERNS_ME = "concerns_me", _("Only what concerns me")


class MailDelivery(models.TextChoices):
    EACH = "each", _("A mail for each change")
    DIGEST = "digest", _("A daily digest")
    # In the lantern only (specs/lantern.md)
    NONE = "none", _("No mails")


def default_working_days():
    """Monday to Friday (``date.weekday()``), the preset (specs/quiet-hours.md)"""
    return [0, 1, 2, 3, 4]


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
    return Q(**{f"{prefix}is_client": False, f"{prefix}organization__is_own": True})


class User(AbstractBaseUser):
    """Staff or client (specs/access.md). Everybody can belong to an
    organization (specs/organizations.md); staff of an organization other
    than the own one are externals."""

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"

    email = models.EmailField(_("email"), max_length=254, unique=True)
    full_name = models.CharField(_("full name"), max_length=200, blank=True)
    short_name = models.CharField(_("short name"), max_length=30, blank=True)
    # Chosen in the settings; empty is "Automatic": pages follow the
    # browser, mails ``invitation_language`` (specs/languages.md)
    language = models.CharField(
        _("language"), max_length=10, choices=settings.LANGUAGES, blank=True
    )
    # The language of the last invitation mail, the inviter's at the time:
    # mails use it until the person chooses one (``language_for()``)
    invitation_language = models.CharField(
        _("invitation's language"),
        max_length=10,
        choices=settings.LANGUAGES,
        blank=True,
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
    # Who invited the person and when (specs/activation.md, "Inviting"): set by
    # ``invite_people()`` when it creates them. An invitation is somebody
    # invited who has never signed in (``User.objects.invited()``).
    invited_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("invited by"),
    )
    invited_at = models.DateTimeField(_("invited at"), null=True, blank=True)
    # The day the person left (specs/activation.md, "People who left"): set
    # by deactivating and by the importer for people Basecamp no longer has,
    # cleared by activating. Inactive people without it wait to be activated.
    left_at = models.DateField(_("left on"), null=True, blank=True)
    # Set together with ``left_at`` by the importer (gone from Basecamp's
    # account): only such a date is cleared when they are back in Basecamp;
    # a date set by deactivating stays
    left_in_basecamp = models.BooleanField(_("left in Basecamp"), default=False)
    # Overridable per project and item (biwak.activity.models.LevelOverride)
    notification_level = models.CharField(
        _("notifications"),
        max_length=20,
        choices=NotificationLevel,
        # Not everything (decided 2026-11-22): a post to everybody would
        # subscribe everybody to its comments
        default=NotificationLevel.CONCERNS_ME,
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

    # Quiet hours (specs/quiet-hours.md): off by default; on, notification
    # mails and digests wait outside the working days and hours, in the
    # installation's time zone (decided 2026-11-22: no time zone per person)
    quiet_hours = models.BooleanField(_("quiet hours"), default=False)
    working_days = ArrayField(
        models.PositiveSmallIntegerField(),
        verbose_name=_("working days"),
        default=default_working_days,
        blank=True,
    )
    working_from = models.TimeField(_("working from"), default=dt.time(8))
    working_until = models.TimeField(_("working until"), default=dt.time(18))
    # Out of office: away up to and including this day, in the installation's
    # time zone; ends by itself the day after (``is_away``)
    away_until = models.DateField(_("away until"), null=True, blank=True)
    away_note = models.CharField(_("away note"), max_length=200, blank=True)

    # The offer to add a passkey after logging in by code (specs/access.md)
    # stops for good once the person dismissed it or added a passkey
    passkey_offer_done = models.BooleanField(_("passkey offer done"), default=False)

    # Resend reported a hard bounce or a complaint for the address
    # (specs/mail-sending.md): no notification mails, digests and check-in
    # mails go to it; cleared when the address changes, or by an admin
    mail_undeliverable_at = models.DateTimeField(
        _("mail undeliverable since"),
        null=True,
        blank=True,
        help_text=_(
            "Mail to the address bounced or was marked as spam. Clear it once"
            " the address works again."
        ),
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

    # The profile image (specs/people.md): 256 pixel WebP in the default
    # storage as people/<id>/<version>.webp, served by ``person_image``
    image = models.CharField(_("profile image"), max_length=200, blank=True)
    # The drawn mark shown without an image (specs/people.md): a name of
    # ``biwak.accounts.marks.MARKS``, given when the account is created
    mark = models.CharField(_("mark"), max_length=30, blank=True)

    objects = UserManager()

    class Meta:
        ordering = [Lower("full_name"), "email"]
        verbose_name = _("person")
        verbose_name_plural = _("people")

    def __str__(self):
        return self.full_name or self.email

    def save(self, *args, **kwargs):
        if self._state.adding and not self.mark:
            # Everybody has one, whoever creates the account (sign-up,
            # invitation, the importer, the admin)
            from biwak.accounts.marks import mark_for

            self.mark = mark_for(self.organization_id)
        fields = kwargs.get("update_fields")
        stored = None
        if self.pk and (
            fields is None
            or {"email", "mail_undeliverable_at", "organization"} & set(fields)
        ):
            stored = (
                type(self)
                .objects.filter(pk=self.pk)
                .values("email", "mail_undeliverable_at", "organization_id")
                .first()
            )
        if (
            stored
            and self.mail_undeliverable_at
            and stored["email"].lower() != self.email.lower()
            and (fields is None or "email" in fields)
        ):
            # A new address may work (specs/mail-sending.md)
            self.mail_undeliverable_at = None
            if fields is not None:
                fields = kwargs["update_fields"] = [*fields, "mail_undeliverable_at"]
        cleared = (
            stored
            and stored["mail_undeliverable_at"]
            and not self.mail_undeliverable_at
            and (fields is None or "mail_undeliverable_at" in fields)
        )
        super().save(*args, **kwargs)
        if cleared:
            self._drop_waiting_mails()
        if (
            stored
            and stored["organization_id"] != self.organization_id
            and (fields is None or "organization" in fields)
        ):
            # Moved into an organization requiring single sign-on
            # (specs/sso.md): what it doesn't allow ends
            from biwak.accounts import sso

            sso.enforce_required_now_and_after_commit([self.pk])
        if fields is None or "email" in fields:
            # A changed address (the Django admin) stays allauth's verified one
            verify_email(self)

    def _drop_waiting_mails(self):
        """What piled up while the address was undeliverable is never
        mailed: it's in the lantern (decided 2026-11-21). Marked as sent,
        so a later change to the same event is a new notification."""
        from biwak.activity.models import Notification

        Notification.objects.filter(user=self, sent_at__isnull=True).update(
            sent_at=timezone.now()
        )

    def clean(self):
        super().clean()
        if self.is_admin and self.is_external:
            # Admins are own staff (decided 2026-11-21)
            raise ValidationError(
                _(
                    "Admins belong to your own organization, an"
                    " external can't be an admin: move them into it first."
                )
            )
        if self.is_admin and self.is_client:
            # Found 2026-11-28, verification round 2: the Django admin
            # took both
            raise ValidationError(
                _(
                    "Admins are staff of your own organization: a client can't be an admin."
                )
            )

    def get_full_name(self):
        return str(self)

    def get_short_name(self):
        return (
            self.short_name or self.full_name.split(" ")[0] or self.email.split("@")[0]
        )

    @property
    def is_away(self):
        """Away today (specs/quiet-hours.md)"""
        from biwak.accounts.quiet import is_away

        return is_away(self)

    @property
    def away_text(self):
        """ "Away until 3 Dec: back on the 4th" while away, else "" """
        from biwak.accounts.quiet import away_text

        return away_text(self)

    @property
    def is_external(self):
        """Staff who aren't in the own organization: of
        another one (external agencies) or of none (individuals, e.g.
        freelancers, decided 2026-11-21). They see only the projects
        they're members of."""
        if self.is_client:
            return False
        if self.organization_id is None:
            return True
        # The own organization's ID, not the person's organization: no query
        # per person (``own_pk()`` is remembered for the request)
        from biwak.organizations.models import own_pk

        return self.organization_id != own_pk()

    @property
    def sees_all_access(self):
        """Opens all-access projects without being a member: the
        own staff (``own_staff()`` for querysets)"""
        return not self.is_client and not self.is_external

    @property
    def image_version(self):
        """The part of the image's storage name that changes with it, for
        the URL (cached for good)"""
        return self.image.rsplit("/", 1)[-1].removesuffix(".webp")

    @property
    def image_url(self):
        """The image's URL, whoever may see it (``person_image`` answers 404
        to those who may not know the person), or None"""
        if not self.image:
            return None
        from django.urls import reverse

        return reverse("person_image", args=[self.pk, self.image_version])

    @property
    def avatar_color(self):
        """One of the palette's names, from the ID: the same every time"""
        return PALETTE[self.pk % len(PALETTE)]

    @property
    def avatar_data(self):
        """What the scripts need to draw the mark (``frontend/avatar.js``);
        ``away`` only for people away (specs/quiet-hours.md)"""
        data = {
            "name": str(self),
            "mark": self.mark,
            "color": self.avatar_color,
            "image_url": self.image_url,
            "inactive": not self.is_active,
        }
        if away := self.away_text:
            data["away"] = away
        return data

    @property
    def avatar_json(self):
        """``avatar_data`` for a ``data-avatar`` attribute"""
        return json.dumps(self.avatar_data)

    @property
    def organization_name(self):
        if not self.organization_id:
            return ""
        from biwak.organizations.models import own_values

        # The own organization's without a query per person
        pk, name = own_values()
        return name if self.organization_id == pk else self.organization.name

    @property
    def display_name(self):
        """With the organization for clients and externals: "Ada, Example
        Ltd"; own staff without it"""
        if self.organization_id and not self.sees_all_access:
            return f"{self}, {self.organization.name}"
        return str(self)

    @property
    def is_invited(self):
        """Invited and never signed in (``UserManager.invited()``)"""
        return self.is_active and self.invited_at is not None and not self.last_login

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
        """The valid token of an active person, or None. Tokens of people
        whose organization requires single sign-on are valid for 24 hours
        after their creation, checked here whatever ``expires_at`` says
        (specs/sso.md)"""
        from biwak.accounts import sso

        token = (
            self
            .filter(
                key_hash=_hash_api_token(secret),
                expires_at__gt=timezone.now(),
                user__is_active=True,
            )
            .select_related("user", "user__organization")
            .first()
        )
        return token if token is not None and sso.token_counts(token) else None

    def extend(self, token):
        """Each use extends the token, but never past 24 hours after its
        creation for people whose organization requires single sign-on"""
        from biwak.accounts import sso

        now = timezone.now()
        expires_at = now + API_TOKEN_LIFETIME
        if limit := sso.token_expiry(token.user, created_at=token.created_at):
            expires_at = min(expires_at, limit)
        self.filter(pk=token.pk).update(last_used_at=now, expires_at=expires_at)


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
        from biwak.accounts import sso

        secret = f"biwak_{secrets.token_urlsafe(32)}"
        now = timezone.now()
        token = cls.objects.create(
            user=user,
            title=title,
            access=cls.Access(access),
            key_hash=_hash_api_token(secret),
            created_at=now,
            expires_at=sso.token_expiry(user, created_at=now)
            or now + API_TOKEN_LIFETIME,
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


class PushSubscription(models.Model):
    """One device getting push notifications (specs/web-push.md): what the
    browser's ``PushSubscription.toJSON()`` gave, the browser's push
    service delivering to ``endpoint``. A 404 or 410 from it deletes the
    subscription."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
        verbose_name=_("person"),
    )
    endpoint = models.URLField(_("endpoint"), max_length=1000, unique=True)
    p256dh = models.CharField(_("public key"), max_length=200)
    auth = models.CharField(_("authentication secret"), max_length=100)
    user_agent = models.CharField(_("user agent"), max_length=500, blank=True)
    # What the person calls it; empty: the browser and system (``label``)
    name = models.CharField(_("name"), max_length=100, blank=True)
    created_at = models.DateTimeField(_("created at"), default=timezone.now)
    last_success_at = models.DateTimeField(_("last success at"), null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = _("push subscription")
        verbose_name_plural = _("push subscriptions")

    def __str__(self):
        return f"{self.user}: {self.user_agent or self.endpoint}"

    @property
    def label(self):
        """The name, or the browser and system ("Firefox on Linux")"""
        from biwak.accounts.signin import describe_agent

        return self.name or describe_agent(self.user_agent)

    def info(self):
        """What ``pywebpush.webpush()`` takes"""
        return {
            "endpoint": self.endpoint,
            "keys": {"p256dh": self.p256dh, "auth": self.auth},
        }
