# Help pages

The idea (2026-11-21): a help like Governance's, user documentation as
pages in the app, and the keyboard shortcuts moved there from the
settings page, with links to the help where people need it.

**Status:** spec (2026-11-21), the chapters confirmed the same day. Not
built.

**Agent:** a cheaper model following this spec and the checklist in
`AGENTS.md`. The texts are documentation: short, concrete, describing
what the app does now (read the specs and the templates, try it), no
marketing. Have them read by the user before merging.

**Depends on:** Home (`dashboard.md`) merged (it links here and the
docs describe it).

**Touches:**
- `docs/` (new: the Markdown files), `biwak/help.py` (copied from
  Governance's `governance/help.py`, keeping its copyright line,
  `NOTICE`), `templates/help.html`, a URL in `biwak/urls.py`;
- `templates/accounts/settings.html` (the shortcuts list leaves),
  `templates/palette/_shortcuts.html` (stays the one list),
  `base.html` (the "Me" menu), Home's "Useful" card, the palette
  (`biwak/palette/actions.py`);
- `frontend/styles/main.css` (Governance's `.wb-help`,
  `.wb-help-chapters`).

## Pages

- **`/help/`** and **`/help/<page>/`**, as in Governance: Markdown files
  in `docs/` (`README.md` the start page), rendered with
  `markdown-it-py` (in the dependencies already), the chapters as a
  navigation above each page, the current one marked. The files link
  each other relatively (`todos.md`), which works on GitHub; on the
  pages the links lead to the help pages.
- **English only for now**, like the interface (`AGENTS.md`): German
  files (`name.de.md`) come with the German translation; `help.py`
  keeps Governance's per-language table so they slot in.
- **Login required**, like every page. **Everybody sees every
  chapter** (decided 2026-11-21): clients may read how showing to
  clients works and about the CLI; the chapters say where something is
  for staff only.
- The docs come from the repository, not from users: HTML like `<kbd>`
  is fine in them (as in Governance).

## The keyboard page

- `/help/keyboard/` shows `docs/keyboard.md` (the palette, rows, what
  `j`/`k`/`x`/`o` do where) **and the shortcuts list from
  `palette/_shortcuts.html`** below it, so there's one list: the help
  page, the `?` dialog and nothing else render it. `help.py` appends
  the include for this page (a template for the page, not Markdown
  copying the list).
- **The settings page** keeps the on/off switch for shortcuts and loses
  the list; below the switch: "All shortcuts" linking to
  `/help/keyboard/`.
- **The `?` dialog** keeps the list and gets a link "Help" to
  `/help/keyboard/` at its end.

## Links to the help

- The "Me" menu: "Help" (as in Governance), above "Sign out".
- Home's "Useful" card: "Help".
- The palette: "Help" everywhere, and "Keyboard shortcuts" opening
  `/help/keyboard/`.
- Where a page has something to explain, a quiet link to the chapter,
  only where it helps (proposed: the visibility switch's modal to
  "Clients", the notification settings to "Notifications", the API
  tokens page to "The CLI and the API", the calendar link page to
  "To-dos").

## Chapters (decided 2026-11-21)

Each a file in `docs/`, short, with what a person does and where:

1. **Help** (`README.md`): what Biwak is for, the chapters, what it
   doesn't do (time tracking, invoices, chat).
2. **Finding your way** (`orientation.md`): Home, projects, to-dos,
   activity, the lantern, bookmarks, search and the palette, people.
3. **To-dos** (`todos.md`): lists, groups, assigning, due dates,
   repeating, checklists, the to-dos page and its filters, the calendar
   subscription.
4. **Messages, docs and files** (`files.md`): the message board,
   folders, docs edited together, versions, uploads, attachments.
5. **Check-ins** (`checkins.md`): questions on a schedule, answering,
   by mail too.
6. **Notifications** (`notifications.md`): the lantern, what reads a
   notification (opening it there, acting on the item), mails and
   digests, levels per project and item, replying by mail.
7. **Clients** (`clients.md`): what clients see, showing and
   hiding, the banner and badges, what clients can do.
8. **Keyboard** (`keyboard.md`): the palette and the shortcuts (above).
9. **The CLI and the API** (`cli.md`): tokens, installing
   `biwak`, a few examples, a link to the CLI's README.

## Done when

- `/help/` and every chapter render, with the navigation; links between
  the files work on the pages and on GitHub.
- Clients see the same chapters as staff; test.
- The shortcuts list is only in `palette/_shortcuts.html`, shown on
  `/help/keyboard/` and in the `?` dialog; settings links there.
- The links above exist (tests on the pages and the palette's JSON).
- The texts read by the user.
