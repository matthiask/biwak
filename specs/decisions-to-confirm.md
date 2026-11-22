# Decisions to confirm

Decisions made without asking first, for the user to go through. Each is
built and written into its spec; once confirmed (or changed), delete the
entry; git keeps it.

## Copying lists and moving across projects (2026-11-22)

`lists-across-projects.md`:

- **Asking is a second step in the same dialog:** the form comes back
  with who is dropped (a warning) and who would see it (the clients'
  banner, the button turning destructive), submitting again does it; it
  acts at once when there's nothing to say. Changing the target asks
  again.
- **The API asks with a 400** for moves that drop people or show it to
  new clients, unless `confirm: true` (`--confirm`), like merging
  organizations. Copying doesn't ask: `visible_to_clients` is explicit,
  as when creating a list.
- **The `moved` event** is one event, in the target project; the old
  project's feed shows nothing of the item any more, the move included.
  Each project is named only to people who may open it now.
- **Dropping:** assignees of open to-dos are unassigned through
  `unassign()` (in the history, telling nobody); completed to-dos keep
  theirs, as when somebody is removed from a project. Subscriptions are
  deleted. A client moving their message sees the names of people they
  may know only ("Bob Example and 1 other person aren't in Website").
- **Copies:** the copier creates the to-dos; assignees kept are
  subscribed to their to-dos (assigned means subscribed) without being
  told; mentions in notes stay text and tell nobody; the list's view
  (list or board), groups' order and the repeat count come along. "Move
  by" moves "repeats until" too, "Remove" keeps it. Lists in the trash
  don't count for the "(copy)" clash, archived ones do; the suffix is
  in the copier's language.
- **Who copies and moves:** "Copy…" is staff only (like creating
  lists), into every open project the person can open, the same one
  preselected; copying an archived list or one of an archived project
  is possible. Clients move messages they created into projects they're
  members of. Items inside a folder get no other projects as targets,
  and the selection's "Move to…" stays within the project. A moved item
  goes to the end of its kind at the target's top level.
- **Wording:** "Folder or project", "This project", "Other projects",
  "Due dates" with "Keep", "Move by" and "Remove" and a "Days" field
  ("For “Move by”: negative numbers move them earlier."), "Gets “(copy)”
  if the project has a list of that name.", "Makes the copy and 3 to-dos
  visible to 2 clients."; German in the catalog.
