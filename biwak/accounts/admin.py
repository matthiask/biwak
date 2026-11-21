from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from biwak.accounts.models import User


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
    active admin stays (``is_active`` and ``is_admin``)"""

    class Meta:
        model = User
        # The admin's fieldsets decide
        fields = ["is_active", "is_admin"]

    def clean(self):
        data = super().clean()
        user = self.instance
        if user.pk is None:
            return data
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
class UserAdmin(admin.ModelAdmin):
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

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.actor = request.user
        return form

    def save_model(self, request, obj, form, change):
        """Unticking ``is_active`` deactivates through the operation
        (sessions, API tokens and calendar links end, also after the
        commit); taking ``is_admin`` away locks the active admins first, so
        the last one stays (``activation.lock_with_admins()``)"""
        from biwak.organizations import activation

        if not change:
            super().save_model(request, obj, form, change)
            return
        before = activation.lock_with_admins([obj.pk])[0]
        deactivating = before.is_active and not obj.is_active
        if before.is_active and before.is_admin and not obj.is_admin:
            activation.check_admins_left({obj.pk})
        if deactivating:
            obj.is_active = True
        super().save_model(request, obj, form, change)
        if deactivating:
            activation.deactivate([obj], actor=request.user)
            obj.is_active = False

    @admin.action(description=_("Mail to the selected people works again"))
    def clear_undeliverable(self, request, queryset):
        for user in queryset.filter(mail_undeliverable_at__isnull=False):
            user.mail_undeliverable_at = None
            user.save(update_fields=["mail_undeliverable_at"])
