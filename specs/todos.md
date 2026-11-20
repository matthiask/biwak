# To-dos: assignees, recurrence, board view, by due date

Builds on `core.md` and `access.md`.

## Assignees

- Any number of people, staff and clients (clients only on visible
  to-dos).
- Completing a to-do completes it for all assignees; who completed it is
  recorded (decided 2026-11-20).
- Assigning subscribes the assignee and notifies them.

## Recurrence

- A rule (RRULE, `python-dateutil`): "every Monday", "first Monday of the
  month", "every 3 months", "the 15th of every quarter". A small set of
  presets in the interface plus a custom rule.
- When the to-do is completed, the next one is created in the same place
  with the same title, notes, assignees and subscribers, due on the next
  date of the rule after today (decided 2026-11-20). Never a stack of
  open copies.
- Comments and attachments stay with the completed to-do; the new one
  links to the previous one.
- Ending the recurrence: an end date, a count, or removing the rule.

## Board view

- A list can be shown as a board: its groups as columns, to-dos as cards,
  ungrouped to-dos in a first column (decided 2026-11-20: no separate
  boards, no deeper structure).
- Dragging a card to another column moves the to-do into that group, the
  same operation as in the list view.
- The view is a per-list setting (list or board), with a toggle for each
  person.

## Chronological list

Instead of a calendar: to-dos by due date, grouped into overdue, today,
this week, later and no date.

- Per project and across all projects; "my to-dos" is the same list
  filtered by assignee.
- Filters: project, assignee, list, completed or not, visible to clients.
- An iCal feed per person of their to-dos' due dates (a secret URL,
  revocable).

## Tests

Recurrence across month ends, leap years and time zones; completing the
last occurrence; moves between groups in board and list view giving the
same result.
