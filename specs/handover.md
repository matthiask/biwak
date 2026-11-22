# Handing over: when somebody leaves

What happens to someone's work when they leave for good, and the tools to
hand it over: assignments that stay, assigning several to-dos at once,
and the admins' list of all projects. Decided with the user 2026-11-22.

**Status:** specified (2026-11-22), not built.

Depends on: `activation.md` (deactivating), `todos.md` (assignees, the
to-dos page, "Nobody active"), `files.md` (selecting tiles, the model
for selecting rows), `notifications.md` and `lantern.md` (grouping like
uploads), `projects-overview.md`, `access.md`, `keyboard.md`.

## Deactivating keeps the assignments

Decided 2026-11-22, replacing the decision of 2026-11-21 (`todos.md`,
`activation.md`): an assignment also documents who did or was to do the
work, and dropping it on deactivating made "Ada's open to-dos"
impossible to find afterwards.

- `activation.deactivate()` (and withdrawing that keeps the account,
  and the Django admin's "is active") no longer unassigns: no
  "unassigned" events, open to-dos keep the person. Everything else
  about deactivating stays.
- **Removing someone from a project still takes them off its open
  to-dos** (the question says so, `organizations.md`): a deliberate act
  on one project, and an active person shouldn't stay assigned to what
  they can't open.
- **Inactive people show as such** wherever assignees show (rows, the
  board, the to-do's page, the timeline's people, the people picker's
  chosen ones): their mark greyed and "(inactive)" after the name, or a
  title on the mark where there's no room; one include, not copies.
  Built in the tags every list of people uses: `{% avatar %}` greys the
  mark (`.wb-avatar-inactive`, its title "Ada (inactive)"),
  `{% person_page %}` adds "(inactive)"; the timeline's and the feed's
  names (`feed.attach()`), the picker's labels (`PeopleField`, the
  marks through `avatar_data`'s `inactive`), the API's people
  (`is_active` on every person) and the CLI's names (decided 2026-11-22:
  everywhere people show, not only assignees, so one rule).
- **They aren't offered** for new assignments (the people picker),
  but stay in the to-do's assignees until someone takes them out.
- **The to-dos page's "Assigned to"** offers inactive people too, after
  the active ones under "Inactive", so their open to-dos can be listed
  and handed over (`/todos/?assignee=ID`): an `<optgroup>`, inactive
  members of the projects the person can open. "Nobody active" stays: to-dos
  whose assignees are all inactive (or none) count as unowned.
- Inactive people get no mails and no lantern entries, as now.

## Selecting to-dos and assigning them at once

Like selecting tiles (`files.md`), on the to-dos page (`/todos/`) and a
list's page (list and board).

- **Selecting:** Ctrl-click (Cmd-click on a Mac) adds a row to the
  selection or takes it out, Shift-click selects from the last one
  clicked; **x** selects or deselects the current row, Shift with the
  arrow keys selects on. A plain click opens the to-do as always. Escape
  or "Deselect" clears.
- **Completing moves to Shift+x** (decided 2026-11-22: x selects, as on
  tiles): on rows and on a to-do's own page, and the palette's
  "Complete"/"Reopen" shows Shift+x. `palette/_shortcuts.html`, the help
  and `keyboard.md` change with it.
- **The bar** with a selection: "Assign…" and "Deselect", with the count
  ("3 selected"). More actions (due date, moving, completing) may come
  later; not now.
- **"Assign…"** opens a modal (`form_response`): the people picker,
  offering only people who can be assigned in every selected to-do's
  project, and "Instead of the current assignees" (off by default: the
  people are added). Taking people out stays per to-do.
- **One operation per to-do** (`ops` as for one to-do: an event each, the
  same permission checks). **All or nothing:** if any selected to-do
  can't be changed by the person, nothing changes and the modal says
  how many and why.
- **Told once:** a new assignee gets one lantern entry and one mail for
  all the to-dos of one "Assign…" ("Matthias assigned you 23 to-dos"),
  grouped like a batch of uploads (`lantern.chain()`; a `batch` in the
  events). People taken out by "Instead of" are not told, as now.
- **API:** `POST /api/v1/todos/assign/` with `ids`, `people`, `replace`
  (all or nothing, 400 naming the problem). **CLI:** `biwak todo assign
  TODO… --to PERSON… [--replace]` (or extend the existing command; bump
  the version).

Built (2026-11-22):

- **Rows** carry `data-select-row` (`items/_todo.html`,
  `items/_due_row.html`), the bar is `items/_selection_bar.html`;
  `frontend/select-rows.js` selects (class `is-selected`, as the tiles),
  `shortcuts.js` calls it for x and Shift+↑/↓ (only up and down: rows
  are a column, also on the board, where Shift+arrows go through the
  rows in document order) and completes on Shift+x. x goes with the
  shortcuts setting like every single key; Ctrl- and Shift-click work
  with it off (decided 2026-11-22, consistent: the tiles' x is on a
  focused tile only). Ctrl-click on the check, the grip or the peek
  keeps their own clicks.
