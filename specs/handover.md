# Handing over: when somebody leaves

What happens to someone's work when they leave for good, and the tools to
hand it over: assignments that stay, assigning several to-dos at once,
and the admins' list of all projects. Decided with the user 2026-11-22.

**Status:** built (2026-11-22).

## Deactivating keeps the assignments

Decided 2026-11-22: an assignment also documents who did or was to do
the work; dropping it on deactivating made "Ada's open to-dos"
impossible to find afterwards.

- `activation.deactivate()` (and withdrawing that keeps the account,
  and the Django admin's "is active") doesn't unassign: no
  "unassigned" events, open to-dos keep the person.
- **Removing someone from a project still takes them off its open
  to-dos** (the question says so, `organizations.md`): a deliberate act
  on one project, and an active person shouldn't stay assigned to what
  they can't open.
- **Inactive people show as such** everywhere people show, not only
  assignees, so one rule (decided 2026-11-22): their mark greyed and
  "(inactive)" after the name, or a title on the mark where there's no
  room; one include, not copies. In the tags every list of people uses:
  `{% avatar %}` greys the mark (`.wb-avatar-inactive`, its title "Ada
  (inactive)"), `{% person_page %}` adds "(inactive)"; the timeline's
  and the feed's names (`feed.attach()`), the picker's labels
  (`PeopleField`, the marks through `avatar_data`'s `inactive`), the
  API's people (`is_active` on every person) and the CLI's names.
- **They aren't offered** for new assignments (the people picker),
  but stay in the to-do's assignees until someone takes them out.
- **The to-dos page's "Assigned to"** offers inactive people too, after
  the active ones under "Inactive", so their open to-dos can be listed
  and handed over (`/todos/?assignee=ID`): an `<optgroup>`, inactive
  members of the projects the person can open. "Nobody active" stays: to-dos
  whose assignees are all inactive (or none) count as unowned.
- Inactive people get no mails and no lantern entries.

## Selecting to-dos and assigning them at once

Like selecting tiles (`files.md`), on the to-dos page (`/todos/`) and a
list's page (list and board).

- **Selecting:** Ctrl-click (Cmd-click on a Mac) adds a row to the
  selection or takes it out, Shift-click selects from the last one
  clicked; **x** selects or deselects the current row, Shift with ↑/↓
  selects on (only up and down: rows are a column, also on the board,
  where Shift+arrows go through the rows in document order). A plain
  click opens the to-do as always. Escape or "Deselect" clears.
  Ctrl-click on the check, the grip or the peek keeps their own clicks.
  Rows carry `data-select-row` (`items/_todo.html`,
  `items/_due_row.html`); `frontend/select-rows.js` selects (class
  `is-selected`, as the tiles), `shortcuts.js` calls it.
- **With the focus in a row** (its link), x and Shift+↑/↓ work whatever
  the shortcuts setting, like a focused tile's x (keys on the focused
  element only, allowed by WCAG 2.1.4); on the current row of j and k
  they go with the setting, like every single key; Ctrl- and
  Shift-click always work (decided 2026-11-22).
- **Completing is Shift+x** (decided 2026-11-22: x selects, as on
  tiles): on rows and on a to-do's own page, and the palette's
  "Complete"/"Reopen" shows Shift+x.
- **Grips** still select for dragging several (SortableJS's MultiDrag)
  with the same class, so the bar counts them too; a click elsewhere
  doesn't deselect them (`avoidImplicitDeselect`, else the bar's
  "Assign…" would empty the selection), Escape and "Deselect" do. Rows
  selected with Ctrl-click aren't dragged together: MultiDrag's
  selection is one group's, this one goes across groups, lists and
  projects (decided 2026-11-22: dragging several stays as it was).
- **The bar** with a selection (`items/_selection_bar.html`): "Assign…"
  and "Deselect", with the count ("3 selected"). More actions (due date,
  moving, completing) may come later; not now.
- **"Assign…"** opens a modal (`form_response`) at
  `/todos/assign/?items=…&next=…` (`biwak/items/assigning.py`, the IDs
  in the query like the tiles' `items`), back to the page it came from:
  the people picker, offering only people who can be assigned in every
  selected to-do's project (`ops.assignable_to_all()`, members first
  when they're all in one project), and "Instead of the current
  assignees" (off by default: the people are added). Taking people out
  stays per to-do. Everybody who sees a to-do may change its assignees
  (`access.md`: to-dos' fields are shared work), so clients get
  "Assign…" too, offering only members of every selected to-do's
  project. Completed to-dos can be assigned, as on their page.
- **One operation per to-do** (`ops.assign_todos()`: per to-do
  `unassign()` with "Instead of", and `assign()`; an event each, the
  same permission checks). **All or nothing:** what can't be changed is
  what the person doesn't see (anymore): trashed, made internal, not a
  to-do. Then nothing changes and the modal says "2 of the selected
  to-dos can't be changed by you: they were trashed or you can't see
  them anymore." (also before posting); `AssignRefused` ("Bob can't be
  assigned to 3 of the to-dos.") before anything changes.
- **Told once:** the events of more than one to-do share a `batch`;
  `lantern.batch_key()` groups them per assigner across projects with
  `chain()`, like uploads (two "Assign…" of one person within
  `MERGE_AFTER` are one entry and one mail). The entry and the mail:
  "Ada assigned you 23 to-dos." (to subscribers who weren't assigned:
  "Ada assigned people to 23 to-dos."), each to-do linked, the title
  "To-dos" linking `/todos/`; the mail's subject "[Biwak] Ada assigned
  you 23 to-dos" (the project's name when they're all in one).
  Subscribers of a to-do hear of the assignment as with one to-do;
  those taken out by "Instead of" aren't told.
- **API:** `POST /api/v1/todos/assign/` with `ids`, `people`, `replace`
  (all or nothing), answering the to-dos (`TodoOut`); people not
  assignable to every to-do are a 400 without names (a client mustn't
  learn who an ID is). **CLI:** `biwak todos assign TODO… --to PERSON…
  [--replace]` prints each to-do with its assignees.

## Deactivating says what's left

The question before deactivating (`activation.md`,
`organizations/deactivate.html`, `activation.what_is_left()`) adds, for
whoever deactivates:

- "Ada Example has 23 open to-dos." (full names, not the display name
  with the organization), the sentence linking to `/todos/?assignee=ID`.
  The count is the to-dos page's (`due.todos(viewer, assignee=ID)`:
  what the link lists, so archived projects and lists don't count), so
  only to-dos in projects the deactivating person can open.
- "Ada is the only active staff member of: Website, Intranet" for
  projects the deactivating person can open (staff only, for internal
  people), counting staff and externals who are active members, of
  projects not archived (decided 2026-11-22: archived ones need nobody).
- **Nothing about projects one can't open** (decided 2026-11-22: no
  facts without a reason; even a project's title may say too much). The
  admins find those in "All projects" below.
- Below them: "Deactivating doesn't wait for the handover."; nothing
  shows when nothing is left.

It never blocks deactivating: people leave whether or not the handover
is done.

## All projects, for admins

Decided 2026-11-22: admins want a list of every project anyway. The
projects page (`projects-overview.md`) links "All projects" (admins
only) to `/projects/all/` (`biwak/projects/all_projects.py`,
`projects/all.html`) below its cards; also in the person menu after "My
activity" (decided 2026-11-22: not in "Administration"'s group, which is
the Django admin's own) and in the palette ("All projects", admins).

- **Who:** admins (`is_admin`); the page answers 404 to clients and
  externals and 403 to other staff (as `activation.md`'s pages), the API
  403 to everybody else.
- A table: name (a link where the admin can open it, else plain), the
  lock for limited, archived, active staff members (count), client
  organizations, open to-dos, open to-dos whose assignees are all
  inactive, last activity; "Join" for limited projects the admin isn't a
  member of (the existing joining, recorded as an event).
- **Columns:** "active staff" counts active members who aren't clients
  (externals too), shown in the danger color at 0; "clients" names the
  organizations of active client members; "open to-dos" are open, not
  trashed, in lists not archived; "of inactive people" those with at
  least one assignee and no active one (danger color when not 0); the
  last activity as on the cards (`last_activity_at`, "3 hours ago").
- **Filters** (`ui.md`, defaults the empty choice) are checkboxes:
  "No active staff member", "Limited", "With to-dos of inactive people",
  "Include archived" (as in search, since it adds them; archived ones
  left out by default), remembered like the other filters. Sorted by
  name; the columns don't sort.
- **Join** where the existing joining offers it: limited, not archived,
  the admin not a member (`joinable_projects()`).
- Counts only, no titles of to-dos and no people of projects the admin
  can't open: joining is how an admin gets in.
- In a fixed number of queries for any number of projects (four: the
  projects with their counts as subqueries, the client organizations,
  which the admin can open, and the admin's own row through
  `accessible_to()`).
- **API** `GET /api/v1/projects/all/?no_staff=&limited=&inactive=&archived=`
  (admins only, the same columns and filters) with `can_open`,
  `joinable` and `url` (null for projects the admin can't open);
  **CLI** `biwak projects --all [--no-staff] [--limited]
  [--inactive-todos] [--archived]` (admins).

## Projects whose only staff member left

Nothing happens to them (decided 2026-11-22): an all-access project
stays open to all staff, a limited one to admins after joining. "All
projects" shows them with "No active staff member".
