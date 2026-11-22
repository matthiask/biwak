# Seeing more without opening everything

Pages show a bit more content where it saves a click, without turning
lists into walls of text.

**Status:** built (2026-11-20).

## Rule of thumb

Decided 2026-11-20, when asked to show more but not crowd the screen:

- **Small, always-visible signals** (an icon, a count) where many rows
  are shown: to-do rows, lists on the project page.
- **Short excerpts** (one or two lines, plain text, clamped with CSS)
  where few rows are shown and the text is the point: feed entries of
  comments and messages, the message board, project descriptions.
- **Full content on demand**, in place: the peek on to-dos.
- No settings to switch any of this on or off.

## The excerpt filter

`{{ text|excerpt:200 }}` (`biwak/templatetags/biwak.py`), also
`excerpt(text, chars, item)` from Python: renders the Markdown like
`|markdown`, strips the tags, collapses whitespace, cuts at a word
boundary and adds "…". Images and attachments become nothing, links
their text; escaped plain text, never `mark_safe`. Mentions show the
current name when Python passes the item, the label as written in
templates (to-do rows): current names there would need a batch lookup
per page, not a query per row (good enough, 2026-11-20).

## To-do rows

After the title, muted and small (`items/_signals.html`,
`biwak/items/glance.py`): a notes icon (the notes' excerpt as
`title`), a comments icon with the count, an attachment icon with the
count in its `title` (attachments of the notes and comments). Counted by
annotating the page's query (list, board, to-dos page), never a query
per row.

**The peek** (`items/_peek.html`, `frontend/peek.js`): clicking the
notes or comments icon loads `/todos/<pk>/peek/` below the row: the notes in full, the latest three
comments newest first, "Open". Through `item_for()`, so a client gets
404 for an internal to-do. No forms in the peek, and its checklists
can't be ticked.

## Elsewhere

- **Lists on the project page:** "12 open · 2 overdue" (danger color),
  only to-dos the person sees, one query for all lists.
- **Feed entries** of comments and messages show the text as it is now,
  200 characters, two lines (`feed.add_excerpts()`, one query per kind
  for a page; `excerpt` on the API's feed events). A message's current
  text goes with every event of it (decided 2026-11-20: the simplest
  rule); deleted comments and trashed messages show none.
