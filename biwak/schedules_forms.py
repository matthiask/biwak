"""The form field and widget for repeat rules (specs/rule-widget.md), used
by the to-do forms and the question form; ``schedules.rule_fields()`` and
``schedules.build_rule()`` do the work, this is the glue to forms."""

import datetime as dt
import re

from django import forms
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.html import format_html
from django.utils.translation import gettext, gettext_lazy as _

from biwak import schedules


class Keep:
    """What the field cleans to for a rule the widget can't show, when
    the person didn't press "Replace": the form keeps the rule"""

    def __repr__(self):
        return "KEEP"


KEEP = Keep()
SINGLE = [
    "frequency",
    "interval",
    "monthly",
    "month_day",
    "ordinal",
    "weekday",
    "year_month",
    "year_day",
]


class RuleWidget(forms.Widget):
    """A fieldset of plain controls: all parts show without JavaScript,
    ``frontend/rule-widget.js`` hides those of other frequencies"""

    template_name = "forms/rule_widget.html"

    def __init__(self, attrs=None, *, allow_empty=True, default_frequency=""):
        super().__init__(attrs)
        self.allow_empty = allow_empty
        self.default_frequency = default_frequency
        self.label = ""
        self.anchor = None  # The date the defaults come from, set by the form

    def value_from_datadict(self, data, files, name):
        values = {
            key: data.get(f"{name}_{key}") for key in SINGLE if f"{name}_{key}" in data
        }
        key = f"{name}_weekdays"
        values["weekdays"] = (
            data.getlist(key) if hasattr(data, "getlist") else data.get(key, [])
        )
        values["unshowable"] = bool(data.get(f"{name}_keep"))
        values["replace"] = bool(data.get(f"{name}_replace"))
        return values

    def value_omitted_from_data(self, data, files, name):
        return False

    def _fields(self, value):
        """``(fields, unshowable, replace, rule)`` for the value: a rule
        (initial data) or the posted values"""
        anchor = self.anchor or schedules.today()
        fields = schedules.default_fields(anchor, self.default_frequency)
        unshowable = replace = False
        rule = ""
        if isinstance(value, dict):
            unshowable, replace = value["unshowable"], value["replace"]
            fields |= {k: v for k, v in value.items() if k in {*SINGLE, "weekdays"}}
        elif value:
            rule = value
            shown = schedules.rule_fields(value)
            if shown is None:
                unshowable = True
            else:
                fields |= shown
        return fields, unshowable, replace, rule

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        fields, unshowable, replace, rule = self._fields(value)
        field_id = context["widget"]["attrs"].get("id") or f"id_{name}"
        if not rule and not unshowable:
            try:
                rule = schedules.build_rule(fields)
            except schedules.InvalidRule:
                rule = ""
        widget = context["widget"]
        widget.update(
            id=field_id,
            label=self.label,
            fields=fields,
            unshowable=unshowable,
            replace=replace,
            description=schedules.describe(rule) if rule else "",
            current=rule if unshowable else "",
            describe_url=reverse("schedules_describe"),
            frequencies=[
                *([("", gettext("Doesn't repeat"))] if self.allow_empty else []),
                ("daily", gettext("Daily")),
                ("weekly", gettext("Weekly")),
                ("monthly", gettext("Monthly")),
                ("yearly", gettext("Yearly")),
            ],
            weekdays=[
                (code, str(full)[:3], full, code in fields["weekdays"])
                for code, full in zip(schedules.DAYS, schedules.DAY_NAMES, strict=True)
            ],
            ordinals=[
                (n, str(schedules.ORDINALS[n])) for n in schedules.ORDINAL_VALUES
            ],
            weekday_choices=[
                *zip(schedules.DAYS, schedules.DAY_NAMES, strict=True),
                (schedules.WORKING_DAY, _("working day")),
            ],
            months=[(n, _month_name(n)) for n in range(1, 13)],
        )
        return context

    def id_for_label(self, id_):
        return f"{id_}_frequency" if id_ else id_


def _month_name(n):
    return date_format(dt.date(2028, n, 1), "F")


class RuleField(forms.Field):
    """Cleans to the rule (``""`` for none), or to ``KEEP`` for a rule
    the widget can't show and the person left alone"""

    widget = RuleWidget

    def __init__(self, *, allow_empty=True, default_frequency="", **kwargs):
        kwargs.setdefault("required", False)
        kwargs["widget"] = RuleWidget(
            allow_empty=allow_empty, default_frequency=default_frequency
        )
        super().__init__(**kwargs)
        self.widget.label = self.label
        self.allow_empty = allow_empty

    def to_python(self, value):
        if not value:
            value = {}
        if value.get("unshowable") and not value.get("replace"):
            return KEEP
        try:
            rule = schedules.build_rule(value)
        except schedules.InvalidRule as exc:
            if exc.errors:
                raise ValidationError([
                    ValidationError(str(m)) for m in exc.errors.values()
                ]) from exc
            raise ValidationError(str(exc)) from exc
        if not rule and not self.allow_empty:
            raise ValidationError(_("Choose how often it repeats."))
        return rule

    def validate(self, value):
        pass

    def bound_data(self, data, initial):
        if data.get("unshowable") and not data.get("replace"):
            return initial
        return data

    def has_changed(self, initial, data):
        return True


_NAME = re.compile(r"\w+")


def describe(request):
    """The description of the rule in the widget's fields
    (``?name=<field name>&<name>_frequency=…``), for htmx"""
    name = request.GET.get("name", "")
    if not _NAME.fullmatch(name):
        return HttpResponse(status=400)
    values = RuleWidget().value_from_datadict(request.GET, None, name)
    if values["unshowable"] and not values["replace"]:
        return HttpResponse("")
    try:
        rule = schedules.build_rule(values)
    except schedules.InvalidRule as exc:
        return HttpResponse(format_html('<span class="text-danger">{}</span>', exc))
    return HttpResponse(format_html("{}", schedules.describe(rule) if rule else ""))
