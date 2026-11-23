# Reactions

A person reacts with an emoji or a few words instead of writing a
comment ("👍", "🎉", "Thanks!"), like Basecamp's boosts, shown under the
thing with who reacted.

**Status:** built (2026-11-20); reactions to a to-do getting completed
built (2026-11-23).

## Decided

- **Quick reactions:** 32 emoji in rows of 8 (decided 2026-11-21),
  plain and large in the picker, in
  `biwak/reactions/emoji.py`: 👍 👎 👏 🙌 🙏 💪 👋 ✅ / 🎉 🥳 ❤️ 😍 😂 😊 😅 🤪 /
  😮 😢 🤔 👀 💡 🤯 🔥 ✨ / 🚀 💯 ⭐ ☀️ 🍀 ☕ 🍩 🍰. No more (decided
  2026-11-21).
- **Short text** besides them: anything up to 40 characters (decided
  2026-11-20: Basecamp's 16 are too few), plain text, never Markdown, no
  mentions; whitespace collapses.
- **Notifying:** only the author of the thing (the comment's author,
  the item's creator or who completed the to-do) is told, never subscribers, on every level
  (decided 2026-11-22); reacting to yourself tells nobody. Collected
  into the author's next mail (`send_mails`' merging) or the digest under the
  thing ("Reactions to your comment:", "Bea: 👍 🎉, Carl: Thanks!"),
  never one mail per reaction.
- **Not activity:** reactions don't move a project's activity time,
  aren't on the project page or in the history.
- **Reactions to getting it done** (decided 2026-11-23): the timeline's
  line saying someone completed a to-do ("Urs completed this") takes
  reactions, like a comment. Basecamp has it; nobody would ask for it if
  it weren't there, it would just quietly be gone, and with it the small
  celebrations of someone getting something done: it's about
  thoughtfulness. Not the to-do's own reactions repeated there: someone
  may react critically to the to-do and happily to it getting done, and
  one set of reactions can't tell them apart. Below in "Completions".

## Model and behaviour

- `Reaction(user, item, comment null, event null, content, created_at)`
  (`biwak/reactions/`), audited;
  on a comment the comment's item is kept in `item`, so visibility is
  the item's. Unique per person, target and content.
- `REACTABLE` (`biwak/reactions/models.py`): to-dos, messages, docs,
  files and check-in answers, plus comments on any commentable item.
- **Who:** anyone who can see the item, staff and clients. Only one's
  own reactions are removed.
- **Adding and removing are explicit** (decided 2026-11-21): the picker
  (opened by a smiling face, `emoji-smile`, "Add a reaction") and
  others' pills only add; one's own reactions are marked in the picker.
  Removing goes through one's own pill, which first shows a trash icon
  ("mine" when others reacted the same); a click elsewhere or Escape
  cancels. Without JavaScript one's own pill links to a confirmation
  page (`…/reactions/remove/?content=…`). The form's `action` is `add`
  or `remove`; without it (as the API has it) the same reaction again
  removes it.
- **Shown** under the item's text and each comment (`{% reactions item
  %}` and `{% reactions item comment %}`, `frontend/reactions.js`): one pill per
  content with its count, one's own highlighted, the people in the
  tooltip and a "Who?" list. htmx swaps only the block.
- **Events:** one `reacted` event per reaction (`content`, and
  `comment` in `data`); removing deletes its events and their unsent
  notifications (a mail already sent stays sent). The feed merges
  reactions per person and item ("Ada reacted to Order the tent: 👍 🎉").
- A trashed item keeps its reactions; a deleted comment takes them.

## Completions (decided 2026-11-23)

- **Completions only, to-dos only:** no reactions on the timeline's
  other lines (moved, assigned, the due date …).
- **The target is the `completed` event:** `Reaction.event` (nullable,
  next to `comment`; a reaction is on the item, a comment or a
  completing, never on a comment and an event, a check constraint),
  `item` the to-do's, so visibility is the item's. Unique per person,
  target and content, like the others. The event deleted (only with its
  item, by cascading) takes them.
- **Merged lines** (`timeline.Line.completion`): a line that says it
  completed the to-do ("completed this and moved it to Done") offers the
  reactions of its latest `completed` event (completed, reopened and
  completed in one line: the last one). A line where completing and
  reopening cancelled out offers none; reactions already given stay in
  the database, unshown, and show again if the line does.
- **Reopened later** (another line): the reactions stay on the
  completing's line.
- **Who:** anyone who sees the to-do and the event
  (`Event.objects.visible_to()`): a client gets 404 for the completing
  of an internal to-do and for one from the time it was internal. A
  reaction to a completing clients didn't see is internal too (its
  `reacted` event, `record(internal=True)`), and clients' pages aren't
  told of it live.
- **Told:** the person who completed it (the event's actor), like a
  comment's author: never subscribers, nobody for reacting to oneself,
  collected into the next mail or the digest ("Reactions to you
  completing it:"); the lantern's entry opens the page at the line
  (`#reactions-event-<id>`). The feed says "reacted to Order the tent
  being completed". The `reacted` event has `event` in `data`.
- **Shown** with the same tag (`{% reactions item event=completion %}`,
  block `reactions-event-<id>`), `frontend/reactions.js` unchanged;
  live updates come with the line (`event-<id>`).
- **Pages:** `POST /events/<id>/reactions/`,
  `/events/<id>/reactions/remove/` (without JavaScript).

## API and CLI

`GET`, `POST` and `DELETE /api/v1/items/{id}/reactions/`,
`/comments/{id}/reactions/` and `/events/{id}/reactions/` (a to-do's
`completed` event, 404 for any other) with `{"content": …}`; to-dos,
messages, docs, files, answers and comments carry `reactions`
(`{content, count, people, mine}`, loaded with
`reactions.operations.prefetch()`), a to-do's own only. `biwak
reactions create TODO CONTENT [--comment ID | --event ID]` toggles
(CLI 0.67.0). The API has no timeline of a to-do: the `completed`
events' IDs are the feed's (`biwak feed --action completed --json`).
