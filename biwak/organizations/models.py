"""Organizations people belong to (specs/organizations.md): the clients'
companies, the installation's own (``is_own``) and partners'. Staff of an
organization other than the installation's own are partners and see only
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


# The installation's own organization when none is marked yet; admins
# rename it
OWN_NAME = "Our organization"

# The own organization's ID, remembered for a request (``remembering_own()``,
# the middleware): whether somebody is a partner then costs a query per
# request, not one per person shown
_own_pk = ContextVar("own_organization_pk", default=None)


def own_values():
    """``(ID, name)`` of the installation's own organization, ``(None,
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


class OrganizationQuerySet(models.QuerySet):
    def own(self):
        """The installation's own organization, which always exists
        (decided 2026-11-21): created as "Our organization" if none is
        marked"""
        own = self.filter(is_own=True).first()
        if own is None:
            own = self.named(OWN_NAME) or Organization(name=OWN_NAME)
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
        _("the installation's own"),
        default=False,
        help_text=_(
            "Its staff see all-access projects; staff of other organizations"
            " (partners) only the projects they're members of."
        ),
    )
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
