# The lantern and live updates

An in-app inbox for notifications, the **lantern** (named 2026-11-21,
after Biwak's camp theme; avoiding "Hey!", the name of Basecamp's mail
product), and pages
that update while they're open: comments, reactions and changes by others
appear without reloading.

**Status:** open.

**Agent:** a strong model: live updates send changes to many people at
once, and each must only ever get what they may see.

**Depends on:** `collaboration.md` merged (the ASGI server, Channels and
the Redis channel layer), notifications stage 1 (the `Notification`
records, levels, `send_mails`), reactions.

**Touches:**
- `biwak/activity/` (reading, the lantern views, API, mails skipping what
  was read);
- a new `biwak/live/` (the websocket consumer and the "changed" signals);
- `base.html` (the lantern menu);
- the item, list and board templates (live regions);
- `frontend/lantern.js` and `frontend/live.js`;
- the settings page (mail delivery "none");
- the CLI.

## Decided (2026-11-21)

- The lantern shows the same notifications as the mails, with the same levels:
  whatever you'd be told about. Mail becomes a delivery choice: **each**
  (as today), **digest**, or **none**.
- **Read in the lantern, not mailed:** a notification read in the app before its
  mail goes (the merge window of about 2 minutes, or before the digest)
  is left out of the mail, and a mail with nothing left isn't sent.
- **Live** on item pages (to-dos, messages, docs, files, check-in
  questions) and on lists and the board, reactions included. Not the
  feed or the project page.
- **In place, quietly marked:** what's new slides in with a short
  highlight; nothing moves what you're reading or typing in.
- **Browser notifications** (Web Push) later, not now.

## The lantern

- **The menu:** a lantern icon (`bi-lamp` or a lantern of our own) in the navigation with the number of unread
  notifications. Opening it shows them grouped by item, newest first:
  - the item's title, kind icon, project and client badge;
  - what happened ("Ada commented", "Bob completed it", "Cleo reacted
    👍", "You were mentioned"), with the excerpt where there is one
    (`|excerpt`);
  - when.

  Unread ones on top, then the latest 30 read ones. "Mark all as read".
  A link to the whole list.
- **The page** `/lantern/`: the same, paginated like the feed, with filters
  "unread" and "mentions only".
- **Reading:**
  - opening an item marks its notifications read, and those of its
    comments;
  - clicking an entry opens the item, at the comment where it applies;
  - "mark as read" and "mark as unread" per item.
- **The model:** `Notification.read_at` (null: unread). Mail delivery
  gains `none`. `send_mails` leaves out notifications read before
  sending, and deletes nothing it would need for merging.
- **Visibility:** `_deliverable()`'s rules apply when listing, not only
  when mailing. A notification about something the person can't see
  any more isn't shown; it stays in the database, unseen.
- **API and CLI:**
  - `GET /api/v1/lantern/` (cursor-paginated, `unread`, `mentions`);
  - `POST /api/v1/lantern/read/` (all, or by item);
  - `biwak lantern [--unread] [--read ITEM|--all]`.

## Live updates

One websocket per browser tab (`/ws/live/`, Channels, the same ASGI
setup as `collaboration.md`).

- **The page says what it shows:** the item, or the list. The consumer
  checks access on joining (`item_for()` rules: `visible_to()`, for
  clients only visible items) and again when access changes, through the
  same `check_access()` mechanism as the live editor.
- **The person's own group** gets the lantern count and new entries.
- **Never content through the websocket.** Operations announce "this
  item changed" (after commit, with the kind of change and the ids). The
  browser then fetches the changed part through the normal views (htmx
  GET of a fragment): the comment, the reactions block, the to-do row,
  the board column. Every fragment goes through the same permission
  checks as the page. A client is never sent a fragment of something
  internal, because the fragment views answer 404 for them as for
  everything else.
- **What changes live:**
  - **Item pages:** new or edited comments, reactions (on the item and
    on comments), completion and reopening, edits of the title and text
    when not editing them oneself, assignees, the due date, trashing
    (the page says so and offers to go back).
  - **Lists and the board:** to-dos added, completed or reopened,
    renamed, moved between groups and lists, reordered, trashed;
    reactions on the rows.
- **Not disturbing:**
  - new things slide in with a short highlight (`.wb-live-new`, fading
    out);
  - the scroll position stays;
  - a form being edited is never replaced: its block waits, with a small
    "changed by Ada" note, until the form is saved or closed;
  - one's own changes don't come back as live updates;
  - several changes within a second are fetched once.
- **Offline and reconnecting:** after a reconnect the page fetches what
  it shows once, so nothing is missed. Without JavaScript or websockets
  everything works as today.
- **Load:** the announcements are tiny and only go to tabs showing the
  item or list. Fragments are fetched by the tabs that need them,
  through the normal caches. No polling.

## Done when

- **The lantern:**
  - the menu, the page, reading by opening and by marking;
  - the count updating live;
  - mail delivery "none";
  - read notifications left out of mails and digests (a test for each);
  - a client never seeing a notification about something internal;
  - the API and CLI.
- **Live:**
  - Django tests of the consumer: joining refused for internal items as
    a client (and for others' limited projects); access lost while
    connected; announcements after commit only; nothing announced to
    tabs not showing the item.
  - Fragment views for every live region tested as staff and as a
    client (404 for internal).
- **Playwright with two browsers:**
  - a comment, a reaction and a completion appearing for the other;
  - a to-do added and moved on a board appearing for the other;
  - a form being edited not replaced;
  - a client's open page not receiving an internal change;
  - reconnecting after being offline.

## Questions before building

- How long read notifications stay in the lantern list (proposed: they're
  kept, as decided for the records; the menu shows the latest 30, the
  page pages through all).
- The wording of the entries; proposed above.
