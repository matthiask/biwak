# Decisions to confirm

Decisions made without asking first, for the user to go through. Each is
built and written into its spec; once confirmed (or changed), delete the
entry; git keeps it.

## Start dates (`start-dates.md`, 2026-11-22)

- **Removing the due date removes the start date** (API `due_on: null`,
  the CLI's `--due none`), like removing a rule removes its ends; giving
  a start date with no due date, or moving the due date before the
  start, is refused with "A start date needs a due date." / "The start
  date can't be after the due date.".
- **"Starting later" on the to-dos page:** for open to-dos in both
  groupings, one flat list by start date (rows with project and list),
  not grouped like the page. On Home only my to-dos that would be in
  "Due" (due within 7 days); one starting tomorrow and due in a month
  isn't on Home at all, as before.
- **The inline form** labels the start field with the visible word
  "Starts" (the due field keeps its icon); the edit form says "Starts
  on" after "Due on". The to-do's page has a separate "Starts on" fact
  (only when set) rather than a range in "Due on"; mails a "Starts on"
  line after "Due on".
- **The timeline** says "changed the dates to 3–7 Dec 2026" whenever a
  start date is or was involved (also when only the due date moved),
  "set the due date to …" without one.
- **The overdue badge** shows the range ("Overdue · 20–24 Nov").
- **Importer:** a Basecamp start date without a due date or after it is
  dropped silently, not reported.
- **German:** "Beginnt am" / "Beginnt", "Beginnt später (N)", "hat die
  Daten auf … geändert", "Ein Startdatum braucht eine Fälligkeit.", "Das
  Startdatum kann nicht nach der Fälligkeit liegen."
