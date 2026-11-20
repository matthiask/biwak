# Reactions

A person reacts to something with an emoji or a few words instead of
writing a comment ("👍", "🎉", "Thanks!"), like Basecamp's boosts.
Shown under the thing with who reacted.

**Status:** open.

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`. Reactions are content on items: visibility tests
through every entry point.

**Depends on:** `notifications.md` stage 1 (mails, merging, digests).
Built for to-dos and comments first. Messages, docs, files and check-in
answers get reactions when their part exists: whichever part comes
second adds the kind to `REACTABLE` and the snippet to its page.

**Touches:** a new app `biwak/reactions/` (models, operations, views,
api, templates), `biwak/activity/` (an action, the mail and feed
templates), `items/todo.html` and the comment template, the CLI.

## Decided (2026-11-20)

- **Quick reactions:** a fixed set of 24 emoji offered in a small
  picker, one click each: 👍 👎 👏 🙌 🙏 💪 🎉 🥳 ❤️ 😍 😂 😊 😮 😢 🤔 👀 🔥
  ✨ ✅ 🚀 💯 ⭐ ☕ 🍰. In `biwak/reactions/emoji.py`, so changing them
  is one line.
- **Short text:** besides the quick ones, a text field for anything
  else (any emoji, "Thanks!", "Nice work"), at most 16 characters
  (Basecamp's limit; proposed, change it here if wrong). Plain text,
  never Markdown, no mentions.
- **Notifying:** the author of the thing reacted to is told, nobody
  else; reactions never mail subscribers. They're collected: a new
  reaction goes into the author's next mail through the existing
  merging (`send_mails`, about 2 minutes after the last change) or the
  digest, never one mail per reaction. Only on the levels "everything"
  and "what concerns me" (a reaction to your own text concerns you); the
  person reacting is never told, reacting to yourself tells nobody.

## Model

- `Reaction(user, item, comment null, content, created_at)`: on an item
  when `comment` is empty, else on the comment (the comment's item is
  kept in `item`, so visibility is the item's). Unique per person,
  target and content: the same reaction again removes it (a toggle);
  different ones from the same person are fine.
- `REACTABLE = {Kind.TODO}` to start, plus comments on any commentable
  item; later parts add `MESSAGE`, `DOC`, `FILE`, `ANSWER`.
- `audit_tables()` for the table (a migration like the others).

## Behaviour

- **Who:** anyone who can see the item, staff and clients. A client
  reacts only on visible items (there are no others for them). Removing
  only your own reaction; staff can't remove others'.
- **Operations** (`biwak/reactions/operations.py`): `toggle_reaction(
  user, content, *, item=None, comment=None)`, validating the length and
  stripping whitespace; it records a `reacted` event (`Action.REACTED`,
  with the content and, for comments, the comment's ID in `data`) and
  hands the author to the notification merging. Removing records
  nothing and, if the reaction isn't mailed yet, drops it from the
  pending mail.
- **Shown** under the to-do's text and under each comment: one pill per
  distinct content with its count ("👍 3"), your own highlighted; the
  names on hover and in a small list on click. Then a "+" button
  opening the picker and the text field. htmx swaps the reactions block
  only.
- **Trash:** reactions stay with their item; a deleted comment takes
  its reactions with it.
- **Feed:** at most one merged line per person and item within the
  feed's merging ("Ada reacted to Order the tent"), with the contents
  ("👍 🎉"). Not on the project page's short list of events.
- **Mails:** the author's mail lists the reactions under the thing
  reacted to ("Bea: 👍, Carl: Thanks!").
- **History:** none; reactions aren't changes of the item.

## API and CLI

- `GET /api/v1/items/{id}/reactions/`, `POST` and `DELETE` with
  `{"content": …}`; the same under `/comments/{id}/reactions/`.
  Items and comments in other responses get `reactions`: a list of
  `{content, count, people, mine}`.
- `biwak react TODO CONTENT [--comment ID]` (again removes it), and
  reactions shown in `biwak todo show`. Bump the CLI version.

## Done when

- Toggling on to-dos and comments through the page, the API and the
  CLI; the length limit; the quick set offered.
- Visibility: a client can't see or add reactions on internal items
  (404 everywhere), and doesn't see them in the feed or the mails.
- Notifying: several reactions within the merging time give one mail to
  the author, none to subscribers, none to the person reacting or for
  reacting to yourself; a removed reaction before sending isn't mailed;
  the digest lists them; the levels respected.
- The feed's merged line.
