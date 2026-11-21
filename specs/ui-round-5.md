# UI round 5: cards, the project's to-dos, filters, assigned by me

Round 5 of `ui-feedback.md` (2026-11-21).

**Status:** built 2026-11-21 (branch `ui5`). Decisions on the way:
- 1: the card is Bootstrap's `card` / `card-body`, which the edit form used
  already; the view's root is the card (inside `#live-text`, so editing in
  place swaps card for card), the doc's `#live-text` sits in a card.
- 2: the palette's "To-dos by due date" is now "All to-dos".
  `data-restore-filters` is on each top bar link and the project header's
  button (and its "More" entry).
- 3: `wb-filters` (`main.css`) on the form, `_filter_buttons.html` for the
  buttons; plain sizes everywhere (the by-due form's buttons were `btn-sm`
  next to normal selects), the checkboxes of the feed and the lantern are
  as high as the fields. Filter on the to-dos page is quiet now, like the
  others (it's hidden with JavaScript anyway).
- 4: `Assignment` keeps the old table name (`items_todo_assignees`), so
  existing rows and the audit trigger stay; the migration adds the columns
  and renames the unique constraint with SQL inside
  `SeparateDatabaseAndState`, `audit_tables()` runs again (idempotent) in
  it, and a test migrates back and forth with rows. `assign()` takes
  `assigned_by={user pk: assigner or None}` (default: the actor); the next
  recurring to-do and the importer use it. The filter is one `Exists` on
  `Assignment`, so "Assigned to: X" and "Assigned by: Me" mean the same
  assignment; "Nobody" with "Me" shows nothing. The form's labels are
  lowercase like the others ("assigned by"). The palette action
  "To-dos I assigned" is marked `exact`: unlike "Go to to-dos" it opens
  its own query, not the one remembered for the page (which would defeat
  it); the page then remembers that. The API's `assigned_by` other than
  `me` is a 400. CLI 0.30.0.
- 4, decided 2026-11-21 (user): the top bar's entry is "To-dos" (was "My
  to-dos"), active on every view of the page; it starts at
  `?assignee=me` until a view is remembered. The palette's "Go to my
  to-dos" is "Go to to-dos" (it restores the remembered view too). The
  page's title follows the filters: "My to-dos" (assigned to me),
  "To-dos I assigned" (by me, to anybody else), else "To-dos".
- "Assigned to me" in the header (decided 2026-11-21, built): a link with
  the same filters and me as the assignee, shown when someone else is
  chosen. "Reset filters" only shows when a filter is set (the grouping
  isn't one).
- **The default is the page's** (decided 2026-11-21): across projects
  (`/todos/`, the top bar's "To-dos" without a query) the empty choice is
  "Me", since everybody's open to-dos can get huge; "Anybody" is
  `assignee=anybody`, `assignee=me` still works (Home's link). A
  project's to-dos show anybody's by default. "Nobody" is "Nobody
  active": to-dos assigned to nobody or only to deactivated people (the
  API's `assignee=nobody` too).

**Agent:** a cheaper model following this spec and the checklist in
`AGENTS.md`; section 4 touches a model and the API, so check its
migration and the CLI carefully.

**Depends on:** `ui-round-4.md` merged (the to-do row, the page headers,
`view-prefs`' filters).

**Touches:**
- `items/todo.html`, `items/_todo_view.html`, `files/doc.html` and CSS;
- `projects/project_detail.html`;
- the filter forms' templates (`items/todos_by_due.html`,
  `activity/feed.html`, `activity/lantern.html`);
- `Todo.assignees` (a through model), `items/operations.py`
  (`assign()`, `update_todo()`, the next recurring to-do),
  `items/due.py`, `items/by_due.py`, the to-dos' API and CLI, the
  importer.

## 1. Cards on the to-do and doc pages

Decided 2026-11-21: the facts and the text together in one card.

- **A to-do's page:** one card (`card`, `card-body`) in the main column
  holding the facts line (assigned to, due on, repeats) and, below a
  divider, the notes ("Add notes…" when empty). Editing in place swaps
  the card's content for the form, the form sits in the same card.
- **A doc's page:** its content in a card the same way.
- Reactions and comments stay below the card, outside it; the sidebar
  stays as it is; the title stays in the page header.
- Both through the same CSS (a `wb-` class if Bootstrap's `card` isn't
  enough), nothing hard-coded per page. Wide and at 390 px.

## 2. The project's to-dos from the project page

Decided 2026-11-21. The header's "To-dos by due date" opens
`/projects/<pk>/todos/`, which is grouped by list since round 3, so the
label is wrong.

- **Below the "To-do lists" heading**, a small line of its own (not in
  the heading: it wrapped on phones, changed 2026-11-21): "All to-dos:
  by list · by due date", links to `project_todos` with `?grouping=project` and
  `?grouping=due`. These keep their own query (`frontend/filters.js`
  only rewrites the top bar's links), and the page then remembers it,
  as it does any query it loads with.
- **The header's button** becomes "All to-dos" (still `wb-phone-hide`,
  and in "More" on phones), without a parameter, and restores the
  remembered filters like the top bar's links: `filters.js` rewrites
  links marked `data-restore-filters` too, instead of only
  `.wb-nav-links a` (one selector, the top bar's links get the
  attribute).
- The palette's action for it, if there is one, gets the same label.

## 3. Filter buttons line up with the fields

"Filter" and "Reset filters" sit at the height of the selects, not at
the bottom of the labels' line: in every filter form ("My to-dos", a
project's to-dos, the feed, the lantern), through one CSS rule or one
include, not per page. Same height as the fields (`btn-sm` with
`form-select-sm`, or the plain sizes on both).

## 4. Assigned by me

Decided 2026-11-21: Biwak stores who assigned someone.

- **The model:** `Todo.assignees` gets a through model `Assignment`
  (todo, user, `assigned_by`, nullable, `on_delete=SET_NULL`, and
  `assigned_at`), unique per todo and user, in the audit log
  (`audit_tables()`). The migration turns the existing table into the
  through model; existing rows have no assigner (no users yet, no
  backfill).
- **Who assigned:** `assign()` sets `assigned_by` to its `actor`; the
  to-do's form, the API and mail replies go through it already. The next
  to-do of a repeating one keeps each assignment's `assigned_by`. The
  importer leaves it empty (Basecamp's API doesn't say who assigned).
- **The filter:** "My to-dos" and a project's to-dos get "Assigned by"
  in the filter form: "Anybody" (default) or "Me", remembered like the
  rest. "Assigned to: Anybody" with "Assigned by: Me" is Basecamp's
  "assigned by me"; with "Assigned to: Me" it's what I gave myself.
- **The palette** offers "To-dos I assigned" on every page, the same
  as "My to-dos" (`?assignee=&assigned_by=me`).
- **The API:** `GET /api/v1/todos/` takes `assigned_by=me`; each
  to-do's assignees carry `assigned_by` (a person, or null). **The
  CLI:** `biwak todos --assigned-by-me`; bump `cli/pyproject.toml`.
- **The to-do's page** says nothing new (the history already says who
  assigned whom).

## Done when

- The to-do and doc pages show the card, read and while editing
  (screenshots wide and at 390 px, looked at).
- The project page links both groupings, and the header says "All
  to-dos".
- The filter buttons line up with the fields on the four pages
  (screenshots).
- Django tests: `assign()` records the assigner, the recurring copy
  keeps it, the filter and the API's `assigned_by` (staff and client: a
  client sees only to-dos they may see), the palette's JSON, the CLI.
- Browser tests where JavaScript is involved (editing in place inside
  the card, the remembered "Assigned by").
