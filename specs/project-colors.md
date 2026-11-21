# Project colors

A color per project, so projects are told apart at a glance.

**Status:** built 2026-11-21.

- **The names:** one of the palette's ten (`keyboard.md`: Heather, Lake,
  Forest, Glacier, Ember, Alpenglow, Moss, Slate, Bark, Berry), or empty.
  Never the clients' amber. `Color` in `biwak/accounts/models.py` is the
  one list (`Accent` the six of them offered as accents);
  `Project.color` stores the name.
- **Set by staff** on the new-project and edit forms, as a row of radio
  swatches (`ColorSwatches`, `forms/color_swatches.html`; decided
  2026-11-21): a small rounded square per color plus a struck-through
  "None", the name as accessible label and `title`, the checked one
  ringed in the accent color. API: `color` (a name or `""`) on `POST
  projects/` and `PATCH projects/{id}/`, `color` and `color_name` on
  `ProjectOut` (clients see them). CLI: `biwak project add|edit
  --color NAME|none`.
- **Suggested** for new projects (`suggested_color()`): the first color
  no active project has, else the least used; preselected in the form,
  used by the API when `color` is left out. Archiving frees a color.
- **Shown** always with the name, never as the only signal: a stripe on
  the project's card, a 3px line under the project page's header, and
  `{% project_dot %}` (a small rounded square, not a round dot, which
  reads as "unread", decided 2026-11-21; contrast 3:1 checked) before
  the name in the archived list, the feed across projects, search, the
  to-dos page across projects, the lantern and the palette. Not in
  breadcrumbs, mails or bookmarks.
