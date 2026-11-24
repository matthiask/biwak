# To-dos: assignees, recurrence, board view, by due date

**Status:** built (2026-11-20; the to-do's page, the picker, the
groupings and "assigned by" 2026-11-21; filters on a list 2026-11-24).

## Assignees

- **No "When done, notify…"** (decided 2026-11-22): the people who'd
  be named are subscribed anyway and hear about the completion with
  the rest of the thread.

- Any number, everybody who can see the to-do: staff (in all-access
  projects every staff member), clients only on visible to-dos.
  Assigning somebody who isn't a member makes them a member, recorded as
  added (`add_member()`, decided 2026-11-21). One rule in
  `ops.assignable_people()` for the forms (members first), the API and
  the next to-do of a recurring one (which leaves out people removed from
  the project, inactive or no longer seeing it). Completing completes for
  everybody and records who did it; assigning subscribes the assignee
  (notifying them is `notifications.md`).
- **Removed people are dropped** (decided 2026-11-21: "the removal will
  be visible in the history"): removing somebody from a project
  (`remove_member()`, withdrawing an invitation too) takes them off its
  open to-dos, trashed ones included, through `unassign()`
  (`ops.unassign_dropped()`): an "unassigned" event per to-do by whoever
  removed them, nobody told. Completed to-dos keep them: they're history
  (confirmed by the user 2026-11-21: "historical information and
  accurate"), so a sweep doesn't fill the feed with old to-dos.
  **Deactivating keeps them** (decided 2026-11-22, `handover.md`): an
  assignment documents who did or was to do the work; inactive people
  show as such and their to-dos are handed over with "Assign…".
- **The edit form** offers who's still assigned but can't be assigned
  anymore, without dropping them automatically (confirmed 2026-11-21:
  a client on a to-do made internal, `ops.assignable_or_assigned()`),
  so saving never drops anybody silently; taking them out unassigns them.
- **Who assigned** (decided 2026-11-21): `Todo.assignees` goes through
  `Assignment` (todo, user, `assigned_by` nullable, `assigned_at`; the
  old table name `items_todo_assignees`, audited). `assign()` records its
  actor, or `assigned_by={user pk: assigner}`; the next recurring to-do
  keeps each assignment's assigner, the importer leaves it empty
  (Basecamp doesn't say).
- **The picker** (`frontend/people-picker.js`, `PeopleField`, also for
  subscribers and whom to notify): pills with
  ×, a field that opens the list on a click, typing or Down (not on focus
  alone, decided 2026-11-21) and filters while typing
  (Up/Down, Enter, Escape, Backspace removes the last pill; decided
  2026-11-22: Left at the field's start or Home in an empty one reaches
  the pills, Left/Right/Home/End move between them, Delete and Backspace
  remove the focused one and focus a neighbour, Right past the last and
  typing return to the field; one Tab stop, × for the mouse; the order
  isn't kept); non-members
  say "not in the project yet". The list floats over what's below, so it
  closes after a pick (typing or Down opens it again), when nobody is
  left to pick, when the field loses the focus (Tab, a click elsewhere)
  and on a click elsewhere (`data-dismiss`; decided 2026-11-21: the
  empty list stayed over the button below). Without JavaScript the `<select
  multiple>`. Used in the inline form and the to-do's edit form. Staff
  find teams in it, which pick their members (`teams.md`).

## Lists and the board

- **Groups are cards** (decided 2026-11-23, `ui.md`, "Cards"): each
  group a card with its heading inside, below each other in the list
  view, side by side on the board; the to-dos outside groups a card
  first, shown without the card (only "Add a to-do") while there are
  none.
- **Board view:** a list's groups as columns, ungrouped to-dos in a
  first column shown only when there are any; a per-list setting (list
  or board) with `?view=` to switch; dragging between columns is
  `move_todos()`. Columns that don't fit the page widen the board up
  to the window's width (`ui.md`, "Page width", decided 2026-11-23). The board never shows completed to-dos in its columns.
- **Filters on a list** (decided 2026-11-24 by the user: "filter by
  assignee", copied from the to-dos page): the list and the board filter
  by "assigned to" only (`?assignee=`: anybody, the default, me, nobody
  active and, for staff, the people with to-dos in the list, open or
  completed, not trashed (decided 2026-11-24 by the user: "only people
  which actually have assignments"; first the project's members),
  inactive people last; `ListFilterForm` and
  `assignee_choices()` in `biwak/items/filters.py`, the query through
  `due.assigned_to()`). Unknown values show an error and no to-dos. A
  "Filters" menu in the header, applying itself, with the count set
  (`items/_list_filters.html`). **It opens on hover** (decided 2026-11-24
  by the user, after trying a row always there for a few hours: "the
  additional click to open it is slightly annoying", the row "much
  uglier"): resting the mouse on the button 50 ms opens it, leaving
  closes it after 300 ms (confirmed 2026-11-24) unless the select has the focus, a click right
  after keeps it open; touch screens tap as before (`data-hover-open`,
  `frontend/menus.js`). A line below the header says what is set
  ("Assigned to: Ada") with "Reset filters", so to-dos left out aren't
  taken for gone; "No to-dos match the filter." when nothing does. Not
  remembered (confirmed by the user 2026-11-24: a plain link to a list
  shows all of it). **Groups and columns stay** while filtered (the board's column of
  to-dos outside groups too while the list has any, matching or not,
  else the board lost its window width, 2026-11-24) and **Completed
  is filtered too**, its count, "Show more" and its fragment (decided
  2026-11-24 by the user). The view links, "Show more" and completing a
  to-do (`next`) keep the view and the filter. **Dragging places by the
  neighbour shown** (decided 2026-11-24 by the user): `todos.js` sends
  the to-do shown above the dropped ones (`after`) or, at the top, the
  one below (`before`) besides the index, and `move_todos()` puts them
  right next to it when it's still there, else at the index; to-dos left
  out by the filter keep their places. Adding inline while filtered
  shows the new to-do even when it doesn't match, until the next reload
  (confirmed by the user 2026-11-24). API: `assignee` on
  `lists/{id}/todos/` and `…/completed/`; CLI: `--mine` and `--assignee`
  with `--list` (0.73.0).
- **Adding inline:** "Add a to-do" opens a form in place (title, notes,
  assignees, due date, repeat); Ctrl+Enter adds and starts the next one,
  Escape or a click elsewhere closes (`frontend/add-todo.js`). "Add a
  to-do" and "New group" sit side by side under the last group.
- **Rows** (`items/_todo.html`, the same everywhere): a grid of handle,
  checkbox and content; the title wraps in the content column, then a
  line with assignees, the due badge and the signals (`glance.md`,
  checklist counts from `editor.md`).
- **Completed to-dos** (decided 2026-11-20, for lists used for years;
  shown at once since 2026-11-23, the user: "Basecamp shows the last few
  completed to dos and allows loading more. That's more useful than the
  collapsible we have now."): below the list or board, under the heading
  "Completed (142)" (a `COUNT` query, trashed ones not counted), the
  latest few in a card, newest first, and "Show more" adding the next
  (`COMPLETED_FIRST` and `COMPLETED_MORE` in `biwak/items/views.py`,
  5 and 25, confirmed by the user 2026-11-23) until none
  are left. "Show more" is a link to the list's page showing that many
  (`?completed=30`, the view kept; nonsense or fewer is the default),
  the way without JavaScript; htmx loads only the next ones
  (`/lists/<pk>/completed/?before=<completed_at ISO>,<pk>&shown=N`, an
  HTML fragment; a malformed cursor is a 404) and puts the page's
  address in the bar (`hx-replace-url`), so reloading and live updates
  (which fetch the page's address) keep what was loaded. The API
  (`lists/{id}/todos/completed/`) has its cursor.

## The to-do's page

- **View mode** (decided 2026-11-21): the title as the heading, then one
  card with the facts (assigned to, due on, repeats: "Nobody", "No
  date", "Doesn't repeat" when empty; the overdue or "Today" badge next
  to the date; last "Created 3 Dec 2026 by Ada", the person through
  `{% person_page %}`, not editable, decided 2026-11-22; a moment, so
  "Created 2 hours ago by Ada" within seven days, `ui.md`). Start and
  due dates in the same short format as the created date ("3 Dec
  2026", the weekday on hover, decided 2026-11-22: one format in one
  card) and, below a divider, the notes ("Add notes…" when
  empty; checklists tickable). Reactions and the timeline (`timeline.md`)
  below the card. Clicking the facts or the notes edits in place
  (`ui.md`, "Click to edit"; `/todos/<id>/edit/`).
- **Overdue** (decided 2026-11-21): an open to-do due before today shows
  a danger badge "Overdue · 18. Nov", due today a neutral "Today"; later
  dates stay plain, completed to-dos are never overdue. `{% due_badge %}`
  (`items/_due_badge.html`, `items.due.badge_state()`) wherever a to-do
  shows its date: rows, the to-dos page, the to-do's page, bookmarks in
  the palette. `.wb-tone-danger` is a palette token checked for contrast.

## Recurring to-dos

### Schedules

`biwak/schedules/__init__.py`, also used by check-ins:

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
  and group, at the end, with the same title, notes, assignees and
  subscribers. **The rule moves** to it with its end date and count
  (decided 2026-11-23 by the user, as Basecamp does): the completed one
  keeps none, so changing an old to-do's due date never touches the
  schedule; a rule used up (no next one) stays where it is. Migration
  `items/0021_recurrence_moves` cleared the rule of completed to-dos
  which had a next one. The next one is due on the rule's next date after today, or
  after the due date when completed early (decided 2026-11-20: a weekly
  to-do due Friday and done on Wednesday is next due the Friday after).
  Never a stack of open copies. A start date keeps its distance to the
  due date (`start-dates.md`). In `complete()`'s transaction, created
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
- **Filters** (GET, applying themselves and remembered, `ui.md`):
  project, assigned to (across projects the empty choice is "Me", since
  everybody's open to-dos get huge, and "Anybody" is
  `assignee=anybody`; in a project the default is anybody's; "Nobody
  active" is nobody or only deactivated people), assigned by (anybody or
  me: to anybody else, Basecamp's "assigned by me"; decided 2026-11-22: a
  to-do I assigned to myself and Bob counts, Bob being another, one only
  to myself doesn't; Home's "waiting on others" also leaves out to-dos
  I'm assigned to, so they aren't listed twice on Home; with an assignee
  chosen, to them, "Me" being those I gave myself; decided 2026-11-22:
  with "assigned by me" the empty assignee is "Anybody" across projects
  too, else it would show only those I gave myself), open or
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
- **Completing says what it does** (decided 2026-11-22): the rows, the
  to-do's page, the palette and Shift+x post `done=1` (Complete) or `done=0`
  (Reopen) to `/todos/<id>/toggle/`; a to-do already so stays as it is,
  so a page from before someone else completed it never reopens it. The
  API has `complete/` and `reopen/`.
- **From the project page:** "All to-dos: by list · by due date" below
  the lists' heading, each keeping its own query; the header's "All
  to-dos" restores the remembered filters.
- **API:** `GET /api/v1/todos/` with `project_id`, `assignee` (`me`,
  `anybody`, `nobody`, an ID), `assigned_by=me` (else 400; to anybody
  else without an assignee, like the page), `completed`,
  `visible_to_clients` (ignored for clients), `due_group`, `grouping`
  and the cursor; each to-do carries `due_group` (`overdue`, `today`,
  `this_week`, `next_week`, `later`, `none`; months are only headings),
  its project, list and group with positions, and each assignee's
  `assigned_by`. **CLI:** `biwak todos --mine|--assignee
  PERSON|--assigned-by-me|--project ID|--due GROUP|--by-due|--completed`
  (`--assignee` since 0.63.0, for handing over, `agent-skills.md`), by project unless `--by-due`,
  the first 200.

## The calendar feed

- Per person, their assigned open to-dos with a due date as all-day
  events (from the start date, `start-dates.md`) at `/calendar/<token>.ics` (`icalendar`): title, link, "project
  / list" as the description, no notes (the URL travels through
  calendar servers), `UID` `todo-ID@biwak`, not busy.
- The token is secret (`CalendarToken`, not in the audit log), shown on
  `/accounts/calendar/` with "Copy" and "Make a new link" (POST; the old
  one stops working). No login for the feed; it shows only what the
  person can see now; inactive people's feeds are empty. "Calendar" is in
  the person's menu.
