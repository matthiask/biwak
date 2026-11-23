# Timeline on the pages of to-dos, messages, docs and files

The comments section of a to-do, a message, a doc or a file shows what
happened between the comments, like a GitHub issue but simpler.

**Status:** built (2026-11-21) for to-dos; reactions to completing it
built (2026-11-23); messages, docs and files built (2026-11-23). Not
check-in answers: their comments are on the question's page, without
lines.

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
  is left); what was set several times says its last value. A to-do
  moved into another group (a board column like "Done") or list and back
  shows no line, the same as completing and reopening (decided
  2026-11-22): moves record where from (`group_was`, `to_was`;
  dragging between columns is one merged event keeping the first
  `group_was`), and moving back cancels out. A move into another list
  also records the column it ends up in and came from (`group_id`,
  `group_was`): it ends the column moves before it (they're about a
  column it left), and moving back into the list cancels out only if
  it's back in the column it started in, otherwise the line says the
  list. Older moves without them show as before. The API leaves these
  keys out.
- **Reactions** (decided 2026-11-23): a line that completed the to-do
  takes reactions to the completing, on its latest `completed` event;
  none on other lines or where completing and reopening cancelled out
  (`Line.completion`, `specs/reactions.md`).
- **Live:** new lines arrive like new comments (a line is the live
  region `event-<first event's id>`, so a merge updates it and an undone
  completion removes it).
- The link to the history (staff) is in the to-do's "More" menu
  (decided 2026-11-22: not below the timeline, `feed.md`).

## Messages, docs and files

Decided by the user 2026-11-23: the same timeline, but only the lines
that matter between comments, not a full list of events.

- **Which changes:** "Ada edited this" (the title or the text: a
  message's subject and text, a doc's text, a file's name and
  description), "uploaded a new version" (a file replaced), "showed this
  to clients" and "made this internal" (the switch,
  `visibility_changed`), moved (to another folder, "out of its folder"
  to the top level, from another project) and trashed and restored, as
  on to-dos. Not: the creation, pinning, public links, reactions, a
  message's category, "Save as a version" alone. Merging and cancelling
  out as on to-dos: showing and hiding again, or moving into another
  folder and back, within a line leave nothing.
- **Edits only after the first comment** (decided 2026-11-23 by the
  building agent, confirmed by the user): the line is there because comments may
  refer to the old text; before the first comment nobody can have, and
  writing a new doc (its first text up to "Done" and beyond) isn't told
  as edits of it. A live editing session is one line per person: the
  doc records one `edited` event per person and session (`record()`
  merges a person's edits within ten minutes), and the lines merge as
  on to-dos. An edit merged past a comment shows after it.
- **The history:** for staff "edited this" links to the item's history
  (`item_history`, staff only, `feed.md`), where the old text is;
  clients get the words without the link.
- **Clients** see the lines through `Event.objects.visible_to()` as on
  to-dos: "showed this to clients" (the event is recorded visible), never
  "made this internal" or what happened while it was internal (decided
  2026-11-23 by the building agent, confirmed by the user: the line where it became
  visible to them tells them the comments before it were written
  without them). Folders they can't see read "another folder".
- **Older events:** edits of messages, docs and files recorded before
  `fields` aren't shown; moves of docs and files before `folder_id`
  say "moved this".

## Where it comes from

`biwak/activity/timeline.py`, `items/_comments.html`.

- **Events** of the item through `Event.objects.visible_to(user)`, so a
  client sees only the events of the time the to-do was visible to them,
  and list names as the feed resolves them ("another list" when they
  can't see it; assignees they may not know read "someone"). Not the
  audit log, which is staff only and shows old texts. One query for the
  events, one for the comments.
- **`EDITED`** carries `fields` (`title`, `due_on`, `notes`,
  `recurrence`), the new `title`, `due_on` when it changed, and
  `title_was` and `due_was` for merging; older edit events have no
  `fields` and aren't shown. Of messages `title`, `content` and
  `category`, of docs `title` and `content` (none for "Save as a
  version" alone), of files `title`, `description` and `file` (a new
  version) (2026-11-23).
- **Moves between folders** (`move_item()`) carry `folder_id` and
  `folder_was` (None: the top level); the folder's name is looked up
  when shown, in one query (`add_target_folders()`), "another folder"
  when the viewer can't see it. The API leaves both out, like
  `to_was`.
- **`UNASSIGNED`** is an action of its own (with `assignees`): "removed"
  in the feed, the API and mails, notifying nobody (`notify.SILENT`).
