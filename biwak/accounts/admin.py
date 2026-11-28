from allauth.account.admin import EmailAddressAdmin
from allauth.account.models import EmailAddress
from allauth.mfa.admin import AuthenticatorAdmin
from allauth.mfa.models import Authenticator
from allauth.socialaccount.admin import (
    SocialAccountAdmin,
    SocialAppAdmin,
    SocialTokenAdmin,
)
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from allauth.usersessions.admin import UserSessionAdmin as BaseUserSessionAdmin
from allauth.usersessions.models import UserSession
from django import forms
from django.contrib.auth.admin import GroupAdmin
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from biwak import admin
from biwak.accounts.models import User
from biwak.organizations.operations import is_external_organization


class UndeliverableFilter(admin.SimpleListFilter):
    title = _("mail undeliverable")
    parameter_name = "undeliverable"

    def lookups(self, request, model_admin):
        return [("1", _("yes"))]

    def queryset(self, request, queryset):
        if self.value() == "1":
            return queryset.filter(mail_undeliverable_at__isnull=False)
        return queryset


class UserAdminForm(forms.ModelForm):
    """The rules of deactivating (specs/activation.md): not oneself, and an
    active admin stays (``is_active`` and ``is_admin``); a client becomes
    staff only in the own or an external organization (or none: an
    individual), not in a client organization, which would become external
    by the way (decided 2026-11-28, specs/organizations.md)"""

    class Meta:
        model = User
        # The admin's fieldsets decide
        fields = ["is_active", "is_admin"]

    def clean(self):
        data = super().clean()
        user = self.instance
        if user.pk is None:
            return data
        org = data.get("organization")
        if (
            user.is_client
            and "is_client" in data
            and not data["is_client"]
            and org is not None
            and not org.is_own
            and not is_external_organization(org)
        ):
            self.add_error(
                "is_client",
                _(
                    "Staff in %(organization)s would make this client"
                    " organization an external one: choose your own"
                    " organization or an external one too."
                )
                % {"organization": org},
            )
        unticked = user.is_active and not data.get("is_active")
        if unticked and user.pk == self.actor.pk:
            self.add_error("is_active", _("You can't deactivate yourself."))
        leaving = user.is_active and user.is_admin
        if (
            leaving
            and not (data.get("is_active") and data.get("is_admin"))
            and not User.objects
            .filter(is_active=True, is_admin=True)
            .exclude(pk=user.pk)
            .exists()
        ):
            raise forms.ValidationError(
                _("The last active admin can't be deactivated or stop being one.")
            )
        return data


@admin.register(User)
class UserAdmin(admin.ReadWriteModelAdmin):
    """Added and changed here; deactivated, never deleted (specs/activation.md)"""

    form = UserAdminForm
    list_display = [
        "email",
        "full_name",
        "is_client",
        "organization",
        "is_active",
        "mail_undeliverable_at",
    ]
    list_filter = ["is_client", "is_active", "is_admin", UndeliverableFilter]
    search_fields = ["email", "full_name", "short_name", "organization__name"]
    autocomplete_fields = ["organization"]
    fieldsets = [
        (None, {"fields": ["email", "full_name", "short_name", "language"]}),
        (None, {"fields": ["is_client", "organization"]}),
        (None, {"fields": ["is_active", "is_admin"]}),
        # Set by Resend's webhooks (specs/mail-sending.md), cleared here
        (None, {"fields": ["mail_undeliverable_at"]}),
    ]
    actions = ["clear_undeliverable"]

    def has_delete_permission(self, request, obj=None):
        return False

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.actor = request.user
        return form

    def save_model(self, request, obj, form, change):
        """Unticking ``is_active`` deactivates through the operation
        (sessions, API tokens and calendar links end, also after the
        commit), ticking it activates (``left_at`` goes); taking
        ``is_admin`` away locks the active admins first, so the last one
        stays (``activation.lock_with_admins()``). Another organization or
        becoming a client drops subscriptions in projects they can't open
        anymore, like moving them on the pages
        (``organizations.operations.access_changed()``); becoming a client
        also unassigns them from what they can't see and takes them out of
        their teams (``made_client()``)."""
        from biwak.organizations import activation
        from biwak.organizations.operations import access_changed, made_client

        if not change:
            super().save_model(request, obj, form, change)
            return
        before = activation.lock_with_admins([obj.pk])[0]
        deactivating = before.is_active and not obj.is_active
        activating = not before.is_active and obj.is_active
        if before.is_active and before.is_admin and not obj.is_admin:
            activation.check_admins_left({obj.pk})
        if deactivating or activating:
            # The operations change it
            obj.is_active = before.is_active
        super().save_model(request, obj, form, change)
        if deactivating:
            activation.deactivate([obj], actor=request.user)
        if activating:
            activation.activate([obj], actor=request.user)
        if deactivating or activating:
            obj.refresh_from_db(fields=["is_active", "left_at", "left_in_basecamp"])
        if (before.organization_id, before.is_client) != (
            obj.organization_id,
            obj.is_client,
        ):
            access_changed([obj.pk])
        if obj.is_client and not before.is_client:
            made_client(obj, actor=request.user)

    @admin.action(description=_("Mail to the selected people works again"))
    def clear_undeliverable(self, request, queryset):
        for user in queryset.filter(mail_undeliverable_at__isnull=False):
            user.mail_undeliverable_at = None
            user.save(update_fields=["mail_undeliverable_at"])


# The admins of Django and allauth, read only too: groups aren't used,
# addresses, passkeys and sign-ins change through the app (the settings, the
# resetting of a sign-in, deactivating), social apps are in the settings
for model, model_admin in [
    (Group, GroupAdmin),
    (EmailAddress, EmailAddressAdmin),
    (Authenticator, AuthenticatorAdmin),
    (SocialApp, SocialAppAdmin),
    (SocialToken, SocialTokenAdmin),
    (SocialAccount, SocialAccountAdmin),
]:
    admin.site.unregister(model)
    admin.site.register(
        model, type(model_admin.__name__, (admin.ReadOnlyMixin, model_admin), {})
    )


admin.site.unregister(UserSession)


@admin.register(UserSession)
class UserSessionAdmin(admin.ReadOnlyMixin, BaseUserSessionAdmin):
    # People have no username
    search_fields = ["user__email", "ip"]
