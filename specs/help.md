# Help pages

User documentation as pages in the app, like Governance's.

**Status:** built (2026-11-21); German pages (2026-11-22).

## Pages

`biwak/help.py` (copied from Governance, keeping its copyright line),
`templates/help.html`, `docs/`.

- **`/help/`** and **`/help/<page>/`**: Markdown files in `docs/`
  (`README.md` the start page), rendered with `markdown-it-py`, the
  chapters as a navigation above each page. The files link each other
  relatively (`todos.md`), which works on GitHub and on the pages. HTML
  like `<kbd>` is fine: the docs come from the repository.
- **German and English** (decided 2026-11-22: German help pages): a
  German reader gets `docs/<name>.de.md` (`PAGES["de"]`), everybody else
  `<name>.md`. Per page, English is the fallback: a page without its
  German file is shown in English with a line saying so ("This page of
  the help is in English for now."). The German files link each other
  as `todos.de.md`; both spellings lead to the help pages. The German
  follows `languages.md` (du, ss, Kund:innen, the glossary), and the
  labels it quotes are the German catalog's, exactly.
- **Login required. Everybody sees every chapter** (decided
  2026-11-21): clients may read how showing to clients works and about
  the CLI; the chapters say where something is for staff only.
- **The texts** describe what the app does now, short and concrete, no
  plans, no marketing (`AGENTS.md`, "Help"). A part that changes what
  people see or do updates its chapter.
- **Keeping both languages in step** (decided 2026-11-22): a change to
  the help updates the English and the German file in the same branch,
  like texts and their translations (`AGENTS.md`, "Language").

## Chapters

Decided 2026-11-21, one file each, in `help.py`'s table: Help
(`README.md`: what Biwak is for and doesn't do), Finding your way
(`orientation.md`), To-dos, Messages, docs and files (`files.md`),
Check-ins, Notifications, Clients, Keyboard, Signing in (`sign-in.md`),
The CLI and the API (`cli.md`). Coming from Basecamp (`basecamp.md`,
decided 2026-11-23): where Biwak differs from Basecamp and why, for
people switching, not marketing; it holds "What Biwak doesn't do",
which was on the start page, and the start page links to it.

## The shortcuts list

`palette/_shortcuts.html` is the one list: `/help/keyboard/` shows
`docs/keyboard.md` with the list appended (`WITH_SHORTCUTS`), the `?`
dialog renders it with a "Help" link, and the settings page links to it
(`#shortcuts`) instead of listing it.

## Links to the help

"Help" in the "Me" menu (above "Sign out"), Home's useful links and the
palette (with "Keyboard shortcuts"). Quiet links to a chapter only where
they help: `form_response(help_page=…)` ("More in the help", e.g. the
visibility modal to "Clients"), the notification settings, the API
tokens page and the calendar page.
