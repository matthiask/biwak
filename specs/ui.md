# UI rules

The rules every page follows. Part-specific details (the to-do's page,
folders as tiles, the lantern) stay in the parts' specs; `AGENTS.md`
has the how-to ("Modals", checklist step 5). Most came from the user's
feedback rounds (`ui-feedback.md`), all built (2026-11-21).

## Quiet pages and modals

- **Pages show content, not forms** (2026-11-21: forms everywhere lost
  the context). "New list", "New group", renaming, members, editing a
  project or a list, moving and trashing are buttons or "More" entries.
- **Forms open in modals, and every modal form is also a page**
  (2026-11-21, copied from Governance; `AGENTS.md`, "Modals"). Without
  JavaScript, or with a modifier key, the link goes to the page.
  `form_response(help_page=…)` adds a quiet "More in the help" link.
- **Trashing asks:** "Move to the trash? It can be restored for 30
  days."
- **Items' "More" menu** (`items/_more.html`): Move to…, Trash, and
  "Notifications…" on lists only (`notifications.md`). Its entries
  (`items/_more_entries.html`) are also the "…" menu of the folders'
  tiles (`files.md`, "Folders").
- **Click to edit** (2026-11-21: the to-do's page was an edit form, not
  a page to read): the pages of to-dos, messages, files and check-in
  answers show the item; clicking its title, text or facts (or "Edit",
  or `e`) swaps in the edit form in place (`frontend/view-edit.js`:
  `data-edit-url`, `data-edit-focus`, region `#live-text`), Save and
  Cancel swap back. No special views: htmx takes the region out of the
  item's edit page (`hx-select`); without JavaScript "Edit" is that
  page. Escape cancels an unchanged form, a changed one needs it twice
  within 1.5 seconds. When the form goes (Save, Cancel, Escape) the
  focus returns to what opened it, else to "Edit" (decided 2026-11-22).
  Docs have the live editor instead.
- **Showing more without crowding:** small signals on many rows, short
  excerpts on few, full content on demand (`glance.md`).

## Layout

- **Page headers:** all actions in one row at the `btn-sm` height.
- **One primary button:** the button creating what a page is about is
  primary when it's the page's one such action (new project, message,
  check-in); elsewhere it's quiet (`btn-quiet`).
- **Cards** (2026-11-21: pages looked unstructured): an item's page
  shows its content in one card (the to-do's facts and notes, the doc's
  text, `todos.md`, `files.md`); collections are cards or tiles in a
  grid (the projects page, folders), not a list in a card.
- **Empty lists say so** (2026-11-21): a `list-group-item` in a list
  group, else a `text-body-secondary` paragraph.
- **Phones** (under 576 px, 2026-11-21: header buttons of varying
  heights): page headers show icons only (`.wb-label` hidden, the label
  as `title`) and what isn't needed often moves into "More"
  (`.wb-phone-hide`, `.wb-phone-only`); on lists the bookmark, Edit and
  List/Board stay, on to-dos Complete, Edit and the bookmark. Every
  item's page does this (`wb-page-actions is-compact`, `.wb-label` and a
  `title` on every button with an icon; 2026-11-22: messages, files,
  docs, check-ins and "Docs and files" showed their labels). Grids go
  to one column.
- **Floating disclosures** (menus, the reaction picker, the people
  picker's list) close on a click elsewhere and Escape (`data-dismiss`;
  elements other than `<details>` get a `dismiss` event).
- **Shared pieces come from an include** (comments, subscribers, the
  visibility switch, breadcrumbs, the to-do row), not a copy.

## Filters and view choices

- **Filter forms** (GET) **apply themselves** (2026-11-21, like
  Governance; `data-autosubmit`, `frontend/autosubmit.js`): selects,
  checkboxes and radios at once, text after 400 ms and on Enter; the
  button is hidden with JavaScript; the changed field keeps the focus.
  Forms that change things never autosubmit. Filter buttons sit at the
  height of the fields (`wb-filters`, `_filter_buttons.html`).
- **On phones** (2026-11-22: the feed's filters took five rows before
  the first entry) a filter form with several fields sits behind a
  "Filters" button saying how many are set (`.wb-filter-disclosure`,
  open while one is set); wider screens show it as it is.
