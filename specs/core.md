# Core: projects, items, lists, groups, to-dos

Everything else builds on this. Built first, by one agent, before any part
in parallel. See `SPEC.md` for the model overview.

## Projects

- Name, description, archived, all-access or limited (`access.md`).
  Members: staff and clients who joined or were invited. In all-access
  projects, staff who aren't members can still read and write; being a
  member means being listed, mentionable by default and included when
  someone notifies "everybody in the project".
- A project has one message board, one root folder and any number of
  lists. Project page: the lists, the latest messages, docs and files,
  links, and the project's activity.
- Archiving a project hides it from lists and the feed; everything stays
  readable.

## Items

Delegated types, like Basecamp's recordings and recordables (decided
2026-11-20):

- **`Item`** holds what every item has: project, parent, kind, position
  (within the parent), title, creator, created/updated, status (active,
  archived, trashed), the visibility switch where `access.md` allows one,
  and the stored effective visibility.
- **One detail model per kind**, one-to-one with its item (primary key =
  the item's): `List` (description, view), `Todo` (notes, group,
  position in group, due and start date, completion, assignees,
  recurrence), `Message`, `Folder`, `Doc` (rich text), `Upload` (blob,
  size, content type, versions), `Question`, `Answer`. Creating and
  deleting go through one function per kind that writes both rows.
- Comments, events, subscriptions, bookmarks and links have a foreign key
  to `Item`. They aren't items: comments are the largest table and need
  neither children nor visibility of their own.
- Lists over many kinds (feed, search, trash, "everything in this
  project") query `Item` alone; pages of one kind join their detail model.

### Tree

Items form a shallow forest per project. Allowed parents per kind are
enforced in the model, not only in forms:

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
the operations on whole subtrees: moving, trashing and restoring a folder
with its contents, breadcrumbs, recomputing visibility (`access.md`).
Ordinary pages and the visibility check don't need recursive queries;
keep `with_tree_fields()` off by default.

Trashing is soft and recoverable for 30 days; children follow their
parent. Archiving keeps items readable but out of the way.

## Text

To-dos' notes, messages, comments and docs are stored as **Markdown**
(decided 2026-11-20): the same text in the app, in mails, in the API and
for agents, nothing to convert. Rendered with markdown-it (CommonMark,
HTML in the source disabled, links made clickable). Mentions get a
Markdown syntax of their own (`notifications.md`). An editor with
formatting buttons can come later, as long as it writes Markdown.

## Lists, groups and ordering

- **Groups** are a small model of their own (list, title, position), not
  items (decided 2026-11-20): no comments, no visibility, no events of
  their own. A to-do has a nullable group and a position within its
  group; ungrouped to-dos come first.
- Displayed as one sequence: ungrouped to-dos, then each group's heading
  with its to-dos. In the board view the same groups are columns
  (`todos.md`).
- Dragging a group moves it with its to-dos as a block: only the group's
  position changes. Dragging a to-do across a heading sets its group and
  position. Dragging a to-do to another list moves it there, ungrouped
  unless dropped into a group. Keyboard alternatives for all of it.
- Deleting a group keeps its to-dos, ungrouped at the end.
- Completed to-dos leave the sequence and show below the list, newest
  first, collapsed.
- Positions: integers with gaps, renumbered when needed, or fractional
  ranks; moves must be one request and safe against concurrent moves
  (lock the list's row).
- Lists themselves are ordered on the project page and can be archived.
- A list has a description but no comments.

## To-dos

Title, notes (rich text), assignees, due date (optional start date),
completed (when, by whom), comments, attachments. Assignees, recurrence,
the board view and the chronological list are in `todos.md`; the core
only needs the fields.

## Tests

Model constraints (allowed parents, an item and its detail row always
together), ordering after every kind of move including groups, concurrent
moves, trashing and restoring folders with their subtree, archiving.
