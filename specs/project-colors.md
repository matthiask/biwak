# Project colors

A color per project, so projects are told apart at a glance: on the
projects page's cards, in the project's page header, and next to the
project's name in the feed, search, the lantern, "my to-dos" and the
palette.

**Status:** open (wanted 2026-11-21, after the personal accent color in
`keyboard.md`).

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`.

**Depends on:** the accent colors' tokens (`keyboard.md`, the settings
page), so both use one palette.

**Touches:** `Project.color` (a migration), the project form and API,
templates showing project names (a small `{% project_dot project %}`
tag), CSS.

## What

- `Project.color`: one of a fixed palette (the accent colors plus a few
  more, about ten, each checked for contrast in light and dark), or
  empty (neutral). Never the clients' amber.
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

## Questions before building

- The palette's names and values; proposed by whoever builds the accent
  colors, so both match.
