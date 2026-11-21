# Project colors

A color per project, so projects are told apart at a glance: on the
projects page's cards, in the project's page header, and next to the
project's name in the feed, search, the lantern, "my to-dos" and the
palette.

**Status:** built 2026-11-21 (branch `project-colors`): `Project.color`, the
edit page, API and CLI, the suggestion for new projects, the card stripe, the
header line and the dot in the feed, search, "my to-dos" and the palette. The
lantern (`collaboration.md`) uses `{% project_dot %}` when it lands. See
"Built" below.

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`.

**Depends on:** the accent colors' tokens (`keyboard.md`, the settings
page), so both use one palette.

**Touches:** `Project.color` (a migration), the project form and API,
templates showing project names (a small `{% project_dot project %}`
tag), CSS.

## What

- `Project.color`: one of the ten names of the palette in
  `keyboard.md` (Heather, Lake, Forest, Glacier, Ember, Alpenglow, Moss,
  Slate, Bark, Berry), or empty (neutral). Never the clients' amber.
- Set by staff on the project's edit page and through the API
  (`PATCH projects/{id}/ {"color": …}`, `biwak project edit ID
  --color …`); new projects get none, or a suggested one not used by
  other active projects.
- Shown as a colored stripe on the project card, a dot before the
  project's name elsewhere, and a thin line under the project page's
  header. Always with the name: color is never the only signal.
- Clients see the colors of projects they're in.

## Done when

The field, the form and API with tests (staff only; a client can't set
it), the tag in the listed places, the contrast test covering the
palette, and the projects page and a feed page checked in a Playwright
test at phone and desktop width.

## Built (2026-11-21)

- **One list of names:** `Color` in `biwak/accounts/models.py` holds the ten
  names; `Accent` is the subset of six (`ACCENT_NAMES`), built from it.
  `Project.color` is a `CharField` with those choices, blank for none
  (`projects.0003`); `Project.color_label` is the name shown.
- **Setting it:** `update_project(color=)` and `create_project(color=)`, staff
  only like the rest. The edit page and the new project form have a select
  (None, then the ten); `PATCH projects/{id}/` and `POST projects/` take
  `color` (a name or `""`), `ProjectOut` has `color` and `color_name`
  (clients see them too). CLI: `biwak project edit ID --color NAME|none`
  (new command, also `--name`, `--description`, `--limited/--all-access`),
  `project add --color`, a "Color" column in `biwak projects`; CLI 0.20.0
  (`MINIMUM` unchanged: older CLIs ignore the new fields).
- **Suggestion** (`suggested_color()`): the first color of the palette that
  no active project has; when all ten are taken, the least used one. Used by
  the form (preselected, so staff can choose None), and by the API and
  `create_project` when `color` is left out; archiving frees a color.
- **Shown:** `.wb-project-card[data-project-color]` has a stripe at its start
  edge, the project page a 3px line under its header, and `{% project_dot
  project %}` a dot (the palette's `fill`, checked against the page by the
  contrast test at 3:1) with the color's name as hidden text and `title`: in
  the cards and the archived list, the project header, the feed (when it
  isn't one project's), search results, "my to-dos" and by-due rows across
  projects, and the command palette (`color` and `color_name` in the jumps
  and bookmarks, drawn by `frontend/palette.js`). Not in breadcrumbs, mails
  or bookmarks (to confirm).
- **Tests:** `biwak/projects/test_colors.py`, `biwak/test_cli.py`, and
  `ProjectColorTest` in `biwak/test_e2e.py` (the projects page, a project
  page, the feed and the palette at 360 and 1280 px).