- **Grips:** clicking grips still selects for dragging several
  (SortableJS's MultiDrag) with the same class, so the bar counts them
  too; a click elsewhere no longer deselects them
  (`avoidImplicitDeselect`, else the bar's "Assign…" would have emptied
  the selection), Escape and "Deselect" do. Rows selected with
  Ctrl-click aren't dragged together: MultiDrag's selection is one
  group's, this one goes across groups, lists and projects (decided
  2026-11-22: dragging several stays as it was).
- **"Assign…"** is `/todos/assign/?items=…&next=…`
  (`biwak/items/assigning.py`, the IDs in the query like the tiles'
  `items`), back to the page it came from. The picker offers
  `ops.assignable_to_all()` (members first when they're all in one
  project). Everybody who sees a to-do may change its assignees
  (`access.md`: to-dos' fields are shared work), so clients get
  "Assign…" too, offering only members of every selected to-do's
  project; what can't be changed is what the person doesn't see
  (anymore): trashed, made internal, not a to-do. Then nothing changes
  and the modal says "2 of the selected to-dos can't be changed by you:
  they were trashed or you can't see them anymore." (also before
  posting). Completed to-dos can be assigned, as on their page.
- **`ops.assign_todos()`:** per to-do `unassign()` (with "Instead of")
  and `assign()`; `AssignRefused` ("Bob can't be assigned to 3 of the
  to-dos.") before anything changes. The events of more than one to-do
  share a `batch`; `lantern.batch_key()` groups them per assigner
  across projects with `chain()`, like uploads (so two "Assign…" of one
  person within `MERGE_AFTER` are one entry and one mail, as two rounds
  of uploads are). The entry and the mail: "Ada assigned you 23
  to-dos." (to subscribers who weren't assigned: "Ada assigned people to
  23 to-dos."), each to-do linked, the title "To-dos" linking `/todos/`;
  the mail's subject "[Biwak] Ada assigned you 23 to-dos" (the project's
  name when they're all in one). Subscribers of a to-do hear of the
  assignment as with one to-do; those taken out by "Instead of" aren't
  told.
- **API** answers the to-dos (`TodoOut`); people not assignable to
  every to-do are a 400 without names (a client mustn't learn who an ID
  is). **CLI** `biwak todo assign` prints each to-do with its assignees.

## Deactivating says what's left

The question before deactivating (`activation.md`) adds, for whoever
deactivates:

- "Ada has 23 open to-dos" with a link to `/todos/?assignee=ID`,
  counting only to-dos in projects the deactivating person can open.
- "Ada is the only active staff member of: Website, Intranet" for
  projects the deactivating person can open (staff only, for internal
  people).
- **Nothing about projects one can't open** (decided 2026-11-22: no
  facts without a reason; even a project's title may say too much). The
  admins find those in "All projects" below.

It never blocks deactivating: people leave whether or not the handover
is done.

Built (2026-11-22): `activation.what_is_left()` (two queries) and
`organizations/deactivate.html` (extending `modal_form.html`, which got
a `before_form` block). The count is the to-dos page's
(`due.todos(viewer, assignee=ID)`: what the link lists, so archived
projects and lists don't count), the sentence the link; "the only active
staff member" counts staff and partners who are active members, of
projects not archived (decided 2026-11-22: archived ones need nobody).
The names are full names ("Ada Example has 23 open to-dos."), not the
display name with the organization. Below them: "Deactivating doesn't
wait for the handover."; nothing shows when nothing is left.

## All projects, for admins

Decided 2026-11-22: admins want a list of every project anyway. It
replaces the plain list "Limited projects you're not a member of" on the
projects page (`projects-overview.md`) with a link "All projects"
(admins only) to `/projects/all/`, also in Administration:

- A table: name (a link where the admin can open it, else plain), the
  lock for limited, archived, active staff members (count), client
  organizations, open to-dos, open to-dos whose assignees are all
  inactive, last activity; "Join" for limited projects the admin isn't a
  member of (the existing joining, recorded as an event).
- Filters (`ui.md`, defaults the empty choice): "No active staff
  member", "Limited", "With to-dos of inactive people", "Archived"
  (archived ones left out by default). Sorted by name; the columns don't
  sort.
- Counts only, no titles of to-dos and no people of projects the admin
  can't open: joining is how an admin gets in.
- In a fixed number of queries for any number of projects.
- API: `GET /api/v1/projects/all/` (admins only, the same columns and
  filters); CLI: `biwak projects --all` (admins).

## Projects whose only staff member left

Nothing happens to them (decided 2026-11-22): an all-access project
stays open to all staff, a limited one to admins after joining. "All
projects" shows them with "No active staff member".

## Done when

- Deactivating keeps assignments; inactive people show as such; the
  to-dos page lists an inactive person's to-dos.
- Selecting rows and "Assign…" work on the to-dos page and a list (list
  and board), by mouse and keyboard; x selects, Shift+x completes
  everywhere; one mail per assignee per "Assign…".
- The deactivation question shows the counts and the projects as above.
- "All projects" with its filters, API and CLI.
- Tests: the operations, every page as staff, admin and client (clients
  don't get "Assign…" where they can't change the to-dos, no "All
  projects"), the API and CLI, browser tests for selecting and the
  shortcuts; the help (`docs/todos.md`, `docs/keyboard.md`, the people
  chapter, the projects chapter) and the specs named above updated.
