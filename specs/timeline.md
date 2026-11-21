# Timeline on the to-do's page

The idea (2026-11-21): the comments section of a to-do shows what
happened to it between the comments, like a GitHub issue but simpler:
completed and reopened, moved to another list or group, assigned. The
date on the "Completed by" button can go then (it went, 2026-11-21): the
timeline says when.

**Status:** spec (2026-11-21), the questions answered the same day.
Not built.

**Agent:** a cheaper model following this spec and the checklist in
`AGENTS.md`; the visibility tests reviewed.

**Depends on:** nothing (events and comments exist).

**Touches:** `biwak/items/views.py` (the to-do page), `items/_comments.html`
(or a new `items/_timeline.html`), `biwak/activity/` (a function building
the timeline from events), `items/operations.py` (events carrying what
changed, see "Edits"), `live/` (new lines arriving), `docs/todos.md`.

## What

- Under the heading "Comments" (it stays the heading: "Activity" is the
  feed), comments and **event lines** in one list, oldest first, as the
  comments are now.
- A **comment** stays the card it is today.
- An **event line** is one quiet line between the cards: an icon, who,
  what, when (relative, the exact time as `title`), e.g.
  - ☑ Ada completed this · 2 hours ago
  - ↺ Bob reopened this · yesterday
  - → Ada moved this to Plans (another list) / to Done (a group)
  - 👤 Ada assigned Bob, Cleo
- **Consecutive event lines merge** like the feed: the same person, one
  after the other, within ten minutes, become one line ("Ada moved this
  to Done and completed it"); completing and reopening back and forth is
  already gone (`feed.md`, decided 2026-11-21).
- **Not in the timeline:** the creation (the page header says who added
  it), comments' own events (the cards are there), reactions (shown on
  the cards), edits of the notes (the history page has them, staff
  only).
- **A link to the history** at the end of the timeline for staff (it is
  in the header today).

## Where it comes from

- **Events** of the item (`Event`, `activity/models.py`), through
  `Event.objects.visible_to(user)`, so a client sees exactly the events
  of the time the to-do was visible to them (`access.md`), and the
  lists' names as the feed resolves them (`feed.add_target_lists()`:
  "another list" when they can't see it).
- Not the audit log: its history is staff only and shows old texts.
- One query for the events of the page, one for the comments; merged in
  Python by time.

## Edits

Edit events say only "edited" today. For the timeline to show useful
changes, the operations record what changed, from now on (no backfill:
`no users yet`):

- `EDITED` gets `fields` (which changed: `title`, `due_on`, `starts_on`,
  `recurrence`, `notes`) and, for the title and the due date, the new
  value; the timeline shows the title and due date changes, not the
  notes (the history page has them).
- Unassigning records an event too (`UNASSIGNED`, or `ASSIGNED` with
  `removed`), so "Ada removed Bob" appears.

## Decided (2026-11-21)

1. **Which changes:** completed and reopened, moved (list and group),
   assigned and unassigned, the due date, the title, the visibility
   switch (staff only: clients don't see "hidden from clients" lines),
   trashed and restored.
2. **Merging:** the same person's changes one after the other within ten
   minutes are one line.
3. **To-dos first;** other items with comments later.
4. **Live:** new lines arrive on an open to-do page like new comments.

## Done when

- The to-do page shows comments and event lines in one list, as above,
  for staff and clients (a client sees no line of the time the to-do was
  internal, no internal list's name).
- Tests: the lines per action, merging, a client's view, the query
  count fixed (no query per line), live arrival if decided.
- `feed.md` points here; `docs/todos.md` says what the timeline shows.
