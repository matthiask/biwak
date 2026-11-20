from django.contrib import admin

from biwak.projects.models import Membership, Project


class MembershipInline(admin.TabularInline):
    model = Membership
    raw_id_fields = ["user"]
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "is_all_access", "archived_at"]
    list_filter = ["is_all_access"]
    search_fields = ["name"]
    inlines = [MembershipInline]
