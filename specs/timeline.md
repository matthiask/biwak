# Timeline on the to-do's page

The comments section of a to-do shows what happened between the
comments, like a GitHub issue but simpler.

**Status:** built (2026-11-21): `biwak/activity/timeline.py`,
`items/_comments.html`, to-dos only (other items with comments later).

## What

- Under the heading "Comments" ("Activity" is the feed): comments and
  **event lines** in one list, oldest first. An event line is one quiet
  line between the cards: an icon, who, what, when ("Ada moved this to
  Done and completed it · 2 hours ago").
- **Which changes** (decided 2026-11-21): completed and reopened, moved
  (list and group), assigned and unassigned, the due date, the title,
  trashed and restored. Not: the creation (the header says it), comments'
  own events, reactions, edits of the notes (the history page, staff
  only), visibility (to-dos have no switch of their own).
- **Merging:** a line takes in the same person's next change within ten
  minutes of its last one, unless a comment is in between. Changes that
  undo each other within a line are left out (the line goes if nothing
  is left); what was set several times says its last value.
- **Live:** new lines arrive like new comments (a line is the live
  region `event-<first event's id>`, so a merge updates it and an undone
  completion removes it).
- The link to the history (staff) is at the end of the timeline.

## Where it comes from

- **Events** of the item through `Event.objects.visible_to(user)`, so a
  client sees only the events of the time the to-do was visible to them,
  and list names as the feed resolves them ("another list" when they
  can't see it; assignees they may not know read "someone"). Not the
  audit log, which is staff only and shows old texts. One query for the
  events, one for the comments.
- **`EDITED`** carries `fields` (`title`, `due_on`, `notes`,
  `recurrence`), the new `title`, `due_on` when it changed, and
  `title_was` and `due_was` for merging; older edit events have no
  `fields` and aren't shown.
- **`UNASSIGNED`** is an action of its own (with `assignees`): "removed"
  in the feed, the API and mails, notifying nobody (`notify.SILENT`).
