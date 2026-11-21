"""Organizations people belong to (specs/organizations.md): the clients'
companies, the own organization (``is_own``) and partners'. Staff of an
organization other than the own one are partners and see only
the projects they're members of (specs/access.md)."""

import re
from contextlib import contextmanager
from contextvars import ContextVar

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


# Never used for matching addresses to organizations: anybody has one
FREE_MAIL_DOMAINS = frozenset({
    "aol.com",
    "bluewin.ch",
    "gmail.com",
    "gmx.at",
    "gmx.ch",
    "gmx.de",
    "gmx.net",
    "googlemail.com",
    "hotmail.com",
    "icloud.com",
    "live.com",
    "mac.com",
    "me.com",
    "msn.com",
    "outlook.com",
    "proton.me",
    "protonmail.com",
    "sunrise.ch",
    "t-online.de",
    "web.de",
    "yahoo.com",
})

DOMAIN = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)


def normalize_name(name):
    """Without spaces at the ends and with single spaces inside; names
    differing only in case after this are the same organization"""
    return " ".join(str(name or "").split())


def normalize_domain(domain):
    """``example.org`` from ``Example.org``, ``@example.org`` or an address"""
    return str(domain or "").strip().rpartition("@")[2].strip().rstrip(".").lower()


def domain_of(email):
    """The address's domain, empty for free-mail domains (never matched)"""
    domain = normalize_domain(email) if "@" in str(email or "") else ""
    return "" if domain in FREE_MAIL_DOMAINS else domain


# The own organization when none is marked yet; admins
# rename it
OWN_NAME = "Our organization"

# The own organization's ID, remembered for a request (``remembering_own()``,
# the middleware): whether somebody is a partner then costs a query per
# request, not one per person shown
_own_pk = ContextVar("own_organization_pk", default=None)


def own_values():
    """``(ID, name)`` of the own organization, ``(None,
    "")`` if none is marked yet"""
    memo = _own_pk.get()
    if memo is not None and "own" in memo:
        return memo["own"]
    own = Organization.objects.filter(is_own=True).values_list("pk", "name").first()
    own = own or (None, "")
    if memo is not None:
        memo["own"] = own
    return own


def own_pk():
    return own_values()[0]


def forget_own():
    """After marking another one"""
    memo = _own_pk.get()
    if memo is not None:
        memo.clear()


@contextmanager
def remembering_own():
    token = _own_pk.set({})
    try:
        yield
    finally:
        _own_pk.reset(token)


def own_middleware(get_response):
    def middleware(request):
        with remembering_own():
            return get_response(request)

    return middleware


class SignIn(models.TextChoices):
    """How an organization's people sign in (specs/sso.md)"""

    CODES = "codes", _("Codes and passkeys")
    SSO_ALLOWED = "sso_allowed", _("Single sign-on allowed")
    SSO_REQUIRED = "sso_required", _("Single sign-on required")


class IdP(models.TextChoices):
    """The identity provider of an organization with single sign-on: the
    providers' IDs in allauth"""

    GOOGLE = "google", _("Google Workspace")
    MICROSOFT = "microsoft", _("Microsoft Entra ID")


# The tenant of personal Microsoft accounts: anybody can have one, it never
# stands for an organization (the iss and tid claims in
# https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference)
MICROSOFT_CONSUMER_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"


class OrganizationQuerySet(models.QuerySet):
    def own(self):
        """The own organization, which always exists
        (decided 2026-11-21): created as "Our organization" if none is
        marked, signing in with Google allowed as for staff before
        (specs/sso.md)"""
        own = self.filter(is_own=True).first()
        if own is None:
            own = self.named(OWN_NAME) or Organization(
                name=OWN_NAME, signin=SignIn.SSO_ALLOWED, idp=IdP.GOOGLE
            )
            own.is_own = True
            own.save()
        return own

    def named(self, name):
        """The organization of this name, ignoring case and spaces, or None"""
        name = normalize_name(name)
        return self.filter(name__iexact=name).first() if name else None

    def for_email(self, email):
        """The organization whose domains include the address's, or None;
        free-mail domains never match"""
        domain = domain_of(email)
        return self.filter(domains__contains=[domain]).first() if domain else None


class Organization(models.Model):
    name = models.CharField(_("name"), max_length=200)
    domains = ArrayField(
        models.CharField(max_length=253),
        verbose_name=_("email domains"),
        blank=True,
        default=list,
        help_text=_("Inviting an address of these domains suggests the organization."),
    )
    is_own = models.BooleanField(
        _("your own organization"),
        default=False,
        help_text=_(
            "Its staff see all-access projects; staff of other organizations"
            " (partners) only the projects they're members of."
        ),
    )
    # Single sign-on (specs/sso.md): admins only
    signin = models.CharField(
        _("sign-in"), max_length=20, choices=SignIn, default=SignIn.CODES
    )
    idp = models.CharField(
        _("identity provider"), max_length=20, choices=IdP, blank=True
    )
    # Microsoft Entra ID: the tenant's ID, compared with the tokens' ``tid``;
    # Google Workspace uses the domains (``hd``)
    tenant_id = models.CharField(_("Microsoft tenant ID"), max_length=36, blank=True)
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    objects = OrganizationQuerySet.as_manager()

    class Meta:
        ordering = [Lower("name")]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="unique_organization_name"),
            models.UniqueConstraint(
                fields=["is_own"],
                condition=Q(is_own=True),
                name="one_own_organization",
            ),
            models.CheckConstraint(
                condition=Q(signin=SignIn.CODES) | ~Q(idp=""),
                name="sso_has_an_idp",
            ),
            models.CheckConstraint(
                condition=~Q(idp=IdP.MICROSOFT) | ~Q(tenant_id=""),
                name="microsoft_has_a_tenant",
            ),
        ]
        verbose_name = _("organization")
        verbose_name_plural = _("organizations")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        forget_own()

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("organization", kwargs={"pk": self.pk})

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        forget_own()
        return result

    @property
    def sso(self):
        """The identity provider people may sign in with, or empty"""
        return "" if self.signin == SignIn.CODES else self.idp

    @property
    def requires_sso(self):
        return self.signin == SignIn.SSO_REQUIRED

    @property
    def idp_name(self):
        """ "Google", "Microsoft": the button's name"""
        return {IdP.GOOGLE: "Google", IdP.MICROSOFT: "Microsoft"}.get(self.idp, "")
