# UI round 3: "My to-dos" and filters

Feedback from using "My to-dos" (2026-11-21):
- filtering by list makes little sense there, since the list's own page
  shows one list;
- the to-dos are ordered by due date, with no way to see them by
  project, list and group;
- filter forms only apply after pressing the button.

**Status:** open (spec, 2026-11-21).

**Agent:** a cheaper model following this spec and the checklist in
`AGENTS.md`.

**Depends on:** `todos.md` stage 2 (the list by due date) and the
archiving of lists, both merged.

**Touches:**
- `biwak/items/` (the by-due view, its form and queries);
- `items/todos_by_due.html` and its row include;
- `biwak/accounts/` (one field on `User`);
- a small `frontend/autosubmit.js`;
- the API and CLI of `/todos/`;
- `specs/todos.md`.

## 1. No list filter

The list filter goes from the page, the API (`list`) and the CLI. A
list's own page shows one list. No compatibility for old `?list=` links
(decided 2026-11-21).

## 2. Two ways to see them: by project or by due date

- **A switch** at the top, "By project" and "By due date", like the
  projects page's "Activity / A–Z" (a button group).
- **The choice is remembered per person**, like `User.project_order`:
  `User.todo_grouping`, "project" by default. Changing it posts and
  comes back. Without JavaScript, the switch's links carry
  `?grouping=…` and store it too.
- **By project:**
  - **Projects** by name, each a heading with its color swatch.
  - **Lists inside a project** in the project's own order.
  - **Groups inside a list** in their own order. Each group gets a small
    heading; to-dos outside a group come first, as on the list's page.
  - **To-dos** in their position within the list or group.
  - Each to-do keeps its due date and the overdue or "Today" badge.
  - Empty projects and lists aren't shown.
- **By due date:** the sections as today: overdue, today, this week,
  later, no date.
- **On a project's page** (`/projects/<pk>/todos/`) "By project" means
  by list and group, without the project heading.
- **The API and CLI:**
  - `GET /api/v1/todos/` takes `grouping=project|due` and gives each
    to-do its project, list and group with their positions, so clients
    can group the same way. Without the parameter it uses the person's
    choice.
  - `biwak todos --mine` prints headings the same way; `--by-due` picks
    the other.
  - Bump the CLI.
- **Completed to-dos** (`?state=completed`) stay newest first, without
  grouping, as now.

## 3. Filter forms apply themselves

A general rule for every filter form submitting with GET:
- the to-dos by due date;
- the feed's filters;
- the lantern's page;
- search's filters (its text field excepted: Enter searches).

The rule:
- **Changing a select, checkbox or radio** submits the form at once.
- **A text field** submits after a short pause (400 ms), and on Enter.
- **The submit button** stays for people without JavaScript and is
  hidden with JavaScript (`.js` on `<html>`).
- **It's opt-in:** `data-autosubmit` on the form, handled by a small
  `frontend/autosubmit.js`. Forms that change things (POST) never
  autosubmit.
- **Focus and scroll:** the page reloads with the new query, as now. The
  field that changed keeps the focus after the reload (`autofocus` by
  name from the query, or restored by the script), and the scroll
  position stays.

Decided 2026-11-21.

## Done when

- **Django tests:**
  - both groupings with projects, lists, groups and to-dos outside
    groups, as staff and as a client (a client sees no internal lists);
  - the remembered choice;
  - the API's `grouping` and positions;
  - the CLI.
- **Browser tests:** a select change applying the filter, the focus
  kept, the button hidden with JavaScript.
- **`specs/todos.md`** updated: stage 2's filters and this grouping.
- **A screenshot** of "By project" with two projects, a group and an
  overdue to-do.
