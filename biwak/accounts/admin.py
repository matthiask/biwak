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


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
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

    @admin.action(description=_("Mail to the selected people works again"))
    def clear_undeliverable(self, request, queryset):
        for user in queryset.filter(mail_undeliverable_at__isnull=False):
            user.mail_undeliverable_at = None
            user.save(update_fields=["mail_undeliverable_at"])
