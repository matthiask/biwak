# Copying lists, moving across projects

Copying a to-do list (into the same or another project) and moving
top-level items to another project. Decided with the user 2026-11-22.
Templates copy lists the same way (`templates.md`).

**Status:** built (2026-11-22).

## Copying a list

- **"Copy…"** in a list's "More" menu and the palette: a modal with
  the target project (the combobox of projects the person can open and
  create lists in; the same project preselected), the new title and
  the dates (below). The title is the list's own; only when the target
  project already has a list of that name (ignoring case) it gets
  " (copy)", then " (copy 2)" and so on (decided 2026-11-22).
- **The open work** (decided 2026-11-22): title, description, groups
  (in order), open to-dos in order with their notes and checklists
  (unticked as they are). Not completed to-dos, comments, history,
  events, subscribers, reactions, public links.
- **Assignees stay** (decided 2026-11-22):
  those who see the copy in the target keep their assignments; own
  staff and externals who don't are added to the target as members
  (with the default notification choice, as assigning a non-member
  does); clients who don't see the copy are left out. The modal says
  who first: "Dan Example will be added to Website.", "Cleo Example
  won't see the copy: left unassigned."
- **Dates:** "Keep", "Move by N days" (due and start dates together),
  or "Remove"; recurrence rules stay.
- **Visibility** is the target's: the copy is internal unless "Visible
  to clients" is ticked in the modal (staff only), which asks first like
  showing to clients does.
- Attachments in notes are copied (new files, not shared rows).
- Through an operation `copy_list(list, project, title, dates, actor)`
  recording one `created` event for the list (not one per to-do) and
  subscribing the copier to the list (API and CLI below).

## Moving to another project

- **Top-level items** (decided 2026-11-22): lists, messages, folders,
  docs and files at the top of their project (anything inside a folder
  moves with its folder, or is moved out to the top first). "Move to…"
  in the "More" menu offers other projects as targets (where the
  person may create such items); the API and CLI too. Single to-dos
  keep moving between lists of the same project only.
- **Everything comes along:** children, comments, reactions, events
  and history stay with the item (the new project's feed shows them,
  including past events; the old one's keeps a trace, below), checklist
  counts, public links (they keep working), bookmarks.
- **People** (decided 2026-11-22): assignees of open to-dos stay. Those who see the
  item in the target (members; own staff of an all-access project) just
  stay, own staff and externals who don't are added as members (the
  default notification choice), clients who don't are dropped with
  their assignments and subscriptions. Subscribers who won't see it
  there are dropped, not added. The modal lists both first ("Dan
  Example will be added to Website.", "Cleo Example won't see it in
  Website: they'll be unassigned and unsubscribed."); one rule,
  `ops.staying()` and `people_plan()`.
- **Visibility** becomes the target's top level: the item keeps its
  switch, but if it would become visible to clients of the target
  (who aren't the source's clients), the modal asks first like
  "Show to clients…". Internal stays internal.
- **Mentions** of people not in the target stay as text, rendered as
  for non-members (`notifications.md`).
- **Records** a `moved` event in both projects' terms ("moved Launch
  checklist from Pitch to Website"); notifies nobody. **The old project
  keeps a trace** (decided 2026-11-22: hard to find otherwise): a line
  "moved Launch checklist to Website" in its feed, without a link.
- Moving into or out of an archived project is refused.

## How it's built

- **Operations** (`biwak/items/operations.py`): `copy_list()` (with
  `copy_title()`, `open_todos()`, `copy_people()`, attachments copied
  as new files with new keys and the text pointing at them) and
  `move_to_project()` (with `move_people()`, `new_clients()`): the
  subtree's items, events and attachments get the new project, people
  added go through `project_ops.add_member()` (recorded as added),
  dropped assignees through `unassign()` (recorded, telling nobody;
  completed to-dos keep theirs, as when someone is removed from a
  project), dropped subscriptions are deleted, open doc editors check
  their access again. Who stays: `staying(project, visible)`, who sees
  it there (inactive people included: they keep their assignments);
  `people_plan()` decides who is added and dropped.
- **Modals** (`biwak/items/across.py`, `items/across_form.html`):
  "Copy…" (`list_copy`, staff) and "Move to…" of lists and messages
  (`item_move_project`), the project as a combobox; folders, docs and
  files at the top keep their "Move to…" (`files/library.item_move`),
  the select becoming a combobox with "This project" (its folders) and
  "Other projects". The menu offers "Move to…" for lists and messages
  only where there is another project to go to. **Asking** (decided
  2026-11-22): when people would be added or dropped or clients would
  see it, the dialog comes back with the sentences (who is added, who is
  dropped, as a warning; "Makes this list, 12
  to-dos and 34 comments visible to 3 clients.", counting the target's
  clients who aren't the source's) and `confirmed` set to the target;
  submitting it again with the same target does it; changing the target
  asks again; with nothing to say it acts at once. A client moving their
  message sees the names of people they may know only ("Bob Example
  and 1 other person won't see it…"). The palette offers "Copy…" on
  lists (staff).
- **The `moved` event** is one event in the target project, its data
  `from_project`, `to_project` and their IDs; shown "moved Launch from
  Pitch to Website", each project named only to people who may open it
  now (`feed.add_projects()`; the API's event data drops the other's
  keys), so clients of the target read "moved Launch to Website". It
  notifies nobody (`notify()`). The trace in the old project is an
  event without item (`title`, `kind`, `to_project`, `to_project_id`),
  so its own staff see it and clients don't; "moved Launch to another
  project" for readers who can't open the target. The history shows the
  project ("another project" for one the reader can't open).
- **Copies** (decided 2026-11-22): the copier creates the to-dos;
  assignees kept are subscribed to their to-dos (assigned means
  subscribed) without being told; mentions in notes stay text and tell
  nobody; the list's view (list or board), the groups' order and the
  repeat count come along. "Move by" moves "repeats until" too,
  "Remove" keeps it. Lists in the trash don't count for the "(copy)"
  clash, archived ones do; the suffix is in the copier's language.
- **Who** (decided 2026-11-22): "Copy…" is staff only (like creating
  lists), into every open project the person can open, the same one
  preselected; copying an archived list or one of an archived project
  is possible. Clients move messages they created into projects they're
  members of. Items inside a folder get no other projects as targets,
  and the selection's "Move to…" stays within the project. A moved item
  goes to the end of its kind at the target's top level.
- **Wording** (decided 2026-11-22): "Folder or project", "This
  project", "Other projects", "Due dates" with "Keep", "Move by" and
  "Remove" and a "Days" field ("For “Move by”: negative numbers move
  them earlier."), "Gets “(copy)” if the project has a list of that
  name.", "Makes the copy and 3 to-dos visible to 2 clients."
- **API:** `POST /lists/{id}/copy/` (`project_id`, `title`, `dates`
  keep|shift|remove, `days`, `visible_to_clients`; staff), and `POST
  /items/{id}/move/` with `project_id` (top-level items; a 400 with the
  sentences, people added or dropped and clients who'd see it, unless
  `confirm: true`, like merging organizations; decided 2026-11-22).
  Copying doesn't ask: `visible_to_clients` is explicit, as when
  creating a list. **CLI:** `biwak list copy LIST --to PROJECT [--shift DAYS|--no-dates]
  [--title] [--visible]`, `biwak move ITEM --to PROJECT [--confirm]`.
