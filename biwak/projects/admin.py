from biwak import admin
from biwak.projects.models import Membership, Project


class MembershipInline(admin.TabularInline):
    """Read-only: people join, are added and leave through the app, which
    records the events (specs/access.md)"""

    model = Membership
    fields = readonly_fields = ["user", "created_at"]
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "is_all_access", "archived_at"]
    list_filter = ["is_all_access"]
    search_fields = ["name"]
    inlines = [MembershipInline]
