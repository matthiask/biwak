# Decisions to confirm

Decisions made without asking first, for the user to go through. Each is
built and written into its spec; once confirmed (or changed), delete the
entry; git keeps it.

### Handover

Built 2026-11-22 (`handover.md`); each written into the spec.

- **"(inactive)" everywhere people show**, not only assignees: the one
  tag for marks and names (`{% avatar %}`, `{% person_page %}`) greys and
  labels inactive people on every page (subscribers, members, the
  timeline's actors), the feed's and the timeline's names say it too, and
  the API's people have `is_active`.
- **Clients get "Assign…"** for the to-dos they see: to-dos' fields are
  shared work (`access.md`), so everybody who sees one may assign; they
  are offered members of every selected to-do's project only.
- **What "can't be changed" means:** to-dos the person doesn't see
  (anymore): trashed, made internal, not to-dos. Completed to-dos can be
  assigned, as on their page. The modal says it before posting too.
- **Two "Assign…" of one person within ten minutes are one entry and
  one mail**, as two rounds of uploads are (`chain()`). Wording: "Ada
  assigned you 23 to-dos." and, to subscribers who weren't assigned,
  "Ada assigned people to 23 to-dos."; the entry's title "To-dos" links
  `/todos/`; the mail's subject "[Biwak] Ada assigned you 23 to-dos" (the
  project's name when they're all in one).
- **x follows the shortcuts setting** (Ctrl- and Shift-click don't);
  Shift+arrows only up and down. Rows selected with Ctrl-click aren't
  dragged together (SortableJS's selection is one group's); grips still
  select for dragging and count in the bar, and a click elsewhere no
  longer clears that selection, Escape and "Deselect" do.
- **The deactivation question** leaves archived projects out of "the only
  active staff member of", counts partners as staff, and ends with
  "Deactivating doesn't wait for the handover."
- **"All projects":** linked from the person menu (next to
  "Administration") and the palette as well as below the projects page's
  cards; 403 for staff who aren't admins, 404 for clients and partners;
  "Archived" is a checkbox "Include archived"; "clients" lists the
  organizations of active client members; "of inactive people" needs at
  least one assignee; zero staff and to-dos of inactive people in the
  danger color.
