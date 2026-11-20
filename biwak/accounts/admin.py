from django.contrib import admin

from biwak.accounts.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["email", "full_name", "is_client", "organization", "is_active"]
    list_filter = ["is_client", "is_active", "is_admin"]
    search_fields = ["email", "full_name", "short_name", "organization"]
    fieldsets = [
        (None, {"fields": ["email", "full_name", "short_name", "language"]}),
        (None, {"fields": ["is_client", "organization"]}),
        (None, {"fields": ["is_active", "is_admin"]}),
    ]
