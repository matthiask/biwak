# The lantern and live updates

An in-app inbox for notifications, the **lantern** (named 2026-11-21,
after Biwak's camp theme; avoiding "Hey!", the name of Basecamp's mail
product), and pages
that update while they're open: comments, reactions and changes by others
appear without reloading.

**Status:** built and merged (2026-11-21, with `collaboration`; the follow-ups too): the
lantern (`biwak/activity/lantern.py`, the menu, `/lantern/`, reading,
bookmarking, mail delivery "none", the favicon dot, `GET /api/v1/lantern/`,
`POST /api/v1/lantern/read/`, `biwak lantern`, CLI 0.21.0) and live
updates (`biwak/live/`, `frontend/live.js`, `frontend/lantern.js`). How
it was built and what was decided on the way: "Built" below; open
questions at the end.

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
  notifications, shown as a small red dot like the one on the tab's icon
  (on a phone the menu spans the screen below the bar),
  without a number (decided 2026-11-21; the number is in the button's
  tooltip and read to screen readers). Opening it shows them grouped by item, newest first:
  - the item's title, kind icon and project (no client badge: calmer,
    and the item's page shows it, decided 2026-11-21);
  - what happened ("Ada commented", "Bob completed it", "Cleo reacted
    👍", "You were mentioned"), with the excerpt where there is one
    (`|excerpt`);
  - when.

  Unread ones on top, then the latest 30 read ones. "Mark all as read".
  A link to the whole list.
- **The page** `/lantern/`: the same, paginated like the feed, with filters
  "unread" and "mentions only".
- **Reading** only through the lantern (decided 2026-11-21, replacing
  "opening an item marks its notifications read"):
  - clicking an entry in the menu or on the page marks the item's
    notifications read (those of its comments too) and opens the item, at
    the comment where it applies;
  - "mark as read" and "mark all as read";
  - opening the item some other way (the feed, a list, a mail's link, a
    live update) reads nothing;
  - "mark as unread" per item.
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

- **Bookmarking** (decided 2026-11-21; "Bookmark", not "Pin", decided
  2026-11-21 too: pinned messages on the board keep "Pin"): an entry's
  item can be bookmarked (the existing bookmarks, no new concept, the
  bookmark icons `bookmark` and `bookmark-fill` used elsewhere);
  bookmarked items with notifications appear in a "Bookmarked" section
  at the top of the menu and the page, read or not, with their latest
  notification, until the bookmark is removed. The bookmarks page shows
  the same items.
- **Mark as unread** per item (also in the menu, next to each entry),
  bringing the item's latest notification back to unread. Marked unread
  means no mail (decided 2026-11-21): a notification marked unread by
  hand is never mailed afterwards, neither by each change nor in the
  digest (`Notification.marked_unread_at`, left out by `send_mails`).
- **Switching mail back from "none"** (decided 2026-11-21: as built):
  whatever is unread and wasn't marked unread by hand is mailed with the
  next mail or digest, all at once; no special case for the time of the
  switch.
- **The favicon** (decided 2026-11-21, configurable): with the setting
  on, the browser tab's icon shows a dot when there are unread
  notifications, updated live; the setting (`User.lantern_in_favicon`,
  on by default, decided 2026-11-21: nobody has chosen yet, no data
  migration) sits in the notifications section of the settings
  page. Drawn on a canvas from the normal favicon; without the setting
  or without JavaScript the icon stays as it is.

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
  - the menu, the page, reading by following an entry and by marking;
  - the count updating live; the favicon dot with the setting on and
    not without it;
  - bookmarking and removing the bookmark, mark as unread;
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

## Built (2026-11-21)

- **Model:** `Notification.read_at`; `MailDelivery.NONE` ("No mails");
  `User.lantern_in_favicon`. `notify()` moving an unsent notification
  forward (a merged edit) makes it unread again: the change is new.
- **Mails:** `send_mails` and `_claim()` skip read notifications; they're
  kept (sent_at stays empty, they never go out later unless marked unread
  again). A mail or digest with nothing left isn't sent.
- **Listing** (`lantern.notifications_for()`, `wanted()`): items the
  person sees now (`visible_to()`), for clients only events of the time
  clients saw the item, then `_deliverable()`'s level check. Pages of the
  page and the API may hold fewer entries than asked for (level
  "nothing" is checked after loading the page).
- **Reading:** an entry's links go through `/lantern/<notification>/`
  (`views.lantern_open`), which reads the item's notifications (the entry
  stands for the item) and redirects to the item, at the comment; a link,
  so it works without JavaScript; 404 for others' notifications and items
  one doesn't see. The item pages read nothing (decided 2026-11-21; built
  first as reading when opened). "Mark as unread" brings the item's
  newest notification back.
- **Bookmarking:** "Bookmark" and "Remove the bookmark" in the lantern
  (`lantern.bookmark()`, `unbookmark()`, `POST /lantern/bookmark/`); a
  bookmark made on the item's page counts too. Bookmarked items are in
  "Bookmarked" at the top (latest notification, read or not) and not in
  the other sections. The API's entries say `bookmarked` (was `pinned`,
  never released).
- **The menu:** `frontend/lantern.js` fetches the count
  (`/lantern/count/`) on every page and when told, the menu
  (`/lantern/menu/`) when opened; its buttons post without leaving the
  page. Without JavaScript the menu has the link to `/lantern/`.
