# Archiving

Putting finished things out of the way without deleting them. Decided
2026-11-21: **projects and lists** can be archived, nothing smaller.
To-dos are completed, not archived; long runs of completed to-dos are
collapsed (`todos.md`).

**Status:** built (2026-11-21).

## Projects

`Project.archived_at`. Archived projects are left out of the projects
page (its "Archive" lists them), Home, the feed across projects and the
to-dos page; the palette lists them last, marked; search leaves them out
unless "Include archived" (`search.md`). Archiving and bringing back are
in the project's "More" menu (`projects-overview.md`).

## Lists

- `Item.status` `archived`. "Archive" and "Unarchive" in the list's
  "More" menu, in the menu of each list row on the project page and as
  a palette action, with `ops.can_change()` (staff, and clients for
  lists they created). API: `PATCH lists/{id}/ {"archived": …}`, `GET
  projects/{id}/lists/?archived=true`; CLI: `biwak list
  archive|unarchive LIST`, `biwak lists --archived`.
- **Never automatic:** a list isn't archived when it's empty or all done.
- **Archived lists** are in the project page's "Archived lists" section,
  and left out of the project's lists, the to-dos page, Home and the
  calendar feed; last and marked in the palette, left out of search
  unless "Include archived". Their to-dos stay readable through the
  list. Recurring to-dos in them create no next one.
- `archived` and `unarchived` events, in the feed and the history,
  notifying nobody (`notify.SILENT`).
- Trashing an archived list and restoring it keeps it archived.

## Nothing smaller

`ops.archive()` refuses anything but lists (the one place; `Status`
keeps the value). Migration `items/0011` converted earlier archived
to-dos into completed ones. Basecamp's archived recordings:
`import-basecamp.md`.
