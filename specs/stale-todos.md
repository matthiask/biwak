# Stale to-dos: warned, then marked obsolete

**Status:** open (specified 2026-11-26 with the user).

**Depends on:** `notifications.md` (events, who gets told, mails, the
weekly to-dos this replaces), `todos.md` (completing, recurrence),
`start-dates.md`, `quiet-hours.md`, `mail-sending.md`.

**Touches:** `biwak/items/` (marking obsolete, the completed rows, the
to-do's page, groups' form), `biwak/activity/` (`Event.actor`, the
warning mail, removing `weekly.py`), `biwak/palette/actions.py`,
`fairy_tasks`, the API and CLI, `docs/todos*.md` and
`docs/notifications*.md`, `notifications.md`.

## Why

Old to-dos pile up and get discovered by accident months later. Nobody
scrolls through their lists, and the weekly to-dos mail repeats the
to-dos page, so it doesn't help either. Instead, to-dos nobody touches
are marked obsolete, after a warning to the staff following them.
Whoever still wants one says so with a click or any comment ("I still
want to do this").

## Obsolete

A to-do is completed as **done** (as now) or marked **obsolete**
(decided 2026-11-26 with the user: "Obsolete", German "Hinfällig"; a
mark that's useful by hand too, not only for the automatic closing,
like GitHub's "Close as not planned").

- `Todo.obsolete` (a boolean next to `completed_at` and
  `completed_by`, which are set as when completing), an event
  `marked_obsolete` (`Action.MARKED_OBSOLETE`, instead of `completed`),
  telling as completing does. Reopening clears it (`reopen()`, the
  usual `reopened` event).
- **Whoever may complete it** may mark it obsolete: "Mark as
  obsolete" in the to-do's "More" menu (`items/_more.html`, no
  question: reopening undoes it) and in the palette, the API
  (`POST /api/v1/todos/{id}/obsolete/`, like `complete/`), the CLI
  (`biwak todos obsolete ID…`). The rows' checkbox stays "done".
- **Shown:** completed rows and the to-do's page show "Obsolete" (muted
  and struck through like done ones, with the word as a badge) and
  "Marked as obsolete by Ada on 3 March", or "Marked as obsolete after
  90 days without activity" when it happened automatically. The
  feed and the history: "Ada marked it as obsolete." No celebration
  (`celebrations.md`), not counted as done anywhere: Home, the feeds'
  filters, the agent skills' "done this week"
  (`cli/biwak_cli/skills/`), what the API's `completed` lists say
  (`obsolete: true` on every to-do).
- **Recurring** to-dos marked obsolete create no next one: the series
  ends (decided 2026-11-26).

## What is stale

An open to-do (not trashed, not a template, not in an archived list or
project) is stale when the latest of these is more than its group's
`stale_after` days ago (**90** by default, decided 2026-11-26):

- its **last activity**: its latest event except reactions, or its
  creation. Reactions don't count, as they don't for a project's
  activity (`_touch_project()` in `activity/operations.py`), so it's
  one rule for both;
- its **due date**: overdue to-dos count too (decided 2026-11-26: a
  comment is enough to keep one), from their due date;
- its **start date**: one starting later was put aside on purpose.

What that makes count, with the code as it is (decided 2026-11-26:
whatever needs no special cases): editing, ticking a box in its notes
(an edit, `tick()`), commenting (also by mail), assigning and
unassigning, moving to another group or list, completing and reopening,
"Keep open". Not counting: reactions, reordering within its group, and
ticking a box in a comment (neither records an event). To-dos added
from a text (`add_from_text()`) have no `created` event of their own:
their creation counts. Imported to-dos count from their imported
events, which have the original times.

One query a day (`fairy_tasks`), events by item and time: an index on
`Event(item, created_at)` if the plan needs one.

## Backlog groups

