import json

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from biwak.outbox.models import OutgoingMail


class StateFilter(admin.SimpleListFilter):
    title = _("state")
    parameter_name = "state"

    def lookups(self, request, model_admin):
        return [
            ("waiting", _("waiting")),
            ("sent", _("sent")),
            ("given_up", _("given up")),
        ]

    def queryset(self, request, queryset):
        match self.value():
            case "waiting":
                return queryset.pending()
            case "sent":
                return queryset.filter(sent_at__isnull=False)
            case "given_up":
                return queryset.filter(given_up_at__isnull=False)
        return queryset


@admin.register(OutgoingMail)
class OutgoingMailAdmin(admin.ModelAdmin):
    """Read-only: the outbox and Resend's webhooks change the rows"""

    list_display = [
        "created_at",
        "kind",
        "to",
        "state",
        "attempts",
        "delivery",
        "provider_id",
    ]
    list_filter = [StateFilter, "kind", "delivery"]
    search_fields = ["recipients", "provider_id"]
    date_hierarchy = "created_at"
    fields = [
        "kind",
        "recipients",
        "created_at",
        "attempts",
        "next_attempt_at",
        "expires_at",
        "sent_at",
        "given_up_at",
        "last_error",
        "provider_id",
        "delivery",
        "delivery_at",
        "delivery_detail",
        "content",
    ]
    readonly_fields = fields

    @admin.display(description=_("to"))
    def to(self, obj):
        return ", ".join(obj.recipients)

    @admin.display(description=_("state"))
    def state(self, obj):
        return obj.state

    @admin.display(description=_("content"))
    def content(self, obj):
        if obj.message is None:
            return _("Deleted once sent; Resend's log has it.")
        return format_html(
            "<pre>{}</pre>", json.dumps(obj.message, indent=2, ensure_ascii=False)
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
