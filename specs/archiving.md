# Archiving

Putting things out of the way without deleting them: finished projects,
lists nobody works on any more, old messages and docs, to-dos that
won't be done. Archived things stay readable and findable; they just
don't clutter the pages people work on.

**Status:** open. Written 2026-11-21 after archived to-dos from a
Basecamp import showed up as open: the `archived` status exists on
every item, but only projects and lists treat it as anything.

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`, once the questions below are answered.

**Depends on:** the core, the importer (its mapping of Basecamp's
archived recordings).

## What exists

- **Projects:** `Project.archived_at`. Archived projects are left out of
  the projects page (an "Archive" page lists them), the feed across
  projects, "my to-dos", and the palette (marked, last). Search
  includes them, marked, with a filter.
- **Items:** `Item.status` is `active`, `archived` or `trashed`. Lists can
  be archived and unarchived (the project page has an archived section).
  Trashing an archived item and restoring it keeps it archived.
- **Nothing else** treats `archived`: an archived to-do, message, doc,
  file or folder shows like an active one everywhere. The importer sets
  the status from Basecamp, which is why archived to-dos "reappear".

## What archiving means (proposed)

One meaning for every kind: **out of the way, still readable.**

- **Left out of the working views:**
  - lists and the board;
  - "my to-dos" and the list by due date (and the calendar feed);
  - the message board;
  - folders;
  - the project page;
  - the palette's suggestions;
  - the lantern's counts.
- **Still reachable:**
  - their own page and links to it, with a banner "Archived on … by …"
    and "Unarchive";
  - an "Archived" section or page per container (a list's archived
    to-dos, the board's archived messages, a folder's archived docs and
    files);
  - search, marked, with the same filter as for archived projects;
  - the feed's history;
  - the API with a `status` filter.
- **Containers:** archiving a list, folder or project hides what's in it
  with it, without changing the children's own status. Unarchiving
  brings them back as they were (children archived on their own stay
  archived).
- **Notifications:** archiving notifies nobody. Activity on an archived
  item (a comment) still notifies as usual and doesn't unarchive it.
- **Recurring to-dos and check-ins:** an archived recurring to-do creates
  no next one, and an archived check-in question isn't asked (as today
  for archived projects).
- **Due dates:** archived to-dos are not overdue and not in "this week".
- **Who:** staff archive and unarchive everything. Clients archive what
  they created, as `can_change()` says. To-dos are shared work (decided
  2026-11-20), so clients archive visible to-dos too (see the
  questions).
- **Events:** `archived` and `unarchived` events, shown in the feed and
  the history, notifying nobody.
- **API and CLI:** `POST /api/v1/items/{id}/archive/` and `unarchive/` for
  every kind, `status=archived` filters on the list endpoints, and
  `biwak archive ITEM` / `biwak unarchive ITEM`.
- **The importer:** Basecamp's archived recordings map to archived items
  of the same kind; with this spec built, they stop showing as active.
  The importer also fetches archived messages, docs, files and
  questions where the API allows it.

## Questions before building

1. **To-dos:** can open to-dos be archived ("won't do"), or only
   completed ones? Basecamp archives any to-do. Proposed: any to-do;
   archiving an open to-do takes it off lists and "my to-dos" without
   completing it.
2. **Completed to-dos piling up:** archive completed to-dos automatically
   after some time (e.g. completed more than 6 months ago), or leave that
   to the existing "Completed (N)" section and paging? Proposed: no
   automatic archiving.
3. **Search:** archived items included by default (marked, with a filter
   to leave them out, like archived projects), or left out by default?
   Proposed: included, like archived projects.
4. **Clients:** may clients archive visible to-dos staff created (they
   can change every field of them), or only what they created?
   Proposed: like changing, so yes.
5. **Groups:** can a group of a list be archived (hiding its to-dos, e.g.
   a finished board column), or are groups only renamed and deleted?
   Proposed: no, groups stay simple.

## Done when

For every kind: archiving and unarchiving through the page, the API and
the CLI; left out of every working view listed above and shown in the
archived sections, search (marked) and the feed; containers hiding their
children and bringing them back unchanged; no notifications for
archiving; recurring to-dos and check-ins stopping; clients archiving
only what the rules allow (404 for internal); the importer's archived
to-dos imported archived and shown as archived (a test against the
fixtures).
