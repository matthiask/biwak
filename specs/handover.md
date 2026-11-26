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
  and handed over (`/todos/?assignee=ID`, `biwak todos --assignee ID`): an `<optgroup>`, inactive
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
  and "Deselect", with the count ("3 selected"); "Move…" and "Due
  date…" below (open). Not completing several at once (decided
  2026-11-22: it doesn't make much sense).
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

## Moving and dating several to-dos

Asked by the user 2026-11-22, on the same selection as "Assign…".

**Status:** built (2026-11-22): "Due date…", "Move…" within and
across projects, told once about dates, moving telling nobody.

- **"Move…"**: a modal like a single to-do's "Move to…" (a list of the
  same project and a group of it, `move_todos()`), all or nothing. If
  it's built, across projects too (decided 2026-11-22; the user isn't
  sure it's needed: people can move whole lists), like moving top-level
  items (`lists-across-projects.md`: who's added, who's dropped).
- **"Due date…"** (decided 2026-11-22: built, removed again if it
  isn't useful): one due
  date for all, or "Move by N days" (and start dates with them), or
  "Remove", like copying a list's dates (`lists-across-projects.md`).
  The modal shows only the field of the choice (the date for "Set a
  date", the days for "Move by", none for "Remove"), switching as the
  choice changes (decided 2026-11-23 after a visual review; a form
  field's `shown_for`, `frontend/shown-for.js`); without JavaScript
  both stay visible.
- **Building it** like "Assign…": `biwak/items/assigning.py`
  (`todos_for(user, ids)`, `AssignForm`, the view `todos_assign` at
  `/todos/assign/?items=…&next=…`, all or nothing with
  `missing_message()`), its button in `items/_selection_bar.html`
  (`data-selection-action`, the script `frontend/select-rows.js` adds
  the selected IDs). Moving within a project: `ops.move_todos(items,
  todolist=, group=)`; to another project: one new operation in
  `biwak/items/operations.py` following `move_to_project()` and its
  `people_plan()`/`staying()` (the modal says who's added and who's
  dropped first, like "Move to…"). Dates: the `Dates` choices of
  copying (`KEEP` is "Set a date" here: one date, "Move by N days",
  "Remove"), through `ops.update_todo()` per to-do inside one
  transaction. Tests next to `biwak/items/test_assign_several.py`, a browser
  test only for the bar's new buttons (`test_e2e_handover.py`, the selection
  class).
- Both one event per action like "Assign…" (one entry in the lantern),
  the API (`POST /api/v1/todos/move/`, `/todos/dates/` with the IDs) and
  the CLI (`biwak todos move ID… --list`, `biwak todos dates ID…`).

### What's built (2026-11-22)

- **The bar** has "Assign…", "Move…" and "Due date…" (links with
  `data-selection-action`, `select-rows.js` unchanged), then "Deselect".
  Both modals are in `biwak/items/assigning.py` (`todos_move` at
  `/todos/move/?items=…&next=…`, `todos_dates` at `/todos/dates/`), say
  "3 to-dos" (or the title of one), go back to the page they came from,
  and refuse with `missing_message()` when one of the to-dos is gone,
  as "Assign…". Everybody who sees the to-dos may use them, clients too
  (to-dos' fields are shared work, as for "Assign…").
- **"Move…"** (`MoveForm`, built 2026-11-22): staff first choose the
  project (the combobox of active projects they open, the to-dos' own
  preselected, or the first one's), then "List and group" (the single
  to-do's choices over that project's lists they see,
  `list_targets()`) or "New list", and "Position" (to the top or the
  end). Choosing another project shows its lists first (the hidden
  `shown`; in the modal htmx posts the form on `change`, without
  JavaScript submitting does it). Into another project, the dialog
  first says who's added and who's dropped (`move_notes()`, "Bob
  Example will be added to Shop.", "Cleo Example won't see the to-dos
  in Shop: they'll be unassigned and unsubscribed.", as a warning) and
  `confirmed` is set, as "Move to…" of lists; there is no question about
  showing them to clients: the list's choice says "(clients can see
  this)", as for one to-do moved between lists. Hiding them is said
  first (decided 2026-11-23): where to-dos clients see go into an
  internal list (any list, a new one too), the dialog's `clients_note`
  says "Clients won't see 2 to-dos any more: the list is internal."
  (`hidden_note()`) and asks again, as for who's added and dropped. Then `ops.move_todos_to()`. Completed
  to-dos move too (decided 2026-11-22). **Clients** (decided
  2026-11-22) get no project field and no "New list": the lists of the
  to-dos' project they see; a selection from several projects is
  refused for them: "The selected to-dos are in several projects:
  to-dos move to the lists of their own project."
- **"New list"** (staff, who create lists): created in the chosen
  project inside the move's transaction, named after the list the
  to-dos come from when it's one, else "Moved to-dos" (in the mover's
  language), renamed later (confirmed 2026-11-22). Visible to clients
  when every list the to-dos come from is, else internal
  (`new_list_visible()`, decided 2026-11-23: client-visible to-dos
  shouldn't silently disappear for clients).
- **Across projects** (`ops.move_todos_to()`, built 2026-11-22):
  to-dos from other projects come along with comments, reactions,
  events and attachments (their project updated), completed ones too;
  `ops.todos_move_people()` is `people_plan()` over the assignees of
  the open ones and the subscribers of those from other projects, with
  the target list's visibility: assignees who don't see them there are
  added as members (staff, externals), clients dropped with their
  assignments (recorded, telling nobody) and subscriptions, subscribers
  who don't see them dropped. Then `move_todos()` with `_from`: each
  to-do's `moved` event, in the target project, names both projects
  (`from_project`, `to_project` and IDs, as for lists) and the list
  (`to`, `to_id`). Each project they left keeps one line for all
  (decided 2026-11-22): an event without item (`todos`, `to`, `to_id`,
  `to_project`, `to_project_id`), so its staff see it and clients
  don't: "moved 23 to-dos to Plans in Website", the list linked, each
  named only to readers who may see it now (`feed.add_target_lists()`,
  `feed.add_projects()`), else "moved 23 to-dos to Website" or "… to
  another project". Into or out of archived projects and templates is
  refused, as for lists. The events of more than one to-do share a
  `batch` (nobody is told about moves, so nothing groups them yet).
- **"Due date…"** (`DatesForm`): "Due dates" with "Set a date", "Move by"
  and "Remove" (copying's choices and labels, `KEEP` labelled "Set a
  date"), a "Due date" field and copying's "Days" field and help;
  "This field is required." / "By how many days?" at the fields.
  `ops.date_todos(items, actor=, dates=, due_on=, days=)` calls
  `update_todo()` per to-do in one transaction (an `edited` event each,
  merging as any edit, but with an edit outside the batch only when
  that one changed nothing but fields the batch changed, so "changed
  the dates" never hides a change of the notes or the title (decided
  2026-11-23: it's the kind of edit that matters, `_mergeable()` in
  `biwak/activity/operations.py`); more than one share a `batch`, so a subscriber
  is told once: one lantern entry and one mail, "Ada changed the dates
  of 23 to-dos.", the title "To-dos" linking `/todos/`, as "Assign…";
  `lantern.TODO_BATCHES`, `lantern.dated_line()`):
  - "Set a date" sets the due date and keeps start dates, as the to-do's
    page and the API do; a start date after the new date refuses all
    with "The start date can't be after the due date." (the existing
    rule rather than moving or dropping the start; confirmed 2026-11-22).
  - "Move by" moves due date, start date and "repeats until" (as
    copying does); to-dos without a due date stay as they are.
  - "Remove" removes due and start dates; the repeat rule and its end
    stay (as copying).
  - Completed to-dos are dated too (as "Assign…" assigns them).
- **API:** `POST /api/v1/todos/dates/` with `ids`, `dates`
  (`set`|`shift`|`remove`), `due_on`, `days` (-3650 to 3650), all or
  nothing, answering the to-dos (`TodoOut`); 400 for no to-dos, `set`
  without `due_on` ("Send the due date."), `shift` without `days`, a
  to-do gone or a start date after the date. `POST /api/v1/todos/move/`
  (built 2026-11-22) with `ids`, `list_id` (any project), `group_id`,
  `index`, `confirm`: all or nothing, completed to-dos too, answering
  the to-dos; into another project a 400 with who's added and dropped
  ("… Send “confirm”: true to move them anyway.") unless `confirm`, a
  403 for clients ("Only staff move to-dos into other projects."); 400
  for no to-dos, a to-do gone, archived projects or templates. A
  repeated ID counts once, as in `/todos/dates/` and `/todos/assign/`
  (decided 2026-11-23). No new list through the API: create it first. **CLI**
  (0.62.0): `biwak todos dates TODO… --due DATE|--shift DAYS|--remove`
  prints each to-do with its dates; `biwak todos move TODO… --list ID
  [--group ID] [--confirm]` goes through `/todos/move/`, across
  projects too (`--todos 1,2` still works).
- Tests: `biwak/items/test_several_todos.py`,
  `biwak/test_cli_handover.py`, the bar's buttons in
  `biwak/test_e2e_handover.py` (`SelectingTodosTest`).

### Answers (decided by the user 2026-11-22)

1. **Moving tells nobody**, within a project too (a single to-do's
   "Move to…" and dragging are the same code, `move_todos()`); the feed
   and the history show it as before. Except into another group of
   the same list since 2026-11-26 (`notifications.md`, "Watching a
   list"). One rule for every move
   (`Action.MOVED` in `notify.SILENT`): files moved into folders and
   items moved to other projects tell nobody either.
2. **Told once:** the events of one action share a `batch`; one
   lantern entry and one mail per person: "Ada changed the dates of 23
   to-dos." (the subscribers of the to-dos told once each).
3. **Moving across projects is built** (staff only; clients move within
   a project): first the project, then a list of it or "New list"
   (renamed later); the old project keeps one line for all moved
   to-dos; completed to-dos move too; who's added and dropped is shown
   first, like "Move to…"; `POST /api/v1/todos/move/` with `confirm`;
   `biwak todos move ID… --list` across projects. Used sparingly, so
   kept simple.
4. **Confirmed:** "Set a date" keeps start dates and refuses all when
   one would start after it; completed to-dos are moved and dated; the
   wording and the German labels above.

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
