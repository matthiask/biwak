# Archiving

Putting finished things out of the way without deleting them. Decided
2026-11-21: **projects and lists** can be archived, nothing smaller.
To-dos are completed, not archived; long runs of completed to-dos are
already collapsed ("Completed (N)", `todos.md` stage 3).

**Status:** built (2026-11-21). Lists: "Archive"/"Unarchive" in the list's
"More" menu, in a menu on each list row of the project page (the rows are
a `div` with the link inside) and as a palette action (all with
`ops.can_change()`: staff, and clients for lists they created, as the edit
page's button always was); archived lists are out of the project's lists,
"my to-dos", the by-due list and calendar feed, and last and marked in the
palette; recurring to-dos in them create no next one; the events notify
nobody (`notify.SILENT`). Smaller items: `ops.archive()` refuses anything
but lists (the one place; `Status` keeps the value) and migration
`items/0011` converts old ones (archived to-dos completed at their
`updated_at`, no "completed by"; items trashed while archived the same).
Importer: archived to-dos completed at the recording's `updated_at` by the
importing person (the API names neither the time nor the person of the
archiving), archived messages, docs, files and questions found through the
recordings listing (`status=archived`, per type and project), skipped and
listed in the report. API (`PATCH lists/{id}/ {"archived": ...}`, `GET
projects/{id}/lists/?archived=true`) existed; CLI 0.32.0 adds `biwak list
archive|unarchive LIST` and `biwak lists --archived`.

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`.

**Depends on:** the core, the importer.

## What exists

- **Projects:** `Project.archived_at`; archived projects are left out of
  the projects page (an "Archive" page lists them), the feed across
  projects, "my to-dos" and the palette (marked, last); search includes
  them, marked, with a filter.
- **Lists:** `Item.status` `archived`, set from the list's edit page only
  (hard to find); the project page has an archived section. Trashing an
  archived list and restoring it keeps it archived.
- **Every other item** has the same `status` field, and nothing treats
  `archived` for them: the importer sets it for Basecamp's archived
  to-dos, which then show as open.

## Lists

- **Easy to find:** "Archive" in the list page's "More" menu and in the
  menu of each list on the project page, and as a palette action on the
  list; "Unarchive" in the same places for an archived list. No change
  to what archiving a list means.
- **Never automatic:** a list isn't archived when it's empty or all done
  (decided 2026-11-21).
- **Archived lists** are left out of:
  - the project page's lists (they're in its "Archived lists" section);
  - "my to-dos" and the list by due date (with the calendar feed);
  - the palette's suggestions.

  Their to-dos stay readable through the list. Recurring to-dos in an
  archived list create no next one. Check what's missing of this today.
- **Events:** `archived` and `unarchived`, in the feed and the history,
  notifying nobody.

## Smaller items

- `archived` is not a status for to-dos, messages, docs, files, folders,
  questions or answers. The operations refuse it for them, and a data
  migration turns existing archived to-dos into completed ones (their
  `updated_at` as the completion time), other archived items into
  active ones. The `Status` choices keep `archived` for lists only (or
  the check is in `archive()`; one place).

## The importer

- **Basecamp's archived to-dos** come in **completed** (completed at
  Basecamp's archive time, by whoever archived them if known, else the
  import's person), keeping their comments.
- **Archived messages, docs, files and questions** are skipped, and the
  dry run and the report list them.
- **Archived to-do lists and projects** stay archived, as today.

## Done when

- Archiving and unarchiving lists from the list's menu, the project
  page's menu and the palette, through the API and the CLI.
- Archived lists left out of every place listed.
- Smaller items refusing `archived`, and the migration converting
  existing ones.
- The importer's archived to-dos completed and its other archived
  recordings skipped and reported (tests against the fixtures).
