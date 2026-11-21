from django import forms
from django.contrib import admin
from django.db.models import Count

from biwak.organizations import operations as org_ops
from biwak.organizations.models import Organization


class OrganizationForm(forms.ModelForm):
    def _get_validation_exclusions(self):
        # Marking another one moves the mark (save_model()): not a clash
        return super()._get_validation_exclusions() | {"is_own"}


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Marking the installation's own organization is here (admins only,
    specs/organizations.md); the rest also on the pages for staff"""

    list_display = ["name", "domains", "is_own", "people_count"]
    list_filter = ["is_own"]
    search_fields = ["name", "domains"]
    fields = ["name", "domains", "is_own"]
    form = OrganizationForm

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(people_count=Count("people"))

    @admin.display(description="people", ordering="people_count")
    def people_count(self, obj):
        return obj.people_count

    def save_model(self, request, obj, form, change):
        if change and "is_own" in form.changed_data and not obj.is_own:
            super().save_model(request, obj, form, change)
            # Its people lose all-access projects they aren't members of
            org_ops._access_changed(obj.people.values_list("pk", flat=True))
            return
        # Only one is the installation's own: another one loses the mark
        if obj.is_own:
            obj.is_own = False
            super().save_model(request, obj, form, change)
            org_ops.mark_own(obj, actor=request.user)
        else:
            super().save_model(request, obj, form, change)
