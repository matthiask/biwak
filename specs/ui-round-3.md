# UI round 3: "My to-dos" and filters

Feedback from using "My to-dos" (2026-11-21):
- filtering by list makes little sense there, since the list's own page
  shows one list;
- the to-dos are ordered by due date, with no way to see them by
  project, list and group;
- filter forms only apply after pressing the button.

**Status:** built 2026-11-21. Decisions: the switch is a POST form like the projects page's (`/todos/grouping/`, back to the page with its filters) and a valid `?grouping=` stores the choice too; the API's `list_id` is gone, to-dos carry `project_name`, `list_title` and `list_position` (projects have no position, they go by name) beside their group's; `biwak todos` is by project unless `--by-due`; autosubmit is `frontend/autosubmit.js` (`data-autosubmit`, buttons marked `data-autosubmit-button`, `data-no-autosubmit` on a field), remembered filters `frontend/filters.js` (`data-remember`, `data-reset-filters`), the top bar's links and the palette's links restore them.

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

The list filter is gone from the page, the API (`list_id`) and the CLI. A
list's own page shows one list. Nothing reads `?list=` anymore, like any
other unknown parameter (decided 2026-11-21).

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

## 4. Filters remembered

Like Workbench: a filter page opened from the navigation shows the
filters used there last.
- **When stored:** in the browser (`localStorage`, wrapped in try/catch,
  per path), when a filter page loads with a query.
- **When restored:** a navigation link (the top bar, the palette's
  jumps) to such a page goes to it with the stored query.
- **Clearing:** a "Reset filters" link on the page clears it and the
  stored value. Opening the page by any other link (a bookmark, a link
  in a mail) uses that link's query as it is.
- **Which pages:** "My to-dos", the feed and the lantern's page; search
  is excluded (its query is the point).
- **The code:** adapted from Workbench's `main.js` (autosubmit and the
  stored searches; its code is the user's own, adapting it is fine,
  decided 2026-11-21).

Decided 2026-11-21.

## Done when

- **Django tests:**
  - both groupings with projects, lists, groups and to-dos outside
    groups, as staff and as a client (a client sees no internal lists);
  - the remembered choice;
  - the API's `grouping` and positions;
  - the CLI.
- **Browser tests:** a select change applying the filter, the focus
  kept, the button hidden with JavaScript, a filter restored through the
  navigation and cleared with "Reset filters".
- **`specs/todos.md`** updated: stage 2's filters and this grouping.
- **A screenshot** of "By project" with two projects, a group and an
  overdue to-do.
