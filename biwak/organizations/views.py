"""The pages of organizations (specs/organizations.md, "Managing"): for the
installation's own staff, the forms as modals and pages (``biwak/modals.py``)"""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _, gettext_lazy

from biwak.accounts.models import User
from biwak.forms import Form
from biwak.modals import form_response
from biwak.organizations import operations as org_ops
from biwak.organizations.forms import OrganizationFieldMixin, organization_field
from biwak.organizations.models import Organization


def managing(request):
    if not org_ops.can_manage(request.user):
        raise PermissionDenied


def organization_for(request, pk):
    managing(request)
    return get_object_or_404(Organization, pk=pk)


def organization_list(request):
    managing(request)
    organizations = Organization.objects.annotate(
        people_count=Count("people")
    ).prefetch_related(
        Prefetch("people", queryset=User.objects.order_by("full_name", "email"))
    )
    return render(
        request,
        "organizations/organization_list.html",
        {"organizations": organizations},
    )


def organization_detail(request, pk):
    org = organization_for(request, pk)
    people = org.people.order_by("-is_active", "is_client", "full_name", "email")
    return render(
        request,
        "organizations/organization_detail.html",
        {
            "organization": org,
            "people": people,
            "can_touch": org_ops.can_touch(request.user, org),
            "can_delete": org_ops.can_touch(request.user, org) and not people.exists(),
        },
    )


class OrganizationForm(Form):
    name = forms.CharField(label=gettext_lazy("Name"), max_length=200)
    domains = forms.CharField(
        label=gettext_lazy("Email domains"),
        required=False,
        help_text=gettext_lazy(
            "Separated by spaces or commas, e.g. example.org. Inviting an"
            " address of these domains suggests the organization; free-mail"
            " domains never do."
        ),
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        if instance is not None:
            kwargs.setdefault(
                "initial",
                {"name": instance.name, "domains": " ".join(instance.domains)},
            )
        super().__init__(*args, **kwargs)

    def clean_name(self):
        return org_ops.clean_name(self.cleaned_data["name"], instance=self.instance)

    def clean_domains(self):
        return org_ops.clean_domains(
            self.cleaned_data["domains"], instance=self.instance
        )


def organization_create(request):
    managing(request)
    form = OrganizationForm(request.POST or None)
    if form.is_valid():
        org = org_ops.create_organization(actor=request.user, **form.cleaned_data)
        return redirect(org)
    return form_response(
        request,
        form,
        title=_("New organization"),
        cancel_url=reverse("organizations"),
        submit_label=_("Add organization"),
    )


def organization_edit(request, pk):
    org = organization_for(request, pk)
    form = OrganizationForm(request.POST or None, instance=org)
    if form.is_valid():
        org_ops.update_organization(org, actor=request.user, **form.cleaned_data)
        return redirect(org)
    return form_response(
        request,
        form,
        title=_("Edit %(organization)s") % {"organization": org},
        intro=_("A new name is shown everywhere, for everybody."),
        cancel_url=org.get_absolute_url(),
    )


class MergeForm(Form):
    into = forms.ModelChoiceField(
        label=gettext_lazy("Merge into"), queryset=Organization.objects.none()
    )

    def __init__(self, *args, organization, user, **kwargs):
        super().__init__(*args, **kwargs)
        others = Organization.objects.exclude(pk=organization.pk)
        if not user.is_admin:
            others = others.exclude(is_own=True)
        self.fields["into"].queryset = others


def organization_merge(request, pk):
    """The typo case: the people and domains go to the other one, this one
    is deleted"""
    org = organization_for(request, pk)
    if not org_ops.can_touch(request.user, org):
        raise PermissionDenied
    form = MergeForm(request.POST or None, organization=org, user=request.user)
    if form.is_valid():
        target = org_ops.merge(org, form.cleaned_data["into"], actor=request.user)
        messages.success(
            request,
            _("%(source)s has been merged into %(target)s.")
            % {"source": org, "target": target},
        )
        return redirect(target)
    return form_response(
        request,
        form,
        title=_("Merge %(organization)s") % {"organization": org},
        intro=_(
            "Its people and domains move to the organization you pick, and"
            " %(organization)s is deleted."
        )
        % {"organization": org},
        cancel_url=org.get_absolute_url(),
        submit_label=_("Merge"),
        destructive=True,
    )


def organization_delete(request, pk):
    """Only organizations nobody belongs to: a question"""
    org = organization_for(request, pk)
    if not org_ops.can_touch(request.user, org):
        raise PermissionDenied
    if request.method == "POST":
        try:
            org_ops.delete_organization(org, actor=request.user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect(org)
        messages.success(
            request, _("%(organization)s has been deleted.") % {"organization": org}
        )
        return redirect("organizations")
    return form_response(
        request,
        None,
        title=_("Delete %(organization)s?") % {"organization": org},
        intro=_("Nobody belongs to it."),
        cancel_url=org.get_absolute_url(),
        submit_label=_("Delete"),
        destructive=True,
    )


class PersonOrganizationForm(OrganizationFieldMixin, Form):
    organization = organization_field(help_text=gettext_lazy("Empty: none."))


def person_organization(request, pk):
    """Moves somebody to another organization (or none)"""
    managing(request)
    user = get_object_or_404(User, pk=pk)
    form = PersonOrganizationForm(
        request.POST or None,
        initial={"organization": user.organization_name},
    )
    if form.is_valid():
        target = form.cleaned_data["organization"]
        current = user.organization if user.organization_id else None
        if not org_ops.can_touch(
            request.user, current, target if isinstance(target, Organization) else None
        ):
            form.add_error(
                "organization",
                _(
                    "Only admins move people in or out of the installation's own organization."
                ),
            )
        else:
            org_ops.set_organization(
                user, form.organization(request.user), actor=request.user
            )
            messages.success(
                request,
                _("%(name)s's organization has been saved.") % {"name": user},
            )
            return redirect(user.organization or "organizations")
    return form_response(
        request,
        form,
        title=_("The organization of %(name)s") % {"name": user},
        cancel_url=(
            user.organization.get_absolute_url()
            if user.organization_id
            else reverse("organizations")
        ),
    )
