# Seeing more without opening everything

Today a to-do, a list or a feed entry shows little more than its title:
to know what's going on, people open one detail page after another. The
pages should show a bit more content where it saves a click, without
turning lists into walls of text.

**Status:** built (2026-11-20), branch `glance`. The filter (from the
projects page), to-do indicators and the peek (`items/_signals.html`,
`items/_peek.html`, `frontend/peek.js`, `biwak/items/glance.py`), list
counts, feed excerpts (also on the project page's short list and as
`excerpt` on API feed events; CLI 0.9.0). Not built: message excerpts
(no message board yet; `feed.add_excerpts()` is where they go).
Decisions, 2026-11-20:

- `excerpt(text, chars, item)` takes the item from Python only (a
  template filter has one argument): mentions show current names there,
  the label as written in templates (to-do rows). No query per row.
  Excerpts don't look attachments up.
- Feed excerpts are 200 characters, clamped to two lines by CSS.
- The attachment indicator is a plain icon with the count in its
  `title`: it counts attachments linked to the to-do (notes and
  comments), not a button.
- Counts on the project page include only to-dos the person sees; the
  count is "N open" and, when there are any, "M overdue" (danger color).
- The person feed is linked from names too (see `feed.md`).

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`. Excerpts show content: every one goes through the same
visibility as its item, with tests for clients.

**Depends on:** the activity feed (`feed.md`) and `notifications.md`
stage 1 (it changes `_todo.html` and mention rendering), both merged. Messages get
their excerpts with the message board (`files.md`, stage 2), which uses
the filter from here.

**Touches:** `biwak/templatetags/biwak.py` (the filter),
`items/_todo.html` and `biwak/items/views.py` (indicators, peek),
`projects/project_detail.html` (list counts), `activity/_event.html`
(feed excerpts), `frontend/styles/main.css`. Not the projects page
(`projects-overview.md`).

## Rule of thumb

Decided 2026-11-20, when asked to show more but not crowd the screen:

- **Small, always-visible signals** (an icon, a count) where many rows
  are shown: to-do rows, lists on the project page.
- **Short excerpts** (one or two lines, plain text, clamped with CSS)
  where few rows are shown and the text is the point: feed entries of
  comments and messages, the message board, project descriptions.
- **Full content on demand**, in place, without leaving the page: the
  peek on to-dos.
- No settings to switch any of this on or off.

## The excerpt filter

`{{ text|excerpt:200 }}` in `biwak/templatetags/biwak.py`, also usable
from Python (`excerpt(text, chars)`) for the API: renders the Markdown
the way `|markdown` does (mentions with current names, attachments),
strips the tags, collapses whitespace, cuts at a word boundary before
`chars` and adds "…". Images and attachments become nothing, links
their text. Escaped output (plain text, never `mark_safe`).

## To-do rows

In `items/_todo.html`, after the title and the existing assignees and
due date, muted and small:

- A notes icon if the to-do has notes, with the notes' excerpt (200
  characters) as its `title`.
- A comments icon with the number of comments, if any.
- An attachment icon if the notes or comments have attachments; leave
  out if it needs more than the annotation below.

Counted by annotating the query of the list page (`_todos()` in
`biwak/items/views.py`), the board view and the list by due date, never
one query per row.

**The peek:** clicking the notes or comments icon (a button, not a
link) loads `/todos/<pk>/peek/` with htmx below the row: the notes
rendered in full, the latest three comments with author and time, and
"Open" to the to-do's page. Clicking again closes it. The peek view goes
through `item_for()`, so a client gets 404 for an internal to-do like
everywhere else. No forms in the peek: commenting and editing stay on
the to-do's page.

## Lists on the project page

Each list's row gets its counts: open to-dos, and overdue ones in the
danger color when there are any ("12 open · 2 overdue"). One query for
all lists of the page. No to-do titles here: the list page shows them.

## Feed entries

In `activity/_event.html`, entries of comments and (once they exist)
messages show the excerpt of the text as it is now, at most two lines
(CSS `line-clamp`). A deleted comment shows no excerpt. Merged entries
("Ada commented 3 times") show no excerpts, only when expanded. The API
returns the same as `excerpt` on feed events.

## Done when

- The filter with tests: Markdown, mentions, attachments, cutting at
  word boundaries, HTML in the text escaped.
- To-do rows with the indicators on the list, the board and the list by
  due date, in a fixed number of queries (`assertNumQueries`).
- The peek as staff and as a client, including a client getting 404 for
  an internal to-do.
- The list counts on the project page; the feed excerpts, including a
  client's feed and a deleted comment.
