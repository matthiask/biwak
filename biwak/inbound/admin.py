from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from biwak import admin
from biwak.inbound.models import InboundMessage, ReplyToken


@admin.register(ReplyToken)
class ReplyTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "item", "created_at", "expires_at", "revoked_at"]
    list_select_related = ["user", "item"]
    search_fields = ["user__email", "token"]
    actions = ["revoke"]

    @admin.action(description=_("Revoke the selected reply tokens"))
    def revoke(self, request, queryset):
        queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())


@admin.register(InboundMessage)
class InboundMessageAdmin(admin.ModelAdmin):
    list_display = ["received_at", "sender", "status", "provider", "provider_id"]
    list_filter = ["status", "provider"]
    search_fields = ["sender", "provider_id"]
