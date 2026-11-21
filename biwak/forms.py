from django import forms
from django.forms.renderers import TemplatesSetting
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _

from biwak.text import line_breaks


# Django 6.1's label of empty choices (``BLANK_CHOICE_LABEL``) has no German
# translation yet: ours, kept in the catalog because it appears here
BLANK_CHOICE_LABEL = _("- Select an option -")


def next_url(request):
    """Where to go after saving, e.g. back to the meeting amending the
    proposal or to the circle's page (``?next=`` or a ``next`` field)"""
    url = request.POST.get("next") or request.GET.get("next")
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return None


class Renderer(TemplatesSetting):
    """Fields with Bootstrap's markup, see ``forms/field.html``"""

    field_template_name = "forms/field.html"


class BootstrapMixin:
    """Bootstrap's classes on the widgets, also of fields added later"""

    def __getitem__(self, name):
        widget = self.fields[name].widget
        if isinstance(
            widget,
            forms.CheckboxInput | forms.RadioSelect | forms.CheckboxSelectMultiple,
        ):
            css = "form-check-input"
        elif isinstance(widget, forms.Select | forms.SelectMultiple):
            css = "form-select"
        else:
            css = "form-control"
        classes = widget.attrs.get("class", "").split()
        if css not in classes:
            widget.attrs["class"] = " ".join([*classes, css])
        if isinstance(widget, forms.Textarea):
            # Autocompleting @mentions of roles, see mentions.js
            widget.attrs.setdefault("data-mentions", "")
            # Every text is Markdown: the toolbar of toolbar.js
            widget.attrs.setdefault("data-toolbar", "")
        return super().__getitem__(name)

    def _clean_fields(self):
        super()._clean_fields()
        # Texts with \n line breaks only, as the live editor counts them
        for name, field in self.fields.items():
            value = self.cleaned_data.get(name)
            if isinstance(field.widget, forms.Textarea) and isinstance(value, str):
                self.cleaned_data[name] = line_breaks(value)


class ColorSwatches(forms.RadioSelect):
    """A row of radio swatches, one per color, plus "None": the color's name
    is the accessible label and title (``forms/color_swatches.html``)"""

    template_name = "forms/color_swatches.html"
    option_template_name = "forms/color_swatch_option.html"


class Form(BootstrapMixin, forms.Form):
    pass


class ModelForm(BootstrapMixin, forms.ModelForm):
    pass


def people_picker_attrs(placeholder=None):
    """What turns a ``<select multiple>`` of people into the picker of
    ``frontend/people-picker.js`` and the texts it shows; without
    JavaScript the select stays as it is"""
    return {
        "data-people-picker": "",
        "data-placeholder": placeholder or _("Assign…"),
        "data-empty": _("Nobody found"),
        "data-remove": _("Remove %(name)s"),
        "data-new": _("not in the project yet"),
    }


class PeopleSelect(forms.SelectMultiple):
    """People to choose from, with search, avatars and pills
    (``frontend/people-picker.js``): assignees, subscribers, whom to
    notify. Each option says whether the person is a member when the
    queryset says (``ops.assignable_people()``: assigning staff who aren't
    makes them one)."""

    placeholder = None

    def __init__(self, attrs=None):
        super().__init__({**people_picker_attrs(self.placeholder), **(attrs or {})})

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        instance = getattr(value, "instance", None)
        if instance is not None and hasattr(instance, "is_member"):
            option["attrs"]["data-member"] = "true" if instance.is_member else "false"
        if instance is not None and hasattr(instance, "avatar_json"):
            option["attrs"]["data-avatar"] = instance.avatar_json
        return option


class PeopleField(forms.ModelMultipleChoiceField):
    """People in the picker, by the name the one looking may know"""

    widget = PeopleSelect

    def __init__(self, queryset, **kwargs):
        kwargs.setdefault("required", False)
        super().__init__(queryset, **kwargs)

    def label_from_instance(self, obj):
        # Who is looking: the request's user (biwak.activity.mentions)
        from biwak.activity.mentions import reader
        from biwak.organizations.names import display_name

        return display_name(obj, reader())


class ComboboxSelect(forms.Select):
    """A select with a search field which finds the typed words anywhere in
    the options (``frontend/combobox.js``, from Workbench's; specs/ui.md,
    "Forms"): for selects with many choices. Without JavaScript it's the plain
    select. ``search`` returns more text to find an option by (an address),
    given the option's model instance."""

    def __init__(self, attrs=None, choices=(), *, search=None):
        super().__init__(
            {
                "data-combobox": "",
                "data-placeholder": _("Search…"),
                "data-empty": _("Nothing found"),
                **(attrs or {}),
            },
            choices,
        )
        self.search = search

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        instance = getattr(value, "instance", None)
        if self.search is not None and instance is not None:
            option["attrs"]["data-search"] = self.search(instance)
        return option


def person_label(person):
    """Who someone is, in a long list of people: "Ada Example · Example
    Client Ltd", the organization's name (staff without one: "staff")"""
    if person.organization_id:
        return f"{person} · {person.organization_name}"
    if not person.is_client:
        return f"{person} · {_('staff')}"
    return str(person)


class PersonChoiceField(forms.ModelChoiceField):
    """A person out of many, in a combobox; ``with_address`` also finds them
    by their address (for those who may see addresses)"""

    def __init__(self, queryset, *, with_address=False, **kwargs):
        kwargs.setdefault(
            "widget",
            ComboboxSelect(
                search=(lambda person: person.email) if with_address else None
            ),
        )
        super().__init__(queryset, **kwargs)

    def _set_queryset(self, queryset):
        # The organization's name in each label, without a query per person
        if queryset is not None:
            queryset = queryset.select_related("organization")
        super()._set_queryset(queryset)

    queryset = property(forms.ModelChoiceField._get_queryset, _set_queryset)

    def label_from_instance(self, obj):
        return person_label(obj)
