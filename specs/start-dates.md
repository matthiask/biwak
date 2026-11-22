# Start dates on to-dos

An optional start date: a to-do that can't start yet stays out of
current work until it can. Decided with the user 2026-11-22.

**Status:** built 2026-11-22 (branch `start-dates`): `Todo.starts_on`
(there since the first migration), `check_dates()` in
`items/operations.py`, `due.started()` and `due.starting_later()`,
`items/_starting_later.html`, `biwak.formats.format_range()`,
`frontend/start-date.js`.

Depends on: `todos.md` (due dates, the to-dos page, the calendar feed,
recurrence), `dashboard.md` (Home), `glance.md` (rows), `editor.md`,
`import-basecamp.md`, `api-cli.md`.

- **`Todo.starts_on`**, only together with a due date and not after it
  (validated in the operation, the form, the API: "A start date needs a
  due date.", "The start date can't be after the due date."). Removing
  the due date removes the start date, as removing a rule removes its
  ends; moving the due date before the start is refused. Set next to the
  due date (the same date field, "Starts" shown after "Due" is set; the
  field also shows while it has a date, so an error can be read; `max`
  is the due date). The to-do's page shows "Starts on" as a fact of its
  own when set, mails a "Starts on" line.
- **Rows** show the range ("3–7 Dec"; across months "28 Nov – 3 Dec";
  in German "3.–7. Dez.") where they show the due date, the overdue
  badge too ("Overdue · 20–24 Nov"); overdue as now by the due date,
  "Today" alone on the due date.
- **Hidden until they start** (decided 2026-11-22): before its start
  date a to-do isn't in "My to-dos", the to-dos page's default view and
  Home's current work; those show a collapsed "Starting later (3)"
  part at the end. Lists, the board and search show it as always.
  "Today" is the installation's (one time zone, `quiet-hours.md`).
  On the to-dos page that's the open to-dos in either grouping (not
  "Completed"), flat, the next to start first, each row with its project
  and list; on Home the part closes "Due" and holds my to-dos which
  would be there (due within the 7 days) but haven't started. "Waiting
  on others" and the API's `GET /todos/` are unchanged.
- **The calendar feed** shows the range as an all-day event from start
  to due date.
- **Recurrence:** the next to-do keeps the distance between start and
  due date.
- **Changing it** records an event like the due date: the edit lists
  `starts_on`, the data carries both dates and what they were; the
  timeline says "changed the dates to 3–7 Dec 2026" once a start date is
  or was involved, else as before. Notifications as for due dates.
- **API and CLI:** `starts_on` next to `due_on`; `biwak todo … --starts
  DATE` (`none` removes it; CLI 0.46.0), tables show "start – due".
  **Importer:** Basecamp's `starts_on`; one without a due date or after
  it isn't brought.
- Copying a list (`lists-across-projects.md`) shifts start dates with
  due dates.
