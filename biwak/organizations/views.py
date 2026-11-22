"""The pages of organizations (specs/organizations.md, "Managing"): for the
own staff, the forms as modals and pages (``biwak/modals.py``)"""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _, gettext_lazy

from biwak.accounts.models import User
from biwak.forms import Form
from biwak.modals import form_response
from biwak.organizations import operations as org_ops
from biwak.organizations.forms import OrganizationFieldMixin, organization_field
from biwak.organizations.models import IdP, Organization, SignIn


def managing(request):
    if not org_ops.can_manage(request.user):
        raise PermissionDenied


def organization_for(request, pk):
    managing(request)
    return get_object_or_404(Organization, pk=pk)


def organization_list(request):
    managing(request)
    organizations = (
        Organization.objects
        .annotate(people_count=Count("people"))
        .order_by(Lower("name"))
        .prefetch_related(
            Prefetch("people", queryset=User.objects.order_by("full_name", "email"))
        )
    )
    return render(
        request,
        "organizations/organization_list.html",
        {"organizations": organizations},
    )


def organization_detail(request, pk):
    org = organization_for(request, pk)
    people = list(org.people.order_by("-is_active", "is_client", "full_name", "email"))
    can_touch = org_ops.can_touch(request.user, org)
    for user in people:
        user.can_move = can_touch and org_ops.can_touch(request.user, org, person=user)
    return render(
        request,
        "organizations/organization_detail.html",
        {
            "organization": org,
            "people": people,
            "can_touch": org_ops.can_touch(request.user, org),
            "can_change_signin": org_ops.can_change_signin(request.user),
            "can_delete": org_ops.can_touch(request.user, org)
            and not org.is_own
            and not people,
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

    def __init__(self, *args, instance=None, user=None, **kwargs):
        self.instance = instance
        if instance is not None:
            kwargs.setdefault(
                "initial",
                {"name": instance.name, "domains": " ".join(instance.domains)},
            )
        super().__init__(*args, **kwargs)
        if instance is not None and not org_ops.can_change_domains(user, instance):
            # They decide whose sign-ins count (specs/sso.md), or who is
            # suggested for an external organization (decided 2026-11-21)
            self.fields["domains"].disabled = True
            self.fields["domains"].help_text = (
                _("It signs in with %(provider)s: only admins change its domains.")
                % {"provider": instance.idp_name}
                if instance.sso
                else _("An external organization: only admins change its domains.")
            )

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
    form = OrganizationForm(request.POST or None, instance=org, user=request.user)
    if form.is_valid():
        try:
            org_ops.update_organization(org, actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error("domains", exc)
        else:
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
    # Merging into a stricter sign-in (admins only, specs/sso.md)
    confirm = forms.BooleanField(
        label=gettext_lazy("Yes, change how they sign in"),
        required=False,
        widget=forms.HiddenInput,
    )

    def __init__(self, *args, organization, user, **kwargs):
        super().__init__(*args, **kwargs)
        others = Organization.objects.exclude(pk=organization.pk)
        if not user.is_admin:
            others = others.exclude(is_own=True).exclude(
                pk__in=org_ops.external_organizations().values("pk")
            )
        self.fields["into"].queryset = others


def organization_merge(request, pk):
    """The typo case: the people and domains go to the other one, this one
    is deleted"""
    org = organization_for(request, pk)
    if not org_ops.can_touch(request.user, org):
        raise PermissionDenied
    form = MergeForm(request.POST or None, organization=org, user=request.user)
    target = None
    if form.is_valid():
        try:
            target = org_ops.merge(
                org,
                form.cleaned_data["into"],
                actor=request.user,
                confirmed=form.cleaned_data["confirm"],
            )
        except ValidationError as exc:
            if getattr(exc, "code", None) == "confirm":
                # The warning, and the box confirming it
                form.fields["confirm"].widget = forms.CheckboxInput()
            form.add_error(None, exc)
        except PermissionError as exc:
            form.add_error(None, str(exc))
    if target is not None:
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
    organization = organization_field(
        help_text=gettext_lazy(
            "Empty: none. Staff without an organization see only the projects"
            " they're added to."
        )
    )


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
            request.user,
            current,
            target if isinstance(target, Organization) else None,
            person=user,
        ):
            form.add_error("organization", str(org_ops.TOUCH_MESSAGE))
        else:
            try:
                # A new organization only with the move
                with transaction.atomic():
                    org_ops.set_organization(
                        user, form.organization(request.user), actor=request.user
                    )
            except ValidationError as exc:
                form.add_error("organization", exc)
            except PermissionError as exc:
                form.add_error("organization", str(exc))
            else:
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


class SignInForm(Form):
    signin = forms.ChoiceField(
        label=gettext_lazy("Sign-in"), choices=SignIn.choices, widget=forms.RadioSelect
    )
    idp = forms.ChoiceField(
        label=gettext_lazy("Identity provider"),
        choices=[("", gettext_lazy("None")), *IdP.choices],
        required=False,
        widget=forms.RadioSelect,
        help_text=gettext_lazy(
            "Google Workspace: sign-ins count for the organization's email"
            " domains (Google's hd). Microsoft Entra ID: for its tenant and"
            " addresses of its domains."
        ),
    )
    tenant_id = forms.CharField(
        label=gettext_lazy("Microsoft tenant ID"),
        required=False,
        max_length=36,
        help_text=gettext_lazy(
            "The Directory (tenant) ID in the Microsoft Entra admin center."
        ),
    )
    two_factor = forms.BooleanField(
        label=gettext_lazy("Require a second factor"),
        required=False,
        help_text=gettext_lazy(
            "A code by mail alone isn't enough: its people sign in with a"
            " passkey, through the identity provider, or with a code and an"
            " authenticator app. People with neither add one first. Not"
            " needed where single sign-on is required."
        ),
    )

    def __init__(self, *args, organization, request, **kwargs):
        self.organization = organization
        self.request = request
        kwargs.setdefault(
            "initial",
            {
                "signin": organization.signin,
                "idp": organization.idp,
                "tenant_id": organization.tenant_id,
                "two_factor": organization.requires_two_factor,
            },
        )
        super().__init__(*args, **kwargs)

    def clean(self):
        from biwak.accounts import sso

        data = super().clean()
        if self.errors:
            return data
        signin, idp, tenant_id = org_ops.clean_signin(
            self.organization,
            signin=data["signin"],
            idp=data.get("idp", ""),
            tenant_id=data.get("tenant_id", ""),
        )
        user = self.request.user
        if (
            signin == SignIn.SSO_REQUIRED
            and user.organization_id == self.organization.pk
            and not sso.signed_in_with_idp(
                self.request,
                user,
                Organization(
                    pk=self.organization.pk,
                    domains=self.organization.domains,
                    signin=signin,
                    idp=idp,
                    tenant_id=tenant_id,
                ),
            )
        ):
            # Not locking oneself out: it works for the one requiring it
            raise ValidationError(
                _(
                    "Sign in with %(provider)s first: requiring it signs you"
                    " out of sessions that didn't."
                )
                % {"provider": IdP(idp).label}
            )
        return {
            "signin": signin,
            "idp": idp,
            "tenant_id": tenant_id,
            "two_factor": data.get("two_factor", False),
        }


def organization_signin(request, pk):
    """How the organization's people sign in (specs/sso.md): admins only"""
    org = organization_for(request, pk)
    if not org_ops.can_change_signin(request.user):
        raise PermissionDenied
    form = SignInForm(request.POST or None, organization=org, request=request)
    if form.is_valid():
        org_ops.set_signin(org, actor=request.user, **form.cleaned_data)
        messages.success(
            request,
            _("How %(organization)s signs in has been saved.") % {"organization": org},
        )
        return redirect(org)
    return form_response(
        request,
        form,
        title=_("Sign-in of %(organization)s") % {"organization": org},
        intro=_(
            "Single sign-on required: its people sign in only through the"
            " identity provider, their passkeys are removed, sessions and API"
            " tokens last 24 hours."
        ),
        help_page="sign-in",
        cancel_url=org.get_absolute_url(),
    )
