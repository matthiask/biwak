# Keyboard: the command palette and shortcuts

Working without the mouse: a command palette to jump anywhere and do
the common things, and single-key shortcuts inside pages, like GitHub
or Gmail.

**Status:** built 2026-11-21 (branch `keyboard`): the palette, the shortcuts, the settings page, the accent colors and the API's `me/`. See "Built" below for how and the choices to confirm.

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`. The palette lists content: its results go through
`visible_to()` like search, tested as a client.

**Depends on:** search (`search.md`), built. Independent of
`collaboration.md` (the live editor keeps its own keys).

**Touches:** a new app `biwak/palette/` (the endpoint for results),
`frontend/palette.js`, `frontend/shortcuts.js`, `base.html` (the dialog,
the actions of the page), templates that list rows (`data-kb-*`
attributes), the settings page (`biwak/accounts/`, the notification settings view in
`biwak/activity/views.py` moving there), CSS.

## Decided (2026-11-21)

- The palette offers jumps and actions; searching is one of its actions.
- Single-key shortcuts inside pages, like GitHub's, which a setting
  turns off (accessibility: single-key shortcuts must be switchable,
  WCAG 2.1.4).
- **Ctrl+K** (Cmd+K on Macs) opens the palette, and so does **/** when not
  typing in a field. Ctrl+K works also with shortcuts turned off; "/" is
  a single key and goes with the setting. Inside a Markdown field Ctrl+K
  inserts a link instead (decided 2026-11-21, `editor.md`); Escape and
  then Ctrl+K, or a click outside, reach the palette.

## The palette

A dialog (`<dialog>`, the combobox and listbox pattern for screen
readers) with a text field and a list below it. Arrow keys move, Enter
runs, Escape closes, focus returns where it was.

**Empty field:** the actions of the current page first, then the
person's bookmarks, then the pages visited last in this browser (kept in
`localStorage`, at most 20, titles as shown then; a per-browser
convenience, so it's fine that they don't follow the person to another
device).

**Typing** filters actions locally and asks the server for jumps after
a short pause (`GET /palette/?q=`, 150 ms debounce, the latest answer
wins):

- **Jumps:** projects, lists, messages, docs, files, folders,
  check-in questions and people, matched by title or name (prefix and
  word matches, the search's `simple` configuration), at most 20,
  grouped by kind. Through `Project.objects.accessible_to()`,
  `Item.objects.visible_to()` and, for people, the members rule
  (`people_known_to()`): a client never finds what they couldn't open
  or whom they may not know. Archived projects and their contents last,
  marked.
- **"Search for '…'"** is always the last entry and opens the search
  page with the text.

**Actions**, each shown only where it applies and only to people allowed
to do it (the server renders them per page as a JSON script in
`base.html`, with label, URL, method and an optional shortcut; the
palette never decides permissions itself):

- Everywhere:
  - go to projects, the feed, my to-dos, bookmarks, settings (the
    notification settings are a section of it; decided 2026-11-21);
  - search;
  - switch the theme;
  - new project (staff).
- In a project: new list (staff), new message, new doc and upload
  (staff), new check-in (staff), the project's feed, people, files and
  to-dos by due date.
- On a list: new to-do (opens and focuses the inline form), board or
  list view.
- On an item: complete or reopen (to-dos), comment (focuses the comment
  field), edit, bookmark, subscribe or unsubscribe, history (staff),
  copy link.

Actions with side effects post with the CSRF token (`frontend/http.js`)
and then reload or follow the answer's redirect, like their buttons.

## Shortcuts inside pages

Never while typing in a field, a `contenteditable` or the live editor,
and never with Ctrl, Alt or Meta held (except Ctrl+K). With the setting
off, only Ctrl+K works.

- **j / k:** the next or previous row: to-dos on lists, the board and
  "my to-dos"; messages on the board; results in search; entries in the
  feed. The current row is marked (`.wb-kb-current`, a visible focus
  ring) and scrolled into view; focus moves to its link, so screen
  readers follow.
- **Enter** or **o:** opens the current row.
- **x:** completes or reopens the current to-do (on lists) or the to-do
  of the page.
- **c:** focuses the comment field (item pages).
- **e:** edit (item pages, where allowed).
- **b:** bookmark; **s:** subscribe or unsubscribe.
- **g** then **p** (projects), **f** (feed), **t** (my to-dos), **b**
  (bookmarks): go to; "g" waits one second for the second key.
- **?:** a dialog listing the shortcuts of this page.
- **Escape:** closes dialogs and menus, clears the current row.

Rows say what they are through attributes, so one script serves every
page: `data-kb-row` on the row, `data-kb-open` (the link),
`data-kb-complete` (the toggle form). No page-specific JavaScript.

## The settings page (decided 2026-11-21)

The notification settings page becomes the person's settings page:
`/accounts/settings/`, "Settings" in the user menu (replacing
"Notifications"), the old URL redirecting. Sections, each saved on its
own:

- **Notifications:** what's on the page now (level, mail delivery, the
  overrides per project and item).
- **Keyboard:** `User.keyboard_shortcuts`, on by default (decided
  2026-11-21), with the list of shortcuts.
- **Appearance:** the theme (light, dark, as the system), moving the
  stored choice from the browser to the person so it follows them to
  other devices; the toggle in the navigation stays and saves there too.
  And an **accent color** (decided 2026-11-21) from the palette below,
  for the navigation, buttons, links and the focus ring, each defined as tokens in `main.css` for light and dark and
  checked for contrast (WCAG AA for text and controls, a test over the
  token values). The clients' amber is reserved and not offered, so the
  client badge and banner always stand out. `User.accent`, in `me/`
  like the theme.
- **Sign-in:** links to passkeys, sessions and API tokens (allauth's and
  Biwak's existing pages), so the user menu gets shorter.

The API: `me/` gets `keyboard_shortcuts`, `theme` and `accent` (read and
change);
the notification endpoints stay as they are.

**Previewing appearance** (decided 2026-11-21): choosing a theme or an
accent color on the settings page applies it to the page at once (the
`data-theme-mode` and `data-accent` attributes on `<html>`); only saving
stores it. Leaving without saving, or "Cancel", shows the stored choice
again (the next page renders it anyway).
Status: built; "Reset" next to Save, shown while the preview differs from the
stored choice (`frontend/appearance-preview.js`).

**The navigation's search field** (decided 2026-11-21) becomes a button
opening the palette: the magnifier as a quiet button like its
neighbours, on wide screens with "Ctrl K" ("⌘K" on Macs) beside it, no
field-like box (decided 2026-11-21 after trying it). It's the visible way into the palette and search for
people without the shortcut (phones); the palette's "Search for '…'"
leads to the search page, which keeps its own field with the filters.
Without JavaScript the button is a link to the search page.

## The palette (decided 2026-11-21)

Named after Biwak's mountain and camp world; the names describe the
character, the exact values are tweaked later. Tokens
`--wb-palette-<name>` (with the shades the accent needs, for light and
dark), shared by the accent colors and the project colors
(`project-colors.md`).

| Name | Character | Accent | Projects |
| --- | --- | --- | --- |
| Heather | violet, as today (the default) | yes | yes |
| Lake | clear blue | yes | yes |
| Forest | deep green | yes | yes |
| Glacier | cool teal | yes | yes |
| Ember | warm orange-red | yes | yes |
| Alpenglow | rose | yes | yes |
| Moss | olive green | | yes |
| Slate | blue-grey | | yes |
| Bark | earthy brown | | yes |
| Berry | magenta | | yes |

The clients' amber is not in the palette: the client badge and banner
always stand out. Stored as the name (`heather`, …), so changing a value
never touches data.

## Done when

- Playwright: Ctrl+K and "/" open the palette; jumping by typing;
  running an action (a new to-do through the palette, completing a
  to-do); j/k and x on a list; g then t; "?"; nothing fires while
  typing in a field; with the setting off only Ctrl+K works.
- The palette endpoint as staff, as a client (no internal items, no
  non-member staff, no limited projects they aren't in) and as staff
  without access to a limited project; a fixed number of queries.
- Actions per page only for people allowed to run them (a client sees
  no "new list"), tested on the rendered JSON.
- Screen readers: the dialog's roles and labels (checked in the test).

## Built (2026-11-21)

- **Settings page** (`biwak/accounts/views.py`): `/accounts/settings/` with
  one form per section, each posting to its own URL
  (`settings/notifications/`, `settings/keyboard/`, `settings/appearance/`);
  the old `/accounts/notifications/` redirects (301). The notification form
  (`SettingsForm`) stays in `biwak/activity/views.py`, so new delivery
  choices flow in from `MailDelivery`. Mails link to the new page. The user
  menu has "Settings" and "Calendar"; passkeys, sessions and API tokens
  moved to the page's "Sign-in" section.
- **Preferences** (`User.keyboard_shortcuts`, `theme`, `accent`, migration
  `accounts.0009`; `biwak/accounts/operations.py`). `<html data-theme-mode
  data-accent>` carry them; `theme.js` saves the toggle by POST
  (`settings/appearance/`, 204 with `X-Biwak-Fragment`), the browser's
  storage only serves the login page. API: `GET` and `PUT /api/v1/me/`
  (`keyboard_shortcuts`, `theme`, `accent`; what's given changes). The CLI
  is unchanged.
- **Palette tokens** (`frontend/styles/main.css`): `--wb-palette-<name>-<shade>`
  for the ten colors, shades `fill` (white text on it), `fill-hover`, `text`
  (links on the page and cards), `text-hover`, `bar` (the navigation), `tint-bg`
  and `tint-ink` (selections), `ring` (focus), plus `-rgb` of `fill`, `text` and
  `text-hover` (Bootstrap's links need them), for light and dark. An accent
  maps them to `--wb-accent-*` (`[data-accent=...]`), which the stylesheet
  uses; `project-colors.md` can use the same tokens. The test
  (`biwak/accounts/test_palette.py`) reads the tokens and checks WCAG AA
  (4.5 for text, 3 for controls) over all ten. The values are first
  guesses, to be tweaked. Heather keeps today's violet.
- **Jumps** (`biwak/palette/`): `GET /palette/?q=`, JSON; projects, lists,
  messages, docs, files, folders, check-in questions (not to-dos or answers)
  and people. Every word must start a word of the title or name; through
  `accessible_to()`, `visible_to()` and `people_visible_to()` (people the
  person shares a project with, the members rule); 3 queries, whatever the
  text. Titles show mentions as written. Without `q` it returns the
  person's bookmarks (at most 20).
- **Actions** (`biwak/palette/actions.py`): `{% palette %}` in `base.html`
  renders the page's actions as JSON; the types are link, post, focus, copy
  and theme, shortcuts come from the same list (`"x"`, `"g p"`). Only on the
  pages listed there (not on forms), with `ops.can_create()` and
  `can_change()` like the buttons. "New list" focuses the form on the
  project page and links to `#new-list` elsewhere (a hash on a field
  focuses it).
- **Scripts**: `frontend/palette.js` (the dialog, the combobox pattern),
  `frontend/shortcuts.js` (rows by `data-kb-row`, `data-kb-open`,
  `data-kb-complete`; "g" waits one second; the "?" dialog); both read the
  JSON, neither decides permissions.

### Decisions made on the way (to confirm)

- Labels of the actions as proposed (listed in `actions.py`), plus
  "Settings" and "Docs and files"; "Board view" and "List view" show the
  one not shown.
- Empty field: the page's actions, then the others, then bookmarks (at
  most 20), then the pages visited last.
- Palette results of staff and clients carry "For clients" on what clients
  can see and "Archived" on archived projects' contents.
- The calendar link stays in the user menu.
- "Enter" opens the current row only while focus is on the page, the row
  or its link; `o` always.
