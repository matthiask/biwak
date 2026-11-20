from django.contrib import admin
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from biwak.inbound.models import InboundMessage, ReplyToken


@admin.register(ReplyToken)
class ReplyTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "item", "created_at", "expires_at", "revoked_at"]
    list_select_related = ["user", "item"]
    search_fields = ["user__email", "token"]
    raw_id_fields = ["item", "user", "occurrence"]
    readonly_fields = ["token", "created_at", "error_sent_at"]
    actions = ["revoke"]

    @admin.action(description=_("Revoke the selected reply tokens"))
    def revoke(self, request, queryset):
        queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())


@admin.register(InboundMessage)
class InboundMessageAdmin(admin.ModelAdmin):
    list_display = ["received_at", "sender", "status", "provider", "provider_id"]
    list_filter = ["status", "provider"]
    search_fields = ["sender", "provider_id"]
    raw_id_fields = ["token", "comment", "answer"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
