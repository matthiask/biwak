# UI round 2: the lantern, people, settings

Round 2 of `ui-feedback.md` (2026-11-21), plus mentions by first name
and Basecamp's profile images. Built 2026-11-21. Where it lives now:

- **A, the lantern** (read and unread at a glance, wider, counting
  items): to move into `lantern.md`, below.
- **B, people in the interface:** the "Me" menu's mark and names
  linking to the person's page in `people.md`; mentions by short name
  to move into `notifications.md`, below.
- **C, Basecamp's profile images:** `import-basecamp.md`, `people.md`.
- **D, the projects page and colors:** no archiving from the cards
  (`projects-overview.md`), the swatches (`project-colors.md`).
- **E, sign-in and sessions on the settings page:** `keyboard.md`
  ("The settings page").
- **F, people with the same first name:** `people.md` ("Names").
- The client badge left the feed and the lantern (`feed.md`); filters
  and grouping went to round 3.

## To move after the builds

Into `lantern.md` (part A):
- An item with unread notifications gets a red dot before its title
  (`--wb-lantern-dot`, `.wb-lantern-unread`); read items are quiet
  (secondary color, not bold), in the menu and on the page. No "Read" and
  "Unread" headings: unread groups come first.
- The menu is `min(34rem, 100vw - 2rem)` wide, placed by `menus.js`.
- **The count is the number of items** with unread notifications, not of
  notifications (the menu groups by item): the badge, its tooltip,
  screen-reader text and `/lantern/count/` (`lantern.unread_count()`,
  `unread_counts()` gives both). `GET /api/v1/lantern/` answers `unread`
  (notifications) and `unread_items` next to `results`; `biwak lantern`
  prints one row per item ("(+N)" for more), `--json` the entries.
  Digests are unaffected.
- One divider between groups: the items' borders separate them, no
  `<hr>`.

Into `notifications.md` (part B, mentions):
- Mentions show the short name ("@Ada"; `people.md`, "Names", for the
  same first name), the full name in the `title`, rendered with the
  current name so renaming updates old mentions; as written where the
  reader may not know the person (`mentions.visible_people()`). The `@`
  list and `syntax()` (the API's and mail replies' `@Name`) write the
  short name as the label (`[@Ada](person:ID)`); the label is only a
  fallback. The same in mails and plain-text excerpts (through
  `reader()`, so mails use the recipient's view); in mails and `*_html`
  mentions aren't links.