- **The websocket** (`biwak/live/consumers.py`, `/ws/live/?item=ID`, one
  per tab): joining checks `visible_to()` (4404 like the pages' 404, 4401
  without a login); the item's group is the staff one or the clients' one
  (`announce.item_group()`), and an announcement goes to the clients'
  group only if it happened while clients saw the item and they see the
  watched item. It joins the live editor's project and person groups and
  checks again on their `access.check` (and every 60 seconds); made a
  client meanwhile, it switches groups. Messages carry IDs and the kind
  of change only, never text or names; the actor's own pages aren't
  told.
- **Announcements** (`biwak/live/announce.py`): every event of an item
  (`record()`) tells the pages of the item and its parent; reordering,
  the lists a to-do left, groups added, renamed, moved or removed, and
  reactions removed are told explicitly. After the commit only.
- **The pages** (`frontend/live.js`): the page fetches itself through
  its view and takes over its regions: `[data-live]` replaced, children of
  `[data-live-list]` added, removed, reordered. A region with focus in a
  field, a changed field, an open `<details>` or an open peek waits with
  "Changed meanwhile: shown once you save or close this." (no name: names
  don't go through the websocket) and takes over once left. A page whose
  item is gone says "This isn’t here anymore: it was trashed, or you
  can’t see it anymore." with a link back. After reconnecting it fetches
  once; several changes within 300 ms are fetched once.
- **The doc's editor page** has no `/ws/live/` (one socket per tab: the
  editor's); its lantern count is fetched when it loads.

## Fixed after the visibility review of the live features (2026-11-21)

- **The lantern's ping** (`announce.lantern_changed()`) about an event
  goes only to those who see its item then, and to clients only if the
  event happened while clients saw the item: a `notify()` running after
  another request made an internal item visible pinged the client's tabs.
  (`notify()` leaving such clients out altogether, and the mails, are
  fixed on main, branch `mail-race`.)
- **Logging out** closes the tabs' websockets of that login session at
  once (4401), and logging out everywhere those of the others: before,
  they kept hearing changes until the next check (60 seconds). Like the
  live editor's (`collaboration.md`).
- **Reading and marking unread** touch only the notifications listed
  (`notifications_for()`): "Mark all as read" counted (`{"read": N}` in
  the API) and read those about items the person can't see anymore, and
  "Mark as unread" could bring back a client's notification of an
  internal event.
- **Every ping about an item** goes through the same filter as
  `notify()`'s: removing a reaction pinged the tabs of everybody notified
  of it, also of a client who couldn't see the item anymore; now only who
  sees it, clients only for events of the time they saw it. Bookmarking,
  removing the bookmark and marking unread pass their item too.
- **Losing access doesn't depend on one message:** the websocket checks
  access again before passing on every announcement and ping (a few
  queries; announcements only go to the tabs showing the item, and are
  rare), not only on `access.check` and every 60 seconds. A lost
  `access.check` (Redis evicting it, or a change in the database
  directly) let a page hear of changes until the next 60-second check.
  Chosen over a shorter timer: no window at all, and no load from idle
  tabs.
- **Limits:** `?item=` longer than 18 digits closes with 4404 (it
  crashed the consumer); at most 50 websockets per person and process
  (confirmed 2026-11-21, to be tuned after real use), more close with 4429 and the page reconnects later, backing
  off like after being offline. The live editor's limits are in
  `collaboration.md`.

## Decided after the review (2026-11-21)

- **Reading through a form button:** following an entry posts a small
  form styled as a link (it marks read and redirects to the item), so
  another site can't mark someone's notifications read by embedding the
  link; it still works without JavaScript. *Built:* `lantern_open` is
  `@require_POST`: a GET answers 405 and reads nothing (a redirect without
  reading would only hide the link's old meaning); the forms carry the
  CSRF token, `frontend/lantern.js` lets them post as they are instead of
  fetching them.
- **Following one entry reads the whole item** (the menu groups by item).
- **An edit merged into a notification marked unread** stays unmailed; a
  new event is mailed as usual.
- **Assigned and mentioned in one change:** one notification, the
  assignment, saying "assigned you (and mentioned you)"; the mention adds
  nothing on top of being assigned. Mentions in a later edit or a
  comment notify as usual. Basecamp sends two, which is annoying.
  *Built:* `items.operations.assign(mentioned=(event, people))`, called by
  `create_todo()` and `update_todo()` with what `mentions.update()`
  returned: the assignment event gets `mentioned` for those both assigned
  and mentioned, and the `created`/`edited` event moves them from its
  `mentioned` to `assigned`, which `notify.candidates()` leaves out (a
  merged edit mentioning them again still tells them). Wording in
  `mails.describe()`: "Ada assigned you (and mentioned you)."; the lantern
  doesn't add "You were mentioned." to it. Only the mention is
  deduplicated: assigned-only people still get the `created` and the
  `assigned` notifications as before.

## Questions (built the way described meanwhile)

- The wording of "No mails", "Changed meanwhile: …",
  "This isn’t here anymore: …", the entries ("Cleo Example reacted 👍",
  "You were mentioned.").
- The menu shows at most 100 unread notifications (the page has all):
  a value the spec didn't fix.

**Entries are links again** (decided 2026-11-21): following one posted a
form, so its address didn't show on hovering and it couldn't open in a
new tab. Now each entry is a link to where it applies; a click or a
middle click posts `lantern/<id>/` in the background (`keepalive`,
so it survives leaving the page), which reads the item's notifications
(204). Not read: without JavaScript, or "Open in new tab" from the
browser's context menu; "Mark as read" covers those. The view still only
posts, so another site can't read somebody's notifications.
