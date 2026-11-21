from django import forms
from django.forms.renderers import TemplatesSetting
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _


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


class ColorSwatches(forms.RadioSelect):
    """A row of radio swatches, one per color, plus "None": the color's name
    is the accessible label and title (``forms/color_swatches.html``)"""

    template_name = "forms/color_swatches.html"
    option_template_name = "forms/color_swatch_option.html"


class Form(BootstrapMixin, forms.Form):
    pass


class ModelForm(BootstrapMixin, forms.ModelForm):
    pass


def assignee_picker_attrs():
    """What turns a ``<select multiple>`` of people into the picker of
    ``frontend/assignees.js`` and the texts it shows; without JavaScript
    the select stays as it is"""
    return {
        "data-assignee-picker": "",
        "data-placeholder": _("Assign…"),
        "data-empty": _("Nobody found"),
        "data-remove": _("Remove %(name)s"),
        "data-new": _("not in the project yet"),
    }


class AssigneeSelect(forms.SelectMultiple):
    """People to choose from, the project's members first (the order of
    ``ops.assignable_people()``); each option says whether the person is a
    member, since assigning staff who aren't makes them one"""

    def __init__(self, attrs=None):
        super().__init__({**assignee_picker_attrs(), **(attrs or {})})

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        instance = getattr(value, "instance", None)
        if instance is not None and hasattr(instance, "is_member"):
            option["attrs"]["data-member"] = "true" if instance.is_member else "false"
        if instance is not None and hasattr(instance, "avatar_json"):
            option["attrs"]["data-avatar"] = instance.avatar_json
        return option


class AssigneeField(forms.ModelMultipleChoiceField):
    widget = AssigneeSelect

    def __init__(self, queryset, **kwargs):
        kwargs.setdefault("required", False)
        super().__init__(queryset, **kwargs)

    def label_from_instance(self, obj):
        return obj.get_short_name()