Some to-dos are kept on purpose: a board's "Backlog" or "Later" column,
a list of ideas. They shouldn't stay forever either (decided
2026-11-26: that's dead data too). A **group** keeps its to-dos longer:
`Group.stale_after`, days (`PositiveSmallIntegerField`, default 90),
set only to 90 or 365 (decided 2026-11-26: the model stores days, the
interface offers a switch, not arbitrary values). The group's form has
a checkbox "Keep untouched to-dos for a year" (`update_group()`,
`create_group()`), staff only; the API and CLI take the same two
values (`stale_after`, 400 for others; `biwak groups edit ID
--keep-for-a-year/--no-keep-for-a-year` by `specs/api-cli.md`'s rules).
Ungrouped to-dos: 90 days. Not on lists (a list of ideas gets a group),
no "never". The board's column header and the list's group heading show
nothing.

## Warning

`STALE_WARNING` days (**14**, decided 2026-11-26) before marking it
obsolete:

- **Staff only** (decided 2026-11-26: it's not the clients'
  responsibility): the to-do's subscribers who are own staff or
  externals and see it. Clients are neither warned nor told when it's
  marked obsolete.
- **A mail of its own** (decided 2026-11-26, not a section of the
  digest), whatever the delivery (each change or the daily digest);
  "No mails", inactive people and bounced addresses
  (`mail_undeliverable_at`) get none, as the weekly to-dos did. Not a
  notification in the lantern. Kind `stale` in the outbox, sent by
  `send_mails` from `DIGEST_AT` (07:00) or, with quiet hours, in the
  working time; skipped while away (the to-dos are marked obsolete all
  the same, the colleagues following them are told).
- **One mail per person and day**, plain text and HTML, in
  `language_for(recipient)`: subject "[Biwak] 12 to-dos will be marked
  as obsolete" (`ngettext`; decided 2026-11-26), heading the same with
  the date ("on 10 December"), by project and list, one row each (title
  linked, "Nothing since 3 May" or "Due 3 May", "Keep open" as a
  button), then "Comment on one or change it to keep it too." The
  settings link at the end, also as `List-Unsubscribe` (no one-click),
  like the digest.
- **Keeping:** "Keep open" in the mail (a signed link per to-do and
  person: `GET` asks, `POST` keeps, like `/unsubscribe/<token>/`), a
  banner on the to-do's page for staff while warned ("Nothing happened
  since 3 May. It will be marked as obsolete on 10 December." and
  "Keep open"), the palette, the API (`POST
  /api/v1/todos/{id}/keep/`) and the CLI (`biwak todos keep ID…`).
  Keeping records an event `kept` (`Action.KEPT`, in the feed and
  history, internal, telling nobody, in `notify.SILENT`) and starts the
  clock again; any other activity does too.
- `Todo.stale_warned_at`: set with the warning; activity after it
  clears it (the daily run). A to-do without staff subscribers is
  marked obsolete all the same, 14 days later.
- **At most 20 warnings per project and day**, the oldest first
  (decided 2026-11-26): the first run would warn about every old to-do
  at once. The steady state stays below it, so it's one rule rather
  than a mode for the first weeks; a project with 300 old to-dos drains
  in 15 days.

## Marking it obsolete automatically

`STALE_WARNING` days after the warning, still untouched, `fairy_tasks`
marks it obsolete. The event has **no actor**: `Event.actor` becomes
nullable, and every place reading it (the feed, the history, the
lantern, mails' `From`, the API's events) says "Biwak" for none — the
bigger change of this part. Its subscribers who are staff are told as
for any marking (mail per change, the digest, the lantern); the event
is internal (`record(internal=True)`), so clients see the to-do as
obsolete but aren't told.

`STALE_TODOS = True` in settings turns it on (off by default, also in
tests but those of this part). `./manage.py stale_todos` lists what is
stale now and what would be warned, counts per project, changing
nothing; run it in production before turning it on.

## The weekly to-dos go

Removed (decided 2026-11-26): it repeated the to-dos page.
`User.weekly_todos` and `weekly_todos_on` dropped (a migration),
`biwak/activity/weekly.py`, `templates/mails/weekly.*`, the outbox kind
(old rows keep theirs), the setting, the help; the API's `weekly_todos`
accepted and ignored on `PUT`, not returned; `biwak notifications
--weekly` removed (CLI version bump, `MINIMUM` unchanged: an older CLI
sending it still works). `notifications.md` loses its section and
gets a pointer here.

## Not in this part

Decided 2026-11-26 with the user: no "by last activity" view on the
to-dos page, no cleanup skill (people ask their agent to clean up
already), projects and lists are never archived or suggested for
archiving automatically.

## Done when

- Tests of the operations: marking obsolete (completed fields, the
  event, no next one of a recurring to-do, reopening clears it), as
  staff and as a client who may complete it; keeping.
- Tests of being stale: no activity, overdue, starting later, a
  reaction not counting, an edit, a comment and a move counting, a
  to-do added from text, a group kept for a year, archived lists and
  projects, templates and trashed ones left out.
- Tests of the daily run: warning once, at most 20 per project and day
  the oldest first, activity after the warning clearing it, marking
  obsolete after 14 days, nothing with `STALE_TODOS` off.
- Tests of the warning mail: one per person and day, staff and
  externals only, never clients, not for "No mails", inactive people,
  bounced addresses or people away, quiet hours, both languages; "Keep
  open" asking on `GET` and keeping on `POST`, a bad or foreign token.
- The event without an actor rendered in the feed, the history, the
  lantern, the digest and a mail per change; not told to clients.
- Pages: the "More" menu's item and the palette's action (rendered
  JSON), the banner, the completed rows; a client getting 404 for an
  internal to-do's keep link and API.
- The API (`obsolete/`, `keep/`, `obsolete` on to-dos, groups'
  `stale_after`) and the CLI commands (`biwak/test_cli.py`); the skills
  not counting obsolete to-dos as done (`biwak/test_skills.py`).
- The weekly to-dos gone: the API ignoring `weekly_todos`, the tests of
  `weekly.py` removed.
- The help (`docs/todos*.md`, `docs/notifications*.md`) and the German
  catalog.
