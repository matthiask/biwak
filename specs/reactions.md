# Reactions

A person reacts with an emoji or a few words instead of writing a
comment ("👍", "🎉", "Thanks!"), like Basecamp's boosts, shown under the
thing with who reacted.

**Status:** built (2026-11-20; adjusted after testing 2026-11-21):
`biwak/reactions/`, `{% reactions item %}` and `{% reactions item
comment %}`, `frontend/reactions.js`.

## Decided

- **Quick reactions:** 32 emoji in rows of 8 (decided 2026-11-21, 24
  before), plain and large in the picker, in
  `biwak/reactions/emoji.py`: 👍 👎 👏 🙌 🙏 💪 👋 ✅ / 🎉 🥳 ❤️ 😍 😂 😊 😅 🤪 /
  😮 😢 🤔 👀 💡 🤯 🔥 ✨ / 🚀 💯 ⭐ ☀️ 🍀 ☕ 🍩 🍰. No more (decided
  2026-11-21).
- **Short text** besides them: anything up to 40 characters (decided
  2026-11-20: Basecamp's 16 are too few), plain text, never Markdown, no
  mentions; whitespace collapses.
- **Notifying:** only the author of the thing (the comment's author or
  the item's creator) is told, never subscribers, on every level
  (decided 2026-11-22); reacting to yourself tells nobody. Collected into the
  author's next mail (`send_mails`' merging) or the digest under the
  thing ("Reactions to your comment:", "Bea: 👍 🎉, Carl: Thanks!"),
  never one mail per reaction.
- **Not activity:** reactions don't move a project's activity time,
  aren't on the project page or in the history.

## Model and behaviour

- `Reaction(user, item, comment null, content, created_at)`, audited;
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
- **Shown** under the item's text and each comment: one pill per
  content with its count, one's own highlighted, the people in the
  tooltip and a "Who?" list. htmx swaps only the block.
- **Events:** one `reacted` event per reaction (`content`, and
  `comment` in `data`); removing deletes its events and their unsent
  notifications (a mail already sent stays sent). The feed merges
  reactions per person and item ("Ada reacted to Order the tent: 👍 🎉").
- A trashed item keeps its reactions; a deleted comment takes them.

## API and CLI

`GET`, `POST` and `DELETE /api/v1/items/{id}/reactions/` and
`/comments/{id}/reactions/` with `{"content": …}`; to-dos, messages,
docs, files, answers and comments carry `reactions` (`{content, count,
people, mine}`, loaded with `reactions.operations.prefetch()`). `biwak
react TODO CONTENT [--comment ID]` toggles.
