# Keyboard: the command palette, shortcuts, settings and colors

Working without the mouse: a command palette to jump anywhere and do
the common things, and single-key shortcuts inside pages, like GitHub
or Gmail. Also the person's settings page and the colors, which came
with it.

**Status:** built 2026-11-21.

## Decided (2026-11-21)

- The palette offers jumps and actions; searching is one of its actions.
- Single-key shortcuts inside pages, which a setting turns off (WCAG
  2.1.4: single-key shortcuts must be switchable); on by default.
- **Ctrl+K** (Cmd+K on Macs) opens the palette, also with shortcuts
  off; **/** too when not typing (a single key, so it goes with the
  setting). Inside a Markdown field Ctrl+K inserts a link (`editor.md`);
  Escape and then Ctrl+K reaches the palette.
- **The navigation's search** is a quiet magnifier button opening the
  palette, with "Ctrl+K" ("⌘K" on Macs) beside it on wide screens, no
  field-like box (decided after trying it); without JavaScript a link
  to the search page. The palette's "Search for '…'" leads to the
  search page, which has its own field and filters.

## The palette

A `<dialog>` with the combobox and listbox pattern for screen readers
(`frontend/palette.js`). Arrow keys move, Enter runs, Escape closes,
focus returns where it was.

- **Empty field:** the page's actions, then the others, then bookmarks
  (at most 20), then the pages visited last in this browser
  (`localStorage`, at most 20; a per-browser convenience).
- **Typing** filters actions locally and asks the server for jumps
  (`GET /palette/?q=`, 150 ms debounce, the latest answer wins):
  projects, lists, messages, docs, files, folders, check-in questions and
  people (not to-dos or answers), every word starting a word of the
  title or name, at most 20, grouped by kind, in 3 queries. Through
  `accessible_to()`, `visible_to()` and `people_visible_to()`: a client
  never finds what they couldn't open or whom they may not know.
  Archived projects and their contents last, marked "Archived"; what
  clients can see with the yellow "Clients" badge of the pages (decided
  2026-11-22). The title wins the row: the hint (kind, project,
  shortcut) is cut first. "Search for '…'" is always last.
- **Actions** are decided on the server (`biwak/palette/actions.py`,
  rendered per page as JSON by `{% palette %}` in `base.html`): label,
  URL, type (link, post, focus, copy, theme) and an optional shortcut,
  shown only where they apply and to people allowed to run them
  (`ops.can_create()`, `can_change()`, like the buttons; tested on the
  rendered JSON). The script never decides permissions. Not on form
  pages. Actions with side effects post with the CSRF token
  (`frontend/http.js`) and follow the redirect, like their buttons.
  "To-dos I assigned" is `exact`: it opens its own query, not the one
  remembered for the page.

## Shortcuts inside pages

Never while typing in a field, a `contenteditable` or the live editor,
never with Ctrl, Alt or Meta (except Ctrl+K). The one list is
`palette/_shortcuts.html`, shown in the `?` dialog and on
`/help/keyboard/` (`help.md`).

- **j / k:** next or previous row (to-dos, messages, feed entries,
  search results); the row is marked (`.wb-kb-current`) and its link
  focused. **Enter** (while focus is on the page or the row) or **o**
  opens it.
- **Shift+x:** completes or reopens the current to-do or the page's
  to-do (the palette's "Complete"/"Reopen" shows it). **x** selects:
  the current to-do row on a list, the board and the to-dos page
  (`frontend/select-rows.js`, decided 2026-11-22, `handover.md`), a
  focused tile of a folder (`frontend/files.js`, `files.md`); Shift with
  the arrow keys selects on.
- **c** comment, **e** edit, **b** bookmark, **s** subscribe or
  unsubscribe.
- **g** then **h** (Home), **p** (projects), **f** (feed), **t**
  (to-dos), **b** (bookmarks); "g" waits one second.
- **?** the shortcuts dialog, **Escape** closes dialogs and menus and
  clears the current row.

**Ctrl+Enter** (Cmd+Enter on a Mac) **submits the form the focus is
in, every form** (decided 2026-11-22, the user: "for example the comment
form"): comments, modals, edit forms in place, new messages and docs.
One handler on the document (`frontend/submit-shortcut.js`), not one
per form, independent of the shortcuts setting: it presses the form's
default button (the first submit button, `requestSubmit()`, so htmx and
the browser's checks run as with a click), once per key press (a held
key or a second press within a second doesn't submit again). A form's
own handling comes first and wins by preventing the default: the
inline "Add a to-do" saves itself, the people picker's and the `@`
list's Enter pick while their list is open.

Rows say what they are through attributes, so one script serves every
page (`frontend/shortcuts.js`): `data-kb-row`, `data-kb-open`,
`data-kb-complete`, `data-select-row`. No page-specific JavaScript.

## The settings page

`/accounts/settings/`, "Settings" in the "Me" menu (decided 2026-11-21),
one form per section, each posting to its own URL; the old
`/accounts/notifications/` redirects (301). Sections:

- **Appearance** first, so the navigation bar, which shows the accent
  most, stays in view while choosing: the profile image (`people.md`),
  the theme (light, dark, as the system) and the accent color, stored on
  the person (`User.theme`, `User.accent`) so they follow them to other
  devices; the navigation's theme toggle saves there too. Choosing
  previews at once (`data-theme-mode`, `data-accent` on `<html>`,
  `frontend/appearance-preview.js`); only saving stores it, "Reset"
  shows the stored choice again.
- **Notifications** (`notifications.md`).
- **Keyboard:** `User.keyboard_shortcuts` and "All shortcuts" linking
  the help.
- **Sign-in** (decided 2026-11-21): passkeys, the authenticator app,
  connected accounts, sessions and the API tokens (`access.md`, "Sign-in").

- **Language** (`languages.md`): Automatic, Deutsch, English.

The API's `GET` and `PUT /api/v1/me/` read and change
`keyboard_shortcuts`, `theme`, `accent` and `language`.

## The palette of colors

Decided 2026-11-21. Named after Biwak's mountain world, shared by the
accent colors and the project colors (`project-colors.md`); stored as
the name, so changing a value never touches data. The values are first
guesses, to be tweaked.

| Name | Character | Accent |
| --- | --- | --- |
| Heather | violet (the default) | yes |
| Lake | clear blue | yes |
| Forest | deep green | yes |
| Glacier | cool teal | yes |
| Ember | warm orange-red | yes |
| Alpenglow | rose | yes |
| Moss | olive green | |
| Slate | blue-grey | |
| Bark | earthy brown | |
| Berry | magenta | |

- The clients' amber is not in the palette, so the client badge and
  banner always stand out.
- Tokens in `frontend/styles/main.css`: `--wb-palette-<name>-<shade>`
  (`fill` with white text on it, `fill-hover`, `text`, `text-hover`,
  `bar`, `tint-bg`, `tint-ink`, `ring`, and `-rgb` variants), for light
  and dark; an accent maps them to `--wb-accent-*`. Colors in the
  stylesheet are tokens, never hard-coded.
- **Contrast:** `biwak/accounts/test_palette.py` checks WCAG AA (4.5
  for text, 3 for controls) over all ten, the danger tone and every
  accent's page background.
- **The page background** takes a hint of the accent:
  `color-mix(in oklab, var(--wb-accent-bar) 5%, #eeebe4)` in light, 12%
  into `#0e0d11` in dark, the plain color as the fallback.
