from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **kwargs):
        user = self.model(email=self.normalize_email(email), **kwargs)
        # No passwords (specs/access.md): codes by mail, passkeys, Google
        user.set_unusable_password()
        user.save()
        return user

    def create_superuser(self, email, password=None, **kwargs):
        return self.create_user(email, password, is_admin=True, **kwargs)

    def active(self):
        return self.filter(is_active=True)


class User(AbstractBaseUser):
    """Staff or client (specs/access.md). Clients belong to an organization,
    shown beside their name"""

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
    organization = models.CharField(_("organization"), max_length=200, blank=True)

    objects = UserManager()

    class Meta:
        ordering = [Lower("full_name"), "email"]
        verbose_name = _("person")
        verbose_name_plural = _("people")

    def __str__(self):
        return self.full_name or self.email

    def get_full_name(self):
        return str(self)

    def get_short_name(self):
        return (
            self.short_name or self.full_name.split(" ")[0] or self.email.split("@")[0]
        )

    @property
    def display_name(self):
        """With the organization for clients: "Ada, Example Ltd" """
        if self.is_client and self.organization:
            return f"{self}, {self.organization}"
        return str(self)

    @property
    def is_staff(self):
        """Django's admin, not the staff/client distinction"""
        return self.is_admin

    def has_perm(self, perm, obj=None):
        return self.is_active and self.is_admin

    def has_module_perms(self, app_label):
        return self.is_active and self.is_admin
