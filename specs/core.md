# Core: projects, items, lists, groups, to-dos

**Status:** built (2026-11-20).

Everything else builds on this. See `SPEC.md` for the model overview.

## Projects

- Name, description, color (`project-colors.md`), archived, all-access
  or limited (`access.md`). Members: staff and clients who joined or
  were invited. In all-access projects, staff who aren't members can
  still read and write; being a member means being listed, mentionable
  by default and included when someone notifies "everybody in the
  project".
- A project has one message board, one root folder and any number of
  lists. Project page: the lists, the latest messages, docs and files,
  links, and the project's activity.
- Archiving a project hides it from lists and the feed across projects
  (web and API); everything stays readable, including the project's own
  activity (`archiving.md`).

## Items

Delegated types, like Basecamp's recordings and recordables (decided
2026-11-20):

- **`Item`** holds what every item has: project, parent, kind, position
  (within the parent), title, creator, created/updated, status (active,
  archived for lists only, trashed), the visibility switch where
  `access.md` allows one, and the stored effective visibility.
- **One detail model per kind**, one-to-one with its item (primary key =
  the item's): `List`, `Todo`, `Message`, `Folder`, `Doc`, `Upload`,
  `Question`, `Answer`. Creating and deleting go through one function
  per kind that writes both rows.
- Comments, events, subscriptions, bookmarks and links have a foreign key
  to `Item` (or `Project`). They aren't items: comments are the largest
  table and need neither children nor visibility of their own.
- Lists over many kinds (feed, search, trash) query `Item` alone; pages
  of one kind join their detail model.

### Tree

Allowed parents per kind are enforced in the model, not only in forms:

| Kind | Parent |
| --- | --- |
| list | none (top level of the project) |
| to-do | list |
| message | none (the project's message board) |
| folder | none (root folder) or folder |
| doc, file | none (root folder) or folder |
| check-in question | none |
| check-in answer | check-in question |

Only folders nest without limit. `Item` uses django-tree-queries for
operations on whole subtrees (moving, trashing and restoring a folder,
breadcrumbs, recomputing visibility). Ordinary pages and the visibility
check don't need recursive queries; keep `with_tree_fields()` off by
default.

**Trash:** soft and recoverable for 30 days; children follow their
parent; an archived list comes back archived. Staff see a project's
trash and restore from it; clients rename, archive and trash only what
they created. `fairy_tasks` deletes what has been in the trash for 30
days.

## Text

Stored as **Markdown** (decided 2026-11-20): the same text in the app,
in mails, in the API and for agents. Rendered with markdown-it
(CommonMark, HTML in the source disabled, links made clickable, links to
other sites open in a new tab). Mentions have a Markdown syntax of their
own (`notifications.md`); checklists, the toolbar and pasting are
`editor.md`.

## Lists, groups and ordering

- **Groups** are a small model of their own (list, title, position), not
  items (decided 2026-11-20): no comments, no visibility, no events of
  their own. A to-do has a nullable group and a position within it;
  ungrouped to-dos come first, then each group's heading with its
  to-dos. In the board view the groups are columns (`todos.md`).
- Dragging a group moves it with its to-dos as a block. Clicking several
  to-dos' grips selects them, dragging one moves them together
  (`move_todos()`). Dragging across a heading sets the group; dragging to
  another list moves it there, ungrouped unless dropped into a group.
  Lists of other projects are refused (web and API answer 400); a
  repeated to-do counts once (`/lists/ID/todos/move/` and its API, as
  `todos/move/`; decided 2026-11-23). "Move to…" in the "More" menu is
  the keyboard's way, for open to-dos (404 for completed ones); the
  API's `todos/{id}/move/` refuses completed ones too (400, verification
  round 1, 2026-11-28, consistent), the selection's "Move…" and its
  `todos/move/` move them on purpose (`handover.md`).
- Moves are one request and safe against concurrent moves (the list's
  row is locked).
- **Moving a group without dragging** (decided 2026-11-23 by the user):
  "Move up" and "Move down" in the group's menu ("…", "Edit, move or
  remove the group"), plain forms posting to `group_move`, so the
  keyboard and pages without JavaScript reorder groups; no arrow
  buttons on the heading.
- Deleting a group keeps its to-dos, ungrouped at the end.
- Groups are changed like their list (`can_change()`): clients add,
  rename, move and remove groups only in lists they created, 403
  otherwise, and don't get the controls (decided 2026-11-20).
- **Group colors** (decided 2026-11-23 by the user: "same as folders",
  `files.md`, "Folders"): `Group.color`, a name of the palette or empty
  (`Color`, never the clients' amber), none unless chosen, never
  suggested. Set by whoever may change the group (`can_change()` on the
  list: clients in lists they created) with `ColorSwatches` in "New
  group" and "Edit the group" (the group's modal, title and color,
  `group_edit`). Shown as a stripe at the top of the group's card in
  the palette's fill and the heading in its text tone, in the list and
  on the board (`data-group-color`, also updated live), always next to
  the name; clients see it. Not on to-do rows, Home, the to-dos page,
  mails or the feed. A color alone records no event (groups have none).
  Copying lists and templates keeps it. API: `color` (a name or `""`)
  on `POST lists/{id}/groups/` and `PATCH groups/{id}/`, `color` and
  `color_name` on every group (`GroupOut`: lists, to-dos). CLI (0.64.0):
  `biwak groups --list LIST`, `groups create LIST TITLE [--color NAME]`,
  `groups update GROUP [--title] [--color NAME|none] [--index N]`,
  `groups delete GROUP`. The importer maps Basecamp's colors
  (`import-basecamp.md`).
- Completed to-dos leave the sequence and show below the list, newest
  first, collapsed (`todos.md`).
- A list has a description but no comments; lists are ordered on the
  project page and can be archived (`archiving.md`).

## Pages

The rules every page follows (modals, quiet pages, click to edit,
filters, the combobox, phones and more) are in `ui.md`.
