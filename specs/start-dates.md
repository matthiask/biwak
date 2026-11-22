# Start dates on to-dos

An optional start date: a to-do that can't start yet stays out of
current work until it can. Decided with the user 2026-11-22.

**Status:** open.

Depends on: `todos.md` (due dates, the to-dos page, the calendar feed,
recurrence), `dashboard.md` (Home), `glance.md` (rows), `editor.md`,
`import-basecamp.md`, `api-cli.md`.

- **`Todo.starts_on`**, only together with a due date and not after it
  (validated in the operation, the form, the API). Set next to the due
  date (the same date field, "Starts" shown after "Due" is set).
- **Rows** show the range ("3–7 Dec"; across months "28 Nov – 3 Dec")
  where they show the due date; overdue as now by the due date.
- **Hidden until they start** (decided 2026-11-22): before its start
  date a to-do isn't in "My to-dos", the to-dos page's default view and
  Home's current work; those show a collapsed "Starting later (3)"
  part at the end. Lists, the board and search show it as always.
  "Today" is in the person's time zone (`quiet-hours.md`), else the
  installation's.
- **The calendar feed** shows the range as an all-day event from start
  to due date.
- **Recurrence:** the next to-do keeps the distance between start and
  due date.
- **Changing it** records an event like the due date ("changed the
  dates"); notifications as for due dates.
- **API and CLI:** `starts_on` next to `due_on`; `biwak todo … --starts
  DATE`. **Importer:** Basecamp's `starts_on` (spec: no longer "Not
  imported").
- Copying a list (`lists-across-projects.md`) shifts start dates with
  due dates.

## Done when

- A to-do gets a start date only with a due date, not after it,
  through the form, the inline form, the API and the CLI.
- Rows and the calendar feed show the range; before the start the
  to-do is in "Starting later" on My to-dos, the to-dos page and Home,
  as staff and as a client.
- Recurrence keeps the distance; the importer brings start dates.
- Help and the German catalog updated.
