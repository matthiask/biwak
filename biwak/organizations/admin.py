from django import forms
from django.db.models import Count
from django.utils.translation import gettext as _

from biwak import admin
from biwak.accounts import sso
from biwak.organizations import operations as org_ops
from biwak.organizations.models import Organization, SignIn


class OrganizationForm(forms.ModelForm):
    def _get_validation_exclusions(self):
        # Marking another one moves the mark (save_model()): not a clash
        return super()._get_validation_exclusions() | {"is_own"}

    def clean(self):
        """Admins stay own staff (decided 2026-11-21):
        not unmarking or moving the mark while admins would be left out"""
        data = super().clean()
        was_own = (
            bool(self.instance.pk)
            and Organization.objects.filter(pk=self.instance.pk, is_own=True).exists()
        )
        if was_own and not data.get("is_own"):
            raise forms.ValidationError(
                _("There is always your own organization: mark another one instead.")
            )
        if data.get("is_own") and not was_own:
            for old in Organization.objects.filter(is_own=True):
                org_ops._no_admin_externals(org_ops._admins_in(old), own_after=False)
        # The same checks as the organization's page (specs/sso.md)
        if {"signin", "idp", "tenant_id"} & set(self.changed_data):
            org = Organization(pk=self.instance.pk, domains=data.get("domains") or [])
            data["signin"], data["idp"], data["tenant_id"] = org_ops.clean_signin(
                org,
                signin=data.get("signin"),
                idp=data.get("idp"),
                tenant_id=data.get("tenant_id"),
            )
            org.signin, org.idp, org.tenant_id = (
                data["signin"],
                data["idp"],
                data["tenant_id"],
            )
            user = self.request.user
            if (
                org.requires_sso
                and org.pk is not None
                and user.organization_id == org.pk
                and not sso.signed_in_with_idp(self.request, user, org)
            ):
                raise forms.ValidationError(
                    _(
                        "Sign in with %(provider)s first: requiring it signs you"
                        " out of sessions that didn't."
                    )
                    % {"provider": org.get_idp_display()}
                )
        if data.get("signin", SignIn.CODES) != SignIn.CODES and not data.get("domains"):
            raise forms.ValidationError(
                _(
                    "With single sign-on, the organization needs its email"
                    " domains: sign-ins count only for them."
                )
            )
        return data


@admin.register(Organization)
class OrganizationAdmin(admin.ReadWriteModelAdmin):
    """Marking the own organization is here (admins only,
    specs/organizations.md); the rest also on the pages for staff"""

    list_display = ["name", "domains", "is_own", "signin", "idp", "people_count"]
    list_filter = ["is_own", "signin", "idp"]
    search_fields = ["name", "domains"]
    fields = ["name", "domains", "is_own", "signin", "idp", "tenant_id"]
    form = OrganizationForm

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(people_count=Count("people"))

    @admin.display(description="people", ordering="people_count")
    def people_count(self, obj):
        return obj.people_count

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.request = request
        return form

    def save_model(self, request, obj, form, change):
        if change and {"signin", "idp", "tenant_id"} & set(form.changed_data):
            # Through the operation, which ends what requiring single
            # sign-on ends (specs/sso.md)
            signin = {f: getattr(obj, f) for f in ["signin", "idp", "tenant_id"]}
            stored = Organization.objects.get(pk=obj.pk)
            for field in signin:
                setattr(obj, field, getattr(stored, field))
            self._save(request, obj, form, change)
            org_ops.set_signin(obj, actor=request.user, **signin)
        else:
            self._save(request, obj, form, change)
            if change and "domains" in form.changed_data and obj.requires_sso:
                # Sign-ins through domains it doesn't have anymore end
                sso.enforce_required_now_and_after_commit(
                    obj.people.values_list("pk", flat=True)
                )

    def _save(self, request, obj, form, change):
        # Only one is the own organization: another one loses the mark
        if obj.is_own:
            obj.is_own = False
            super().save_model(request, obj, form, change)
            org_ops.mark_own(obj, actor=request.user)
        else:
            super().save_model(request, obj, form, change)
