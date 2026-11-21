# Keyboard: the command palette and shortcuts

Working without the mouse: a command palette to jump anywhere and do
the common things, and single-key shortcuts inside pages, like GitHub
or Gmail.

**Status:** open.

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`. The palette lists content: its results go through
`visible_to()` like search, tested as a client.

**Depends on:** search (`search.md`), built. Independent of
`collaboration.md` (the live editor keeps its own keys).

**Touches:** a new app `biwak/palette/` (the endpoint for results),
`frontend/palette.js`, `frontend/shortcuts.js`, `base.html` (the dialog,
the actions of the page), templates that list rows (`data-kb-*`
attributes), a setting on the person (`biwak/accounts/`), CSS.

## Decided (2026-11-21)

- The palette offers jumps and actions; searching is one of its actions.
- Single-key shortcuts inside pages, like GitHub's, which a setting
  turns off (accessibility: single-key shortcuts must be switchable,
  WCAG 2.1.4).
- **Ctrl+K** (Cmd+K on Macs) opens the palette, and so does **/** when not
  typing in a field. Ctrl+K always works, also with shortcuts turned off;
  "/" is a single key and goes with the setting.

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
  - go to projects, the feed, my to-dos, bookmarks, notification
    settings;
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

## The setting

`User.keyboard_shortcuts` (on by default, proposed below), on the
notification settings page renamed to "Settings", or a small section of
its own there; through the API (`me/`) and `biwak` doesn't need it.

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

## Questions before building

- Shortcuts on by default (proposed: yes, with the setting to turn them
  off), or off until turned on?
- The labels of the actions; proposed as listed.