- **Filters are remembered** per path in the browser (2026-11-21,
  adapted from Workbench; `frontend/filters.js`, `data-remember`; for
  to-dos, the feed and the lantern's page, not search): links marked
  `data-restore-filters` (the top bar, the project's "All to-dos") go to
  the stored query; "Reset filters" clears it and shows only when a
  filter is set. Other links keep their own query.
- **View choices** (groupings, orderings) are query parameters
  remembered like filters, never fields on `User` (2026-11-21: no row,
  no audit entry per click).
- **Empty values stay out of the URL, and every default is the empty
  choice.**

## Forms

- **Long selects get a search field** (2026-11-21, from Workbench's):
  `data-combobox` (`ComboboxSelect`, `frontend/combobox.js`): "Add
  someone" (also finding the address), the feed's person filter, a
  check-in's time zone; a new long select gets it too. Options say who
  someone is ("Ada Example · Example Client Ltd", "staff" for staff
  without an organization). Without JavaScript the plain select. Choosing
  several people (assignees, subscribers, whom to notify) is the people
  picker, its own widget (`todos.md`, "Assignees").
- **Form labels show with `capfirst`** in the templates, whatever case
  they're written in (2026-11-21: model `verbose_name`s are lowercase;
  one translation serves both).
- **A field right under a heading saying the same** keeps its label for
  screen readers, visually hidden: the comment field's "Comment" under
  "Comments".
- **Every `Textarea` is a Markdown field** with the toolbar
  (`data-toolbar`, `editor.md`).
- **Destructive or revealing actions ask first:** trashing, and showing
  something to clients (`access.md`, "Making it obvious"); hiding is one
  click.

## Links

- **Links inside sentences are underlined** (decided 2026-11-22): in
  rendered Markdown (notes, comments, the help) and in the lines of the
  feed and Home (`.wb-event`). Links that are a row, a title or
  navigation (breadcrumbs, the bar, lists of links) are not; people's
  names (`.wb-person-link`) neither, they underline on hover.

## Clients, icons, colors

- **Visible to clients** (2026-11-21: a banner on pages was too
  imposing): the badge on rows (`{% client_badge item %}`, not in the
  feed and the lantern, which tell what happened), the tab at the
  window's edge on pages (`items/_client_tab.html`), the banner
  (`items/_client_banner.html`) only above forms in modals (`access.md`,
  "Making it obvious").
- **Icons** with `{% icon %}`; a new one goes into
  `frontend/styles/icons.css` (`biwak/test_icons.py` checks).
- **Colors are palette tokens** (`--wb-palette-*`, `--wb-accent-*`),
  never hard-coded violet; the clients' amber stays out of the palette
  (`keyboard.md`, "The palette of colors").
- **Danger ink** (`--wb-danger-ink`, also `.text-danger` and invalid
  fields) instead of Bootstrap's red, which is below AA on the stone
  page (2026-11-22).
- **Dark mode** (2026-11-22): fields a little darker than cards, not
  black (`--wb-field-bg`); dialogs dim the page more
  (`--wb-backdrop`).
- **Relative times** use the `ago` filter ("just now" under a minute).
- **Overdue and today** are badges (`todos.md`, "The to-do's page").

## Motion

- **Short and quiet** (`celebrations.md`): 150 to 600 ms, never
  blocking, nothing on page load, CSS first, one celebration per action.
- **`prefers-reduced-motion: reduce` turns every animation off;** the
  scripts then don't intercept at all.

## Keyboard and accessibility

- **Focus is always visible** (decided 2026-11-22): every button gets a
  2px outline in the accent's ring color when focused by keyboard
  (white on the bar), whatever its variant.
- **"Skip to content"** is the first link of every page, shown when
  focused; `<main id="main">` is its target. Every `<nav>` has a label
  ("Main", "Breadcrumbs", …) and error pages (403, 404, 500) put their
  text in `<main>` with an `<h1>`.
- **Every control has a name:** task list checkboxes are named by their
  line, the combobox's hidden select is hidden from screen readers too.
- **Touch targets** (2026-11-22): on coarse pointers small controls
  (the to-do's check, row signals, breadcrumbs, names, the feed's
  links) keep their look and get an invisible larger area taking the
  tap; checkboxes grow a little; the tiles' "…" is 36 px. What needs a
  keyboard (Home's "Search Ctrl+K", "Keyboard shortcuts") is not shown
  on phones (`.wb-keyboard-only`).

- **Rows people move through with j/k** (to-dos, messages, feed
  entries, search results) carry `data-kb-row`, `data-kb-open` and, for
  to-dos, `data-kb-complete` (`keyboard.md`).
- **What a page offers** in the command palette and as shortcuts is
  decided on the server in `biwak/palette/actions.py`, with the same
  permission checks as the buttons. Shortcuts are listed once, in
  `palette/_shortcuts.html`.

## Testing

- **No browser tests of plain CSS layout** (sizes, positions,
  alignment, wrapping, fitting the screen; 2026-11-21: slow, broken by
  font differences, testing the browser): look at screenshots instead.
  Positions that JavaScript computes and computed colors stay testable
  (`AGENTS.md`).
