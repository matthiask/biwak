# To-dos: assignees, recurrence, board view, by due date

Builds on `core.md` and `access.md`.

**Status:** built (2026-11-20; the to-do's page, the picker, the
groupings and "assigned by" from the UI rounds, 2026-11-21).

## Assignees

- Any number, everybody who can see the to-do: staff (in all-access
  projects every staff member), clients only on visible to-dos.
  Assigning somebody who isn't a member makes them a member, recorded as
  added (`add_member()`, decided 2026-11-21). One rule in
  `ops.assignable_people()` for the forms (members first), the API and
  the next to-do of a recurring one (which leaves out people removed from
  the project, inactive or no longer seeing it). Completing completes for
  everybody and records who did it; assigning subscribes the assignee
  (notifying them is `notifications.md`).
- **Who assigned** (decided 2026-11-21): `Todo.assignees` goes through
  `Assignment` (todo, user, `assigned_by` nullable, `assigned_at`; the
  old table name `items_todo_assignees`, audited). `assign()` records its
  actor, or `assigned_by={user pk: assigner}`; the next recurring to-do
  keeps each assignment's assigner, the importer leaves it empty
  (Basecamp doesn't say).
- **The picker** (`frontend/people-picker.js`, `PeopleField`, also for
  subscribers and whom to notify): pills with
  ×, a field that opens the list on focus and filters while typing
  (Up/Down, Enter, Escape, Backspace removes the last pill); non-members
  say "not in the project yet". Without JavaScript the `<select
  multiple>`. Used in the inline form and the to-do's edit form.

## Lists and the board

- **Board view:** a list's groups as columns, ungrouped to-dos in a
  first column shown only when there are any; a per-list setting (list
  or board) with `?view=` to switch; dragging between columns is
  `move_todos()`. The board never shows completed to-dos in its columns.
- **Adding inline:** "Add a to-do" opens a form in place (title, notes,
  assignees, due date, repeat); Ctrl+Enter adds and starts the next one,
  Escape or a click elsewhere closes (`frontend/add-todo.js`). "Add a
  to-do" and "New group" sit side by side under the last group.
- **Rows** (`items/_todo.html`, the same everywhere): a grid of handle,
  checkbox and content; the title wraps in the content column, then a
  line with assignees, the due badge and the signals (`glance.md`,
  checklist counts from `editor.md`).
- **Completed to-dos** (decided 2026-11-20, for lists used for years):
  below the list or board, collapsed, "Completed (142)" (a `COUNT` query,
  trashed ones not counted); opening shows the latest 20, "Show more" the
  next 50 (`/lists/<pk>/completed/?before=<completed_at ISO>,<pk>`, an
  HTML fragment; a malformed cursor is a 404). The API
  (`lists/{id}/todos/completed/`) has its cursor.

## The to-do's page

- **View mode** (decided 2026-11-21): the title as the heading, then one
  card with the facts (assigned to, due on, repeats: "Nobody", "No
  date", "Doesn't repeat" when empty; the overdue or "Today" badge next
  to the date) and, below a divider, the notes ("Add notes…" when
  empty; checklists tickable). Reactions and the timeline (`timeline.md`)
  below the card. Clicking the facts or the notes edits in place
  (`core.md`, "Click to edit"; `/todos/<id>/edit/`).
- **Overdue** (decided 2026-11-21): an open to-do due before today shows
  a danger badge "Overdue · 18. Nov", due today a neutral "Today"; later
  dates stay plain, completed to-dos are never overdue. `{% due_badge %}`
  (`items/_due_badge.html`, `items.due.badge_state()`) wherever a to-do
  shows its date: rows, the to-dos page, the to-do's page, bookmarks in
  the palette. `.wb-tone-danger` is a palette token checked for contrast.

## Recurring to-dos

### Schedules

`biwak/schedules.py`, also used by check-ins:

- A rule is an RRULE string (`python-dateutil`), validated on save:
  `INTERVAL` 1 to 99, no day 0 in `BYMONTHDAY` or `BYSETPOS`, at least
  two dates, nothing shorter than daily, no `DTSTART`, `COUNT` or
  `UNTIL`. A stored rule which isn't valid gives no date, never an error
  or a hang (`INTERVAL=0` made dateutil loop forever).
- **Canonical form** (decided 2026-11-21): `validate()` normalizes what
  the API, the CLI or the importer send (`FREQ`, `INTERVAL`, `BYMONTH`,
  `BYDAY`, `BYMONTHDAY`, `BYSETPOS`, `WKST`; days in week order, numbers
  ascending, repeats dropped, `INTERVAL=1` and `WKST=MO` dropped;
  dateutil's `MO(+1)` refused), so equal schedules are equal strings.
- `next_date(rule, after, tz, anchor=)`: the next date after a date in
  the installation's time zone; `anchor` keeps the phase of "every two
  weeks". `describe(rule)`: "every Monday", "the last working day of
  every month".
- The 29th to 31st and 29 February fall on the last day of shorter
  months instead of skipping them (`BYMONTHDAY=28,29,30,31;BYSETPOS=-1`).
- Forms use the rule widget (`rule-widget.md`); the API and the CLI take
  an RRULE or a preset name (`PRESETS`, counted from the due date sent or
  stored, today without one; "every week" is that date's weekday).

### Completing

- `Todo.recurrence` (empty for none), `recurrence_ends_on`,
  `recurrence_count` (how many more after this one: 2 makes two more, the
  last has 0), `previous`.
- **Completing** a recurring to-do creates the next one in the same list
  and group, at the end, with the same title, notes, assignees,
  subscribers and rule, due on the rule's next date after today, or
  after the due date when completed early (decided 2026-11-20: a weekly
  to-do due Friday and done on Wednesday is next due the Friday after).
  Never a stack of open copies. In `complete()`'s transaction, created
  by the original creator with its own `created` event by whoever
  completed it.
- **One series:** completing a to-do that already has a next one (not
  in the trash) creates none, so reopening and completing again never
  branches. Reopening doesn't remove the next one.
- Comments and attachments stay with the completed to-do; the new one
  links to it ("Previous: completed on 3 March by Ada").
- **Ending:** an end date, a count, or removing the rule (which removes
  both ends). No next one in an archived list.
- **API:** `recurrence` (preset or RRULE; `null` or `""` removes it),
  `recurrence_description`, `recurrence_ends_on`, `recurrence_count`,
  `previous_id` on `TodoOut`. `previous_id` is hidden when the to-do is
  visible to clients and the previous one isn't (moved since), for staff
  too. The CLI has `--repeat RULE` only.

## The to-dos page

Instead of a calendar. `/todos/` across all projects the person can
see, `/projects/<pk>/todos/` per project; "To-dos" in the top bar.

- **The title follows the filters:** "My to-dos" (assigned to me),
  "To-dos I assigned" (by me, to anybody else), else "To-dos".
- **Filters** (GET, applying themselves and remembered, `core.md`):
  project, assigned to (across projects the empty choice is "Me", since
  everybody's open to-dos get huge, and "Anybody" is
  `assignee=anybody`; in a project the default is anybody's; "Nobody
  active" is nobody or only deactivated people), assigned by (anybody or
  me: with "Anybody" it's Basecamp's "assigned by me"), open or
  completed (latest first, 50 per page), visible to clients (staff
  only). Assignee choices list people only for staff; clients get
  anybody, me and nobody. Unknown values show an error and no to-dos,
  never a silent "everything". No list filter (decided 2026-11-21: a
  list's page shows one list). "Assigned to me" in the header when
  someone else is chosen.
- **Group by** (`?grouping=`, decided 2026-11-21):
  - **project** (the default): projects by name with their color, lists
    and groups in their own order, to-dos outside groups first, empty
    ones left out; on a project's page by list and group;
  - **due date:** overdue, today, this week (until Sunday, in the
    installation's time zone), next week (Monday to Sunday), one section
    per month ("December", "January 2027"), no date
    (`items.due.sections()`; Home uses the same).
  Completed to-dos are never grouped.
- **Left out:** trashed to-dos, archived projects and archived lists
  (also in the API and the calendar feed).
- Rows complete in place (the list's toggle, `next` back to the page).
- **From the project page:** "All to-dos: by list · by due date" below
  the lists' heading, each keeping its own query; the header's "All
  to-dos" restores the remembered filters.
- **API:** `GET /api/v1/todos/` with `project_id`, `assignee` (`me`,
  `anybody`, `nobody`, an ID), `assigned_by=me` (else 400), `completed`,
  `visible_to_clients` (ignored for clients), `due_group`, `grouping`
  and the cursor; each to-do carries `due_group` (`overdue`, `today`,
  `this_week`, `next_week`, `later`, `none`; months are only headings),
  its project, list and group with positions, and each assignee's
  `assigned_by`. **CLI:** `biwak todos --mine|--assigned-by-me|--project
  ID|--due GROUP|--by-due|--completed`, by project unless `--by-due`,
  the first 200.

## The calendar feed

- Per person, their assigned open to-dos with a due date as all-day
  events at `/calendar/<token>.ics` (`icalendar`): title, link, "project
  / list" as the description, no notes (the URL travels through
  calendar servers), `UID` `todo-ID@biwak`, not busy.
- The token is secret (`CalendarToken`, not in the audit log), shown on
  `/accounts/calendar/` with "Copy" and "Make a new link" (POST; the old
  one stops working). No login for the feed; it shows only what the
  person can see now; inactive people's feeds are empty. "Calendar" is in
  the person's menu.
