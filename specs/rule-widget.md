# The rule widget

One control for repeat rules wherever they are edited: to-dos (the
inline form and the to-do's page) and check-in questions. Decided
2026-11-20: widget only, no presets and no raw RRULE in the forms, the
description instead of a preview of dates. The API and the CLI keep
RRULEs and preset names.

**Status:** built (2026-11-20): `rule_fields()`, `build_rule()` and
`default_fields()` in `biwak/schedules.py` (the only place that knows
RRULE syntax); `RuleField` and `RuleWidget` in `biwak/schedules_forms.py`
with `forms/rule_widget.html` and `{% rule_widget %}` for the inline
forms; `GET /schedules/describe/`; `frontend/rule-widget.js`.

## What it looks like

A fieldset of plain form controls:

- **Repeat:** "Doesn't repeat" (not for check-ins), daily, weekly,
  monthly, yearly; **every [N]** days, weeks, months or years (1 to 99).
- **Weekly:** seven toggles Monday to Sunday (checkboxes styled as
  buttons), at least one.
- **Monthly:** "on day [1–31]" (the 29th to 31st falling on the last day
  of shorter months), or "on the [first … fourth, last] [Monday … Sunday,
  working day]" ("working day" is Monday to Friday, `BYSETPOS`).
- **Yearly:** "on [month] [day]", 29 February falling on the 28th.
- **Ends** (to-dos only): "until" a date and "repeats left", the fields
  `recurrence_ends_on` and `recurrence_count` rendered inside the
  fieldset and shown only when a repeat is chosen.
- **The description** under it from `schedules.describe()` ("every 3
  weeks on Monday, Friday", "the last working day of every month"),
  updated through htmx, or the validation error.

A new rule starts from the anchor when the page is rendered (the due
date or today, the question's first date): weekly on its weekday,
monthly on its day, yearly on its date. JavaScript only shows the parts
for the frequency; without it all parts show and the server builds the
rule from the posted fields (`<field>_frequency`, `_interval`,
`_weekdays`, …; the inline forms of a list's groups differ only in ids).

## Rules it can't show

A rule is shown only if `build_rule(rule_fields(rule))` gives the same
string (rules are canonical, `todos.md`). Others (from the API, the CLI
or the importer, e.g. several monthly days, `WKST=SU`) show their
description and "This schedule was set elsewhere and can't be edited
here" with "Replace"; saving without pressing it keeps the rule. Never
silently rewritten: a misread rule saved back would change a schedule
without anyone noticing, so every rule the widget builds and every
preset has a round-trip test (`test_schedules.py`).
