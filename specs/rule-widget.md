# The rule widget

One control for repeat rules, wherever they are edited: to-dos (the
inline form adding them and the to-do's page) and check-in questions.
It replaces the preset dropdown and the text field for a raw RRULE
(decided 2026-11-20: widget only, no raw RRULE in the forms, the
description instead of a preview of dates).

**Status:** built (2026-11-20): `rule_fields()`, `build_rule()` and
`default_fields()` in `biwak/schedules.py`; `RuleField` and `RuleWidget`
in `biwak/schedules_forms.py` with `forms/rule_widget.html`, the
`{% rule_widget %}` tag for the inline forms and `GET
/schedules/describe/`; `frontend/rule-widget.js`; tests in
`test_schedules.py` (round trips of every rule the widget builds and of
every preset), `test_schedules_forms.py`, the pages' tests and
`RuleWidgetTest` in `test_e2e.py`. Decisions made on the way:

- Posted names are `<field>_frequency`, `_interval`, `_weekdays`,
  `_monthly`, `_month_day`, `_ordinal`, `_weekday`, `_year_month`,
  `_year_day`, plus `_keep` and `_replace` for rules set elsewhere. The
  inline forms of a list's groups are separate `<form>`s, so they share
  names and differ only in ids (`id_recurrence_<group>_…`).
- A rule is shown only if `build_rule(rule_fields(rule))` is the same rule;
  so `FREQ=WEEKLY` without `BYDAY` or `WKST=SU` are "set elsewhere".
  Since rules are stored in canonical form (decided 2026-11-21,
  `todos.md`), the same means the same string: `BYDAY=TH,MO` from the
  API is stored as `BYDAY=MO,TH`, which the widget shows, and saving an
  unchanged form compares plain strings (it compared normalized parts
  before).
- The end date and count stay separate form fields right after the
  fieldset, not inside it; the inline form hides them without a
  frequency.
- `describe()` says "working day" (not "weekday") for Monday to Friday in
  the monthly rules and handles intervals and weekday sets of the widget
  ("every 3 weeks on Monday, Friday"); "every other Monday" stays.
- The defaults come from the anchor when the page is rendered (today on
  the inline form, the due date on the to-do's page, the question's first
  date); they don't follow a due date changed meanwhile.
- `preset_for()` and `preset_choices()` are gone; `PRESETS`, `from_preset`
  and `preset_of` stay for the API and CLI.

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`. Have the rule round trips reviewed: a rule the widget
misreads and saves back changes a schedule without anyone noticing.

**Depends on:** recurring to-dos (`todos.md`) and check-ins
(`checkins.md`), both built. Independent of `collaboration.md`.

**Touches:** `biwak/schedules.py` (reading and building rules), a form
field and widget (`biwak/forms.py` or `biwak/schedules_forms.py`),
`items/_add_todo.html`, `items/todo.html`, `checkins/question_form.html`,
the to-do and question forms in `biwak/items/views.py` and
`biwak/checkins/views.py`, a small `frontend/rule-widget.js`, CSS. Not
the API or the CLI.

## What it looks like

A fieldset, server-rendered, plain form controls:

- **Repeat:** "Doesn't repeat", "Daily", "Weekly", "Monthly", "Yearly".
  Check-ins always repeat: no "Doesn't repeat" there.
- **Every [N] days / weeks / months / years**: a number, 1 to 99.
- **Weekly:** seven toggle buttons, Monday to Sunday (the week starts on
  Monday, the installation's convention); at least one. "Every weekday"
  is Monday to Friday selected.
- **Monthly**, one of:
  - "on day [1–31]", where the 29th to 31st fall on the last day of
    shorter months, as today (`BYMONTHDAY=28,29,30,31;BYSETPOS=-1` for
    the 31st, and so on);
  - "on the [first, second, third, fourth, last] [Monday … Sunday,
    working day]", where "working day" is Monday to Friday
    (`BYDAY=MO,TU,WE,TH,FR;BYSETPOS=…`).
- **Yearly:** "on [month] [day]", the 29th of February falling on the
  28th in other years, as today.
- **Ends** (to-dos only, as today): "never", "on [date]" or "after [N]
  to-dos". The existing fields (`recurrence_ends_on`,
  `recurrence_count`) inside the fieldset.
- **The description** under it, from `schedules.describe()` ("every
  second Monday", "the last working day of every month"), updated on
  change through htmx (`GET /schedules/describe/?…` with the widget's
  fields, answering the text or the validation error). No dates
  previewed.

Opening the widget for a new rule starts from the anchor (the to-do's
due date or today, the question's first date): weekly on its weekday,
monthly on its day, yearly on its date. Switching the frequency keeps
the anchor-based default for the new one.

JavaScript only shows the parts for the chosen frequency and asks for
the description (`frontend/rule-widget.js`, loaded from `main.js`).
Without it, all parts show and the form still saves: the server builds
the rule from the posted fields.

## Rules and fields

Two functions in `biwak/schedules.py`, the only place that knows RRULE
syntax:

- `rule_fields(rule)`: the widget's fields for a rule, or `None` if the
  widget can't show it.
- `build_rule(fields)`: the normalized rule for the fields (raising
  `InvalidRule` with a message per field).

For every rule the widget can show, `build_rule(rule_fields(rule))` is
the rule itself, normalized; tested for every preset, every frequency,
interval, weekday set, monthly variant and yearly date. The rules are
explicit (`BYDAY`, `BYMONTHDAY`, `BYMONTH`), so the stored rule no
longer depends on the due date or first date, except for the phase of
intervals above 1 (`anchor=`, as today).

**Rules the widget can't show** (from the API, the CLI or the
importer, e.g. several monthly days): the fieldset shows the
description and "This schedule was set elsewhere and can't be edited
here", with a button "Replace" that opens the widget empty. Saving the
form without pressing it keeps the rule unchanged. Never silently
rewritten.

The API and the CLI stay as they are: RRULEs and the preset names
(`--repeat weekly`). The preset table stays for them; the forms no
longer use it (`preset_for()` goes away with its last caller).

## Forms

- A form field (`RuleField`, a `MultiValueField` with its widget) used
  by the to-do forms and the question form. It cleans to the rule or
  `""`, and to "unchanged" for rules the widget can't show.
- The posted names don't clash on the list page, where several inline
  forms exist (one per group): prefixed like the other fields there.
- Labels, a `legend`, keyboard use for the weekday toggles (they're
  checkboxes styled as buttons), and phone widths (the parts wrap).

## Done when

- The widget on the inline to-do form, the to-do's page and the question
  form, as staff and as a client who may edit the to-do.
- Round-trip tests for every rule the widget can build, the presets
  included. A test that rules it can't show survive saving unchanged.
  The validation messages per field.
- Saving without JavaScript (posting the fields) and with it.
- Playwright: choosing each frequency shows the right parts; the
  description follows; saving a "second Tuesday every month" to-do and
  completing it creates the next one on the right date.
- The API and CLI tests unchanged and passing.

## Questions before building

- The labels' wording; the defaults are proposed above.
