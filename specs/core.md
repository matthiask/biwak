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
  Lists of other projects are refused (web and API answer 400). "Move
  to…" in the "More" menu is the keyboard's way.
- Moves are one request and safe against concurrent moves (the list's
  row is locked).
- Deleting a group keeps its to-dos, ungrouped at the end.
- Groups are changed like their list (`can_change()`): clients add,
  rename, move and remove groups only in lists they created, 403
  otherwise, and don't get the controls (decided 2026-11-20).
- Completed to-dos leave the sequence and show below the list, newest
  first, collapsed (`todos.md`).
- A list has a description but no comments; lists are ordered on the
  project page and can be archived (`archiving.md`).

## Pages: conventions shared by every part

Decided in the UI rounds (2026-11-21, `ui-round-1.md` to
`ui-round-6.md`); `AGENTS.md` has the how-to.

- **Forms open in modals** and every modal form is also a page
  (`AGENTS.md`, "Modals"). Pages show content, not forms: "New list",
  "New group", renaming, members, editing a project or a list
  (2026-11-21) are buttons or "More" entries opening a modal. Trashing asks: "Move to the trash?
  It can be restored for 30 days." `form_response(help_page=…)` adds a
  quiet "More in the help" link.
- **Items' "More" menu** (`items/_more.html`): Move to…, Trash, and
  "Notifications…" on lists only (`notifications.md`).
- **Click to edit:** the pages of to-dos, messages, files and check-in
  answers show the item; clicking its title, text or facts (or "Edit",
  or `e`) swaps in the edit form in place (`frontend/view-edit.js`:
  `data-edit-url`, `data-edit-focus`, region `#live-text`), Save and
  Cancel swap back. No special views: htmx takes the region out of the
  item's edit page (`hx-select`); without JavaScript "Edit" is that
  page. Escape cancels an unchanged form, a changed one needs it twice
  within 1.5 seconds. Docs have the live editor instead.
- **Page headers:** all actions in one row at the `btn-sm` height. On
  phones (under 576 px) they show icons only (`.wb-label` hidden, label
  as `title`) and what isn't needed often moves into "More"
  (`.wb-phone-hide`, `.wb-phone-only`); on lists the bookmark, Edit and
  List/Board stay, on to-dos Complete, Edit and the bookmark.
- **Filter forms** (GET) apply themselves (`data-autosubmit`,
  `frontend/autosubmit.js`): selects, checkboxes and radios at once,
  text after 400 ms and on Enter; the button is hidden with JavaScript;
  the changed field keeps the focus. Forms that change things never
  autosubmit. Filter buttons sit at the height of the fields
  (`wb-filters`, `_filter_buttons.html`).
- **Filters are remembered** per path in the browser
  (`frontend/filters.js`, `data-remember`; for to-dos, the feed and the
  lantern's page, not search): links marked `data-restore-filters` (the
  top bar, the project's "All to-dos") go to the stored query; "Reset
  filters" clears it and shows only when a filter is set. Other links
  keep their own query. Adapted from Workbench (decided 2026-11-21).
- **View choices** (groupings, orderings) are query parameters
  remembered like filters, never fields on `User` (decided 2026-11-21:
  no row, no audit entry per click). Empty values stay out of the URL
  and every default is the empty choice.
- **Long selects** get a search field: `data-combobox`
  (`ComboboxSelect`, `frontend/combobox.js`, from Workbench's, decided
  2026-11-21): "Add someone" (also finding the address), the feed's
  person filter, a check-in's time zone; a new long select gets it too.
  Options say who someone is ("Ada Example · Example Client Ltd",
  "staff" for staff without an organization). Without JavaScript the
  plain select. The assignee picker is its own widget (`todos.md`).
- **Visible to clients:** the badge on rows, the tab at the window's
  edge on pages, the banner only above forms in modals (`access.md`,
  "Making it obvious").
- **Relative times** use the `ago` filter ("just now" under a minute).
- **Overdue and today** are badges (`todos.md`).
