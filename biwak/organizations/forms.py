"""Picking an organization (specs/organizations.md): a text field with the
existing names to complete (a ``<datalist>``, no JavaScript); a name that
doesn't exist yet creates the organization only after confirming, which
catches most typos."""

from collections import UserString

from django import forms
from django.utils.translation import gettext as _, gettext_lazy

from biwak.organizations import operations as org_ops
from biwak.organizations.models import Organization, normalize_name


class OrganizationInput(forms.TextInput):
    template_name = "organizations/_organization_input.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["names"] = list(
            Organization.objects.values_list("name", flat=True)
        )
        context["widget"]["attrs"]["list"] = f"{context['widget']['attrs']['id']}-names"
        return context


class NewOrganization(UserString):
    """A confirmed name of an organization which doesn't exist yet"""


def organization_field(**kwargs):
    kwargs.setdefault("label", gettext_lazy("Organization"))
    return forms.CharField(
        max_length=200,
        required=False,
        widget=OrganizationInput(attrs={"autocomplete": "off"}),
        **kwargs,
    )


class OrganizationFieldMixin:
    """For forms with an ``organization`` field (``organization_field()``):
    its cleaned value is an ``Organization``, a ``NewOrganization`` once the
    ``create_organization`` box is ticked, or None; ``organization()``
    creates a new one."""

    organization_field_name = "organization"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        name = self.organization_field_name
        typed = normalize_name(self.data.get(self.add_prefix(name), ""))
        if self.is_bound and typed and not Organization.objects.named(typed):
            self.fields[f"create_{name}"] = forms.BooleanField(
                label=_("Create “%(name)s”?") % {"name": typed},
                required=False,
            )

    def clean(self):
        data = super().clean()
        name = self.organization_field_name
        typed = normalize_name(data.get(name) or "")
        if not typed:
            data[name] = None
        elif org := Organization.objects.named(typed):
            data[name] = org
        elif data.get(f"create_{name}"):
            data[name] = NewOrganization(typed)
        else:
            self.add_error(
                name,
                _(
                    "There's no organization called “%(name)s”: check the"
                    " spelling, or tick “Create” to add it."
                )
                % {"name": typed},
            )
        return data

    def organization(self, actor):
        """The cleaned organization, created now if new"""
        org = self.cleaned_data.get(self.organization_field_name)
        if isinstance(org, NewOrganization):
            return org_ops.create_organization(name=str(org), actor=actor)
        return org
